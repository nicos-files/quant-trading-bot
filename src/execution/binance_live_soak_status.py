from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR
from src.utils.atomic_io import atomic_write_json

_STATUS_FILENAME = "binance_live_soak_status.json"


def evaluate_binance_live_soak_status(
    *,
    artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR,
    days_required: int = 3,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    normalized_days = min(max(int(days_required or 3), 3), 5)
    daily_root = root / "daily_close"
    closes = _load_daily_closes(daily_root)
    recent = closes[:normalized_days]
    days_passed = sum(1 for item in recent if str(item.get("soak_day_status") or "").upper() == "PASS")
    days_failed = sum(1 for item in recent if str(item.get("soak_day_status") or "").upper() == "FAIL")
    blockers: list[str] = []
    if len(recent) < normalized_days:
        blockers.append(f"insufficient_soak_days:{len(recent)}<{normalized_days}")
    for item in recent:
        status = str(item.get("soak_day_status") or "").upper()
        if status == "FAIL":
            blockers.append(f"soak_day_failed:{item.get('date_utc')}")
        if status == "INCOMPLETE":
            blockers.append(f"soak_day_incomplete:{item.get('date_utc')}")

    if len(recent) >= normalized_days and days_passed == normalized_days and not days_failed:
        soak_status = "PASSED"
        next_allowed_step = "scheduled_window_can_be_enabled"
    elif days_failed:
        soak_status = "FAILED"
        next_allowed_step = "investigate_failures"
    else:
        soak_status = "INCOMPLETE"
        next_allowed_step = "continue_soak"

    current_day_status = str(recent[0].get("soak_day_status") or "MISSING") if recent else "MISSING"
    payload = {
        "generated_at_utc": moment.isoformat(),
        "soak_status": soak_status,
        "days_required": normalized_days,
        "days_passed": days_passed,
        "days_failed": days_failed,
        "current_day_status": current_day_status,
        "blockers": blockers,
        "next_allowed_step": next_allowed_step,
        "days": recent,
        "artifacts": {
            _STATUS_FILENAME: str(root / _STATUS_FILENAME),
        },
    }
    atomic_write_json(root / _STATUS_FILENAME, payload)
    return payload


def _load_daily_closes(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    payloads: list[dict[str, Any]] = []
    for path in sorted(root.glob("binance_live_daily_close_*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            payloads.append(data)
    return payloads
