"""Multi-image product similarity search orchestration."""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from PIL import Image

from app.core.constants import CATEGORY_CN
from app.repositories.vector_repo import VectorHit
from app.services.image_preprocessing import ImagePreprocessor, PreparedImage

logger = logging.getLogger(__name__)


class SearchError(Exception):
    pass


class SearchNotReadyError(SearchError):
    pass


@dataclass
class AggregatedSku:
    sku: str
    category_id: str | None
    score: float
    matched_views: list[str]
    hits: list[VectorHit]


@dataclass
class SearchCandidateItem:
    sku: str
    category_id: str | None = None
    category_cn: str | None = None
    score: float = 0.0
    matched_views: list[str] = field(default_factory=list)
    reason: str = "vector_match"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "category_id": self.category_id,
            "category_cn": self.category_cn,
            "score": self.score,
            "matched_views": list(self.matched_views),
            "reason": self.reason,
        }


@dataclass
class SearchResponse:
    request_id: str
    index_version: str | None = None
    embedding_model: str | None = None
    decision: str = "candidates"
    confidence_level: str = "medium"
    candidates: list[SearchCandidateItem] = field(default_factory=list)
    rejected: bool = False
    reject_reason: str | None = None
    quality_warnings: list[str] = field(default_factory=list)
    latency_ms: float | None = None
    prepared_images: list[PreparedImage] = field(default_factory=list)


