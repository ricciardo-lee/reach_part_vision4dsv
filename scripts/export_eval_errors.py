#!/usr/bin/env python3
"""Export recognition error samples for offline review (consent-gated)."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tortoise import Tortoise  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models import RecognitionResult, RecognitionSession, UploadedImage  # noqa: E402
from app.services.eval_metrics import score_session  # noqa: E402


async def _export(path: Path, only_consent: bool) -> int:
    await Tortoise.init(config=settings.tortoise_config, _enable_global_fallback=True)
    try:
        query = RecognitionSession.exclude(confirmed_category_name=None)
        if only_consent:
            query = query.filter(optimization_consent=True)
        sessions = await query.order_by("-id").all()
        rows = []
        for session in sessions:
            result = await RecognitionResult.filter(session_id=session.id, success=True).order_by("-id").first()
            if not result:
                continue
            scored = score_session(
                confirmed_code=session.confirmed_category_code,
                confirmed_name=session.confirmed_category_name,
                mapped_code=result.mapped_category_code,
                mapped_name=result.mapped_category_name,
                candidates=result.candidates,
                confidence=result.confidence,
                reject_confidence=settings.EVAL_REJECT_CONFIDENCE,
            )
            # Error pool: Top-1 miss or explicit negative feedback
            if scored["top1_hit"] and session.feedback_correct is not False:
                continue
            images = await UploadedImage.filter(session_id=session.id, deleted_at=None).order_by("sort_order")
            rows.append(
                {
                    "public_id": session.public_id,
                    "confirmed_category_code": session.confirmed_category_code or "",
                    "confirmed_category_name": session.confirmed_category_name or "",
                    "mapped_category_code": result.mapped_category_code or "",
                    "mapped_category_name": result.mapped_category_name or "",
                    "part_name": result.part_name or "",
                    "confidence": result.confidence if result.confidence is not None else "",
                    "top1_hit": scored["top1_hit"],
                    "top3_hit": scored["top3_hit"],
                    "feedback_correct": session.feedback_correct,
                    "optimization_consent": session.optimization_consent,
                    "candidates": json.dumps(result.candidates or [], ensure_ascii=False),
                    "image_keys": ";".join(img.object_key for img in images),
                }
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            path.write_text("", encoding="utf-8")
            print(f"No error samples. Wrote empty file: {path}")
            return 0

        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Exported {len(rows)} error samples -> {path}")
        return len(rows)
    finally:
        await Tortoise.close_connections()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export eval error samples")
    parser.add_argument(
        "-o",
        "--output",
        default=str(ROOT / "backend" / "logs" / "eval_errors.csv"),
        help="Output CSV path",
    )
    parser.add_argument(
        "--include-without-consent",
        action="store_true",
        help="Include sessions without optimization_consent (default: consent only)",
    )
    args = parser.parse_args()
    only_consent = not args.include_without_consent
    asyncio.run(_export(Path(args.output), only_consent=only_consent))


if __name__ == "__main__":
    main()
