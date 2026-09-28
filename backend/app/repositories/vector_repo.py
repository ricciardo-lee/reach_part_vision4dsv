"""Qdrant vector repository abstraction."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class VectorHit:
    id: str
    score: float
    payload: dict[str, Any]


class InMemoryVectorRepo:
    """Fallback for local tests / offline FAISS-less MVP without Qdrant."""

    def __init__(self) -> None:
        self.collection = "memory"
        self.vector_size = 0
        self._ids: list[str] = []
        self._vectors: np.ndarray | None = None
        self._payloads: list[dict[str, Any]] = []

    @property
    def ready(self) -> bool:
        return self._vectors is not None and len(self._ids) > 0

    def ensure_collection(self, name: str, vector_size: int) -> None:
        self.collection = name
        self.vector_size = vector_size
        self._ids = []
        self._vectors = np.zeros((0, vector_size), dtype=np.float32)
        self._payloads = []

    def upsert(self, ids: list[str], vectors: np.ndarray, payloads: list[dict[str, Any]]) -> None:
        if self._vectors is None:
            self.ensure_collection(self.collection, vectors.shape[1])
        assert self._vectors is not None
        self._ids.extend(ids)
        self._vectors = np.vstack([self._vectors, vectors.astype(np.float32)])
        self._payloads.extend(payloads)

    def search(
        self,
        vector: np.ndarray,
        top_k: int = 20,
        category_id: str | None = None,
    ) -> list[VectorHit]:
        if not self.ready or self._vectors is None:
            return []
        q = vector.astype(np.float32).reshape(-1)
        q = q / max(float(np.linalg.norm(q)), 1e-12)
        sims = self._vectors @ q
        order = np.argsort(-sims)
        hits: list[VectorHit] = []
        for idx in order:
            payload = self._payloads[int(idx)]
            if category_id and payload.get("category_id") and payload["category_id"] != category_id:
                # Soft filter not applied here; caller may soft-weight
                pass
            hits.append(
                VectorHit(id=self._ids[int(idx)], score=float(sims[int(idx)]), payload=payload)
            )
            if len(hits) >= top_k:
                break
        return hits

    def count(self) -> int:
        return len(self._ids)


class QdrantVectorRepo:
    def __init__(self, url: str = "http://127.0.0.1:6333", api_key: str | None = None) -> None:
        from qdrant_client import QdrantClient

        self._client = QdrantClient(url=url, api_key=api_key)
        self.collection = "parts_360_current"
        self.vector_size = 0

    @property
    def ready(self) -> bool:
        try:
            info = self._client.get_collections()
            names = {c.name for c in info.collections}
            if self.collection not in names:
                # Alias resolution: try listing aliases if available
                try:
                    aliases = self._client.get_aliases()
                    alias_names = {a.alias_name for a in aliases.aliases}
                    if self.collection not in alias_names:
                        return False
                except Exception:
                    return False
            return self.count() > 0
        except Exception:
            return False

    def ensure_collection(self, name: str, vector_size: int) -> None:
        from qdrant_client.http import models as qm

        self.collection = name
        self.vector_size = vector_size
        existing = {c.name for c in self._client.get_collections().collections}
        if name not in existing:
            self._client.create_collection(
                collection_name=name,
                vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
            )
            logger.info("Created Qdrant collection %s dim=%d", name, vector_size)

    def set_alias(self, collection_name: str, alias: str = "parts_360_current") -> None:
        from qdrant_client.http import models as qm

        try:
            self._client.update_collection_aliases(
                change_aliases_operations=[
                    qm.DeleteAliasOperation(delete_alias=qm.DeleteAlias(alias_name=alias)),
                ]
            )
        except Exception:
            pass
        self._client.update_collection_aliases(
            change_aliases_operations=[
                qm.CreateAliasOperation(
                    create_alias=qm.CreateAlias(collection_name=collection_name, alias_name=alias)
                )
            ]
        )
        self.collection = alias

    def upsert(self, ids: list[str], vectors: np.ndarray, payloads: list[dict[str, Any]]) -> None:
        from qdrant_client.http import models as qm

        points = [
            qm.PointStruct(id=i if _is_uuid(i) else str(uuid.uuid5(uuid.NAMESPACE_URL, i)), vector=v.tolist(), payload=p)
            for i, v, p in zip(ids, vectors, payloads)
        ]
        self._client.upsert(collection_name=self.collection, points=points)

    def search(
        self,
        vector: np.ndarray,
        top_k: int = 20,
        category_id: str | None = None,
    ) -> list[VectorHit]:
        from qdrant_client.http import models as qm

        query_filter = None
        # Soft filter: do not hard-filter by default; category used by caller.
        _ = category_id
        result = self._client.search(
            collection_name=self.collection,
            query_vector=vector.astype(np.float32).tolist(),
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )
        return [
            VectorHit(id=str(p.id), score=float(p.score), payload=dict(p.payload or {}))
            for p in result
        ]

    def count(self) -> int:
        try:
            return int(self._client.count(self.collection, exact=True).count)
        except Exception:
            return 0


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except Exception:
        return False


def create_vector_repo(backend: str, url: str = "http://127.0.0.1:6333", api_key: str | None = None):
    backend = backend.lower().strip()
    if backend in {"memory", "inmemory", "faiss"}:
        return InMemoryVectorRepo()
    if backend == "qdrant":
        return QdrantVectorRepo(url=url, api_key=api_key)
    raise ValueError(f"Unknown vector backend: {backend}")