class SimilarityService:
    def __init__(
        self,
        embedder: Any,
        vector_repo: Any,
        preprocessor: ImagePreprocessor | None = None,
        index_version: str | None = None,
        aggregate: Literal["max", "topm_mean", "vote"] = "topm_mean",
        topm: int = 3,
        per_image_top_k: int = 30,
        high_score: float = 0.72,
        medium_score: float = 0.55,
        min_margin: float = 0.03,
        category_soft_bonus: float = 0.02,
        enable_dual_path: bool = True,
        white_vector_repo: Any = None,
        white_index_version: str | None = None,
    ) -> None:
        self.embedder = embedder
        self.vector_repo = vector_repo
        self.preprocessor = preprocessor or ImagePreprocessor()
        self.index_version = index_version
        self.aggregate = aggregate
        self.topm = topm
        self.per_image_top_k = per_image_top_k
        self.high_score = high_score
        self.medium_score = medium_score
        self.min_margin = min_margin
        self.category_soft_bonus = category_soft_bonus
        self.enable_dual_path = enable_dual_path
        self.white_vector_repo = white_vector_repo
        self.white_index_version = white_index_version

    @property
    def ready(self) -> bool:
        return bool(getattr(self.embedder, "ready", False)) and bool(
            getattr(self.vector_repo, "ready", False)
        )

    def search(
        self,
        images: list[Image.Image],
        top_k: int = 5,
        category_id: str | None = None,
        focus_points: list | None = None,
        segmenter_predict=None,
    ) -> SearchResponse:
        if not self.ready:
            raise SearchNotReadyError("Search index or embedder is not ready")
        if not images:
            raise SearchError("At least one image is required")

        t0 = time.perf_counter()
        request_id = str(uuid.uuid4())
        prepared = self.preprocessor.prepare_many(
            images, focus_points=focus_points, segmenter_predict=segmenter_predict
        )
        warnings: list[str] = []
        for i, p in enumerate(prepared):
            for w in p.quality.warnings:
                warnings.append(f"image_{i}_{w}")
            if p.foreground_source:
                warnings.append(f"image_{i}_foreground_{p.foreground_source}")

        usable = [p for p in prepared if p.quality.usable and p.quality.weight > 0]
        if not usable:
            return SearchResponse(
                request_id=request_id,
                index_version=self.index_version,
                embedding_model=getattr(self.embedder, "model_id", None),
                decision="needs_reshoot",
                confidence_level="none",
                candidates=[],
                rejected=True,
                reject_reason="all_images_low_quality",
                quality_warnings=warnings,
                latency_ms=(time.perf_counter() - t0) * 1000,
                prepared_images=prepared,
            )

        sku_scores: dict[str, list[tuple[float, VectorHit]]] = defaultdict(list)
        sku_category: dict[str, str | None] = {}
        routes: list[str] = []

        for prep in usable:
            repo, route = self._repo_for(prep)
            routes.append(route)
            warnings.append(f"search_index_{route}")
            vectors = self._embed_prepared(prep)
            weight = prep.quality.weight
            for vec in vectors:
                hits = repo.search(vec, top_k=self.per_image_top_k)
                for hit in hits:
                    sku = str(hit.payload.get("sku") or "")
                    if not sku:
                        continue
                    score = float(hit.score) * weight
                    cid = hit.payload.get("category_id")
                    if category_id and cid == category_id:
                        score += self.category_soft_bonus
                    sku_scores[sku].append((score, hit))
                    sku_category[sku] = cid

        aggregated = self._aggregate(sku_scores, sku_category)
        aggregated.sort(key=lambda x: x.score, reverse=True)
        top = aggregated[: max(top_k, 5)]

        candidates: list[SearchCandidateItem] = []
        for item in top[:top_k]:
            candidates.append(
                SearchCandidateItem(
                    sku=item.sku,
                    category_id=item.category_id,
                    category_cn=CATEGORY_CN.get(item.category_id or "", None),
                    score=round(float(item.score), 6),
                    matched_views=item.matched_views[:5],
                    reason="vector_match",
                )
            )

        decision, confidence, rejected, reject_reason = self._decide(candidates)
        return SearchResponse(
            request_id=request_id,
            index_version=self._response_index_version(routes),
            embedding_model=getattr(self.embedder, "model_id", None),
            decision=decision,
            confidence_level=confidence,
            candidates=candidates,
            rejected=rejected,
            reject_reason=reject_reason,
            quality_warnings=warnings,
            latency_ms=(time.perf_counter() - t0) * 1000,
            prepared_images=prepared,
        )

    def _repo_for(self, prep: PreparedImage):
        """White cutouts search the white index. Full-frame fallback stays on the gallery index."""
        white_ready = self.white_vector_repo is not None and bool(
            getattr(self.white_vector_repo, "ready", False)
        )
        if prep.foreground is not None and white_ready:
            return self.white_vector_repo, "white"
        return self.vector_repo, "full"

    def _response_index_version(self, routes: list[str]) -> str | None:
        used = set(routes)
        if used == {"white"}:
            return self.white_index_version or self.index_version
        if "white" in used and self.white_index_version and self.index_version:
            return f"{self.white_index_version}+{self.index_version}"
        return self.index_version

    def _embed_prepared(self, prep: PreparedImage) -> list[np.ndarray]:
        """Embed the white-background cutout. Use the full photo only when matting failed."""
        image = prep.foreground if prep.foreground is not None else prep.full
        return [self.embedder.embed_image(image)]

    def _aggregate(
        self,
        sku_scores: dict[str, list[tuple[float, VectorHit]]],
        sku_category: dict[str, str | None],
    ) -> list[AggregatedSku]:
        out: list[AggregatedSku] = []
        for sku, pairs in sku_scores.items():
            pairs_sorted = sorted(pairs, key=lambda x: x[0], reverse=True)
            scores = [p[0] for p in pairs_sorted]
            hits = [p[1] for p in pairs_sorted]
            if self.aggregate == "max":
                score = scores[0]
            elif self.aggregate == "vote":
                score = float(len(scores)) + scores[0]
            else:
                m = scores[: self.topm]
                score = float(np.mean(m)) if m else 0.0
            views: list[str] = []
            for h in hits:
                fn = h.payload.get("filename") or h.payload.get("relative_path")
                if fn and fn not in views:
                    views.append(str(fn))
            out.append(
                AggregatedSku(
                    sku=sku,
                    category_id=sku_category.get(sku),
                    score=score,
                    matched_views=views,
                    hits=hits[:10],
                )
            )
        return out

    def _decide(
        self, candidates: list[SearchCandidateItem]
    ) -> tuple[str, str, bool, str | None]:
        if not candidates:
            return "rejected", "none", True, "no_candidates"
        top = candidates[0].score
        margin = candidates[0].score - candidates[1].score if len(candidates) > 1 else 1.0
        if top >= self.high_score and margin >= self.min_margin:
            return "candidates", "high", False, None
        if top >= self.medium_score:
            return "candidates", "medium", False, None
        if top < self.medium_score:
            return "uncertain", "low", False, "low_similarity"
        return "candidates", "medium", False, None

    def is_high_confidence_match(self, result: SearchResponse) -> bool:
        """Accept only high score + sufficient margin (strict gate for SKU direct match)."""
        if result.rejected or not result.candidates:
            return False
        if result.confidence_level != "high":
            return False
        if result.decision != "candidates":
            return False
        top = result.candidates[0].score
        margin = (
            result.candidates[0].score - result.candidates[1].score
            if len(result.candidates) > 1
            else 1.0
        )
        return top >= self.high_score and margin >= self.min_margin

    def is_category_eligible(self, result: SearchResponse, min_score: float | None = None) -> bool:
        """True when retrieval is usable for category-level matching (not high SKU gate)."""
        if result.rejected or not result.candidates:
            return False
        if self.is_high_confidence_match(result):
            return False
        floor = self.medium_score if min_score is None else min_score
        return float(result.candidates[0].score) >= floor

    @staticmethod
    def group_candidates_by_category(
        candidates: list[SearchCandidateItem],
    ) -> dict[str, list[SearchCandidateItem]]:
        """Group SKU candidates by category_id (unknown → '_unknown')."""
        groups: dict[str, list[SearchCandidateItem]] = defaultdict(list)
        for c in candidates:
            key = str(c.category_id or "").strip() or "_unknown"
            groups[key].append(c)
        for key in groups:
            groups[key].sort(key=lambda x: x.score, reverse=True)
        return dict(groups)

    @staticmethod
    def filter_same_category_skus(
        candidates: list[SearchCandidateItem],
        category_id: str,
        *,
        top_n: int = 5,
        relative_floor: float = 0.85,
        min_score: float = 0.0,
    ) -> list[SearchCandidateItem]:
        """Dedup and keep top-N SKUs in one category within score band of the category top."""
        cid = str(category_id or "").strip()
        filtered = [
            c
            for c in candidates
            if str(c.category_id or "").strip() == cid and float(c.score) >= min_score
        ]
        if not filtered:
            return []
        # Deduplicate by SKU keeping highest score.
        best: dict[str, SearchCandidateItem] = {}
        for c in filtered:
            prev = best.get(c.sku)
            if prev is None or c.score > prev.score:
                best[c.sku] = c
        ranked = sorted(best.values(), key=lambda x: x.score, reverse=True)
        top_score = ranked[0].score
        floor = top_score * relative_floor
        kept = [c for c in ranked if c.score >= floor]
        return kept[: max(1, top_n)]
