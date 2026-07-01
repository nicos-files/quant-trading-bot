from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR
from src.utils.atomic_io import atomic_write_json

_DAILY_CLOSE_DIR = "daily_close"


def generate_binance_live_daily_close(
    *,
    artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR,
    date_utc: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    target_date = _normalize_date(date_utc or moment.strftime("%Y%m%d"))
    live_result = _load_json(root / "binance_live_micro_submit_result.json")
    readonly = _load_json(root / "binance_mainnet_readonly_preflight.json")
    operations = _load_json(root / "binance_live_operations_status.json")
    incident = _load_json(root / "binance_live_incident_report.json")

    live_for_day = _artifact_matches_day(live_result, target_date)
    submit_attempts = 1 if live_for_day and bool((live_result or {}).get("submit_attempted")) else 0
    successful_placements = int((live_result or {}).get("placed_count") or 0) if live_for_day else 0
    rejected_attempts = int((live_result or {}).get("rejected_count") or 0) if live_for_day else 0
    daily_notional_used = float((live_result or {}).get("requested_notional") or 0.0) if live_for_day and bool((live_result or {}).get("daily_cap_consumed")) else 0.0
    daily_order_count = 1 if daily_notional_used > 0 else 0
    reconciliation_summary = _choose_reconciliation(live_result=live_result if live_for_day else None, readonly=readonly)
    open_orders_count = _choose_open_orders_count(live_result=live_result if live_for_day else None, readonly=readonly)
    live_mode = str((operations or {}).get("live_mode") or "UNKNOWN") if isinstance(operations, Mapping) else "UNKNOWN"
    balances_summary = dict((readonly or {}).get("balances") or {}) if isinstance(readonly, Mapping) else {}
    incidents_generated = 1 if _artifact_matches_day(incident, target_date) else 0
    soak_day_status, soak_blockers = _derive_soak_day_status(
        live_for_day=live_for_day,
        live_result=live_result,
        submit_attempts=submit_attempts,
        successful_placements=successful_placements,
        daily_notional_used=daily_notional_used,
        reconciliation_summary=reconciliation_summary,
        open_orders_count=open_orders_count,
    )
    next_mode = "HALTED" if soak_day_status == "FAIL" else ("OFF" if soak_day_status == "PASS" else "ARMED_MANUAL")

    payload = {
        "date_utc": target_date,
        "live_mode": live_mode,
        "submit_attempts": submit_attempts,
        "successful_placements": successful_placements,
        "rejected_attempts": rejected_attempts,
        "daily_notional_used": daily_notional_used,
        "daily_order_count": daily_order_count,
        "reconciliation_status": reconciliation_summary,
        "open_orders_count": open_orders_count,
        "balances_summary": balances_summary,
        "incidents_generated": incidents_generated,
        "next_recommended_mode": next_mode,
        "soak_day_status": soak_day_status,
        "soak_blockers": soak_blockers,
        "generated_at_utc": moment.isoformat(),
    }
    daily_root = root / _DAILY_CLOSE_DIR
    daily_root.mkdir(parents=True, exist_ok=True)
    json_path = daily_root / f"binance_live_daily_close_{target_date}.json"
    md_path = daily_root / f"binance_live_daily_close_{target_date}.md"
    payload["artifacts"] = {
        json_path.name: str(json_path),
        md_path.name: str(md_path),
    }
    atomic_write_json(json_path, payload)
    md_path.write_text(_build_markdown(payload), encoding="utf-8")
    return payload


def _derive_soak_day_status(
    *,
    live_for_day: bool,
    live_result: Any,
    submit_attempts: int,
    successful_placements: int,
    daily_notional_used: float,
    reconciliation_summary: Mapping[str, Any],
    open_orders_count: int,
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if not live_for_day:
        return "INCOMPLETE", ["live_result_missing_for_date"]
    if submit_attempts != 1:
        blockers.append(f"unexpected_submit_attempts:{submit_attempts}")
    if daily_notional_used > 5.0:
        blockers.append(f"daily_notional_exceeds_cap:{daily_notional_used}")
    if int(reconciliation_summary.get("count") or 0) != 0:
        blockers.append("reconciliation_not_clean")
    if open_orders_count != 0:
        blockers.append(f"unexpected_open_orders:{open_orders_count}")
    status = str((live_result or {}).get("status") or "").upper() if isinstance(live_result, Mapping) else ""
    if status in {"ERROR", "CRITICAL"}:
        blockers.append(f"unresolved_live_status:{status}")
    if successful_placements <= 0:
        blockers.append("no_successful_live_placement")
    if blockers:
        if "live_result_missing_for_date" in blockers:
            return "INCOMPLETE", blockers
        return "FAIL", blockers
    return "PASS", []


def _choose_reconciliation(*, live_result: Any, readonly: Any) -> dict[str, Any]:
    if isinstance(live_result, Mapping) and isinstance(live_result.get("reconciliation_summary"), Mapping):
        return dict(live_result.get("reconciliation_summary") or {})
    if isinstance(readonly, Mapping) and isinstance(readonly.get("reconciliation_summary"), Mapping):
        return dict(readonly.get("reconciliation_summary") or {})
    return {"count": 0, "highest_severity": "INFO", "blocking_count": 0}


def _choose_open_orders_count(*, live_result: Any, readonly: Any) -> int:
    if isinstance(live_result, Mapping) and live_result.get("post_open_orders_count") is not None:
        return int(live_result.get("post_open_orders_count") or 0)
    if isinstance(readonly, Mapping):
        return len(list(readonly.get("open_orders") or []))
    return 0


def _artifact_matches_day(payload: Any, target_date: str) -> bool:
    if not isinstance(payload, Mapping):
        return False
    stamp = _parse_datetime(((payload.get("heartbeat") or {}).get("last_updated_at"))) or _parse_datetime(payload.get("generated_at_utc"))
    return bool(stamp and stamp.strftime("%Y%m%d") == target_date)


def _normalize_date(raw: str) -> str:
    text = str(raw or "").strip()
    if len(text) == 8 and text.isdigit():
        return text
    raise ValueError(f"Invalid YYYYMMDD date: {raw!r}")


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _build_markdown(payload: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# Binance Live Daily Close",
            "",
            f"- Date UTC: {payload.get('date_utc')}",
            f"- Live Mode: {payload.get('live_mode')}",
            f"- Submit Attempts: {payload.get('submit_attempts')}",
            f"- Successful Placements: {payload.get('successful_placements')}",
            f"- Rejected Attempts: {payload.get('rejected_attempts')}",
            f"- Daily Notional Used: {payload.get('daily_notional_used')}",
            f"- Daily Order Count: {payload.get('daily_order_count')}",
            f"- Open Orders Count: {payload.get('open_orders_count')}",
            f"- Soak Day Status: {payload.get('soak_day_status')}",
            f"- Next Recommended Mode: {payload.get('next_recommended_mode')}",
        ]
    )
