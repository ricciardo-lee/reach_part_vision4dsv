from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from app.models import RecognitionResult, RecognitionSession


@dataclass
class EvalStats:
    labeled_sessions: int = 0
    top1_hits: int = 0
    top3_hits: int = 0
    reject_count: int = 0
    reject_eligible: int = 0
    top1_hit_rate: Optional[float] = None
    top3_hit_rate: Optional[float] = None
    reject_rate: Optional[float] = None


def _candidate_codes(candidates: Any) -> List[str]:
    codes: List[str] = []
    if not isinstance(candidates, list):
        return codes
    for item in candidates:
        if not isinstance(item, dict):
            continue
        code = item.get("category_code") or item.get("mapped_category_code")
        name = item.get("category_name") or item.get("name")
        if code:
            codes.append(str(code).strip())
        elif name:
            codes.append(str(name).strip())
    return codes


def score_session(
    *,
    confirmed_code: Optional[str],
    confirmed_name: Optional[str],
    mapped_code: Optional[str],
    mapped_name: Optional[str],
    candidates: Any,
    confidence: Optional[float],
    reject_confidence: float,
) -> dict:
    """Score one labeled session for Top-1 / Top-3 / reject."""
    gold = (confirmed_code or "").strip() or (confirmed_name or "").strip()
    top1 = (mapped_code or "").strip() or (mapped_name or "").strip()
    codes = _candidate_codes(candidates)
    # Ensure Top-1 is considered in Top-3 pool
    pool = ([top1] if top1 else []) + [c for c in codes if c != top1]
    pool = pool[:3]

    top1_hit = bool(gold and top1 and gold == top1)
    # Also allow name match against candidate names when codes differ in format
    if not top1_hit and gold and confirmed_name:
        names = []
        if isinstance(candidates, list):
            for item in candidates[:3]:
                if isinstance(item, dict):
                    names.append(str(item.get("category_name") or item.get("name") or ""))
        top1_hit = gold == top1 or (mapped_name or "") == confirmed_name
        top3_hit = top1_hit or confirmed_name in names or gold in pool
    else:
        top3_hit = top1_hit or (gold in pool)

    conf = float(confidence) if confidence is not None else None
    is_reject = conf is not None and conf < reject_confidence
    return {
        "gold": gold,
        "top1_hit": top1_hit,
        "top3_hit": top3_hit,
        "is_reject": is_reject,
    }


async def compute_eval_stats(*, reject_confidence: float = 0.45) -> EvalStats:
    sessions = await RecognitionSession.exclude(confirmed_category_name=None).all()
    stats = EvalStats()
    for session in sessions:
        if not (session.confirmed_category_code or session.confirmed_category_name):
            continue
        result = await RecognitionResult.filter(session_id=session.id, success=True).order_by("-id").first()
        if not result:
            continue
        stats.labeled_sessions += 1
        scored = score_session(
            confirmed_code=session.confirmed_category_code,
            confirmed_name=session.confirmed_category_name,
            mapped_code=result.mapped_category_code,
            mapped_name=result.mapped_category_name,
            candidates=result.candidates,
            confidence=result.confidence,
            reject_confidence=reject_confidence,
        )
        if scored["top1_hit"]:
            stats.top1_hits += 1
        if scored["top3_hit"]:
            stats.top3_hits += 1
        stats.reject_eligible += 1
        if scored["is_reject"] and not scored["top1_hit"]:
            stats.reject_count += 1

    if stats.labeled_sessions:
        stats.top1_hit_rate = round(stats.top1_hits / stats.labeled_sessions, 4)
        stats.top3_hit_rate = round(stats.top3_hits / stats.labeled_sessions, 4)
    if stats.reject_eligible:
        stats.reject_rate = round(stats.reject_count / stats.reject_eligible, 4)
    return stats
