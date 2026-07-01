from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR
from src.utils.atomic_io import atomic_write_json

_RESULT_FILENAME = "binance_live_micro_submit_result.json"
_REVIEW_FILENAME = "binance_live_manual_review.json"


def acknowledge_binance_live_error_review(
    *,
    artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR,
    reason: str,
    operator_action: str = "manual_review_recorded",
    allow_retry_same_utc_day: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    live_result = _load_json(root / _RESULT_FILENAME)
    if not isinstance(live_result, Mapping):
        payload = {
            "ok": False,
            "status": "BLOCKED",
            "reason": "live_result_missing_or_unreadable",
            "blocking_reasons": ["live_result_missing_or_unreadable"],
            "artifacts": {_REVIEW_FILENAME: str(root / _REVIEW_FILENAME)},
            "reviewed_at_utc": moment.isoformat(),
        }
        atomic_write_json(root / _REVIEW_FILENAME, payload)
        return payload

    payload = {
        "ok": True,
        "status": "ACKNOWLEDGED",
        "review_id": f"live-review-{moment.strftime('%Y%m%d-%H%M%S')}",
        "reviewed_at_utc": moment.isoformat(),
        "reviewed_by_operator": True,
        "reason": str(reason or "").strip(),
        "acknowledged_error_run_id": str(live_result.get("run_id") or ""),
        "acknowledged_failure_stage": live_result.get("failure_stage"),
        "acknowledged_blocking_reasons": [str(item) for item in list(live_result.get("blocking_reasons") or []) if str(item).strip()],
        "operator_action": str(operator_action or "manual_review_recorded").strip(),
        "allow_retry_same_utc_day": bool(allow_retry_same_utc_day),
        "retry_same_day_enabled": False,
        "artifacts": {_REVIEW_FILENAME: str(root / _REVIEW_FILENAME)},
    }
    atomic_write_json(root / _REVIEW_FILENAME, payload)
    return payload


def load_binance_live_manual_review(*, artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR) -> dict[str, Any] | None:
    root = Path(artifacts_dir)
    payload = _load_json(root / _REVIEW_FILENAME)
    return payload if isinstance(payload, dict) else None


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
