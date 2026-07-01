from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.execution.binance_mainnet_readonly_preflight import (
    ARTIFACTS_SUBDIR,
    DEFAULT_MAINNET_BASE_URL,
    DEFAULT_LIVE_KILL_SWITCH,
    LIVE_KILL_SWITCH_ENV,
)
from src.utils.atomic_io import atomic_write_json

_READONLY_FILENAME = "binance_mainnet_readonly_preflight.json"
_READINESS_FILENAME = "binance_live_readiness.json"
_MAX_ARTIFACT_AGE_MINUTES = 30


def evaluate_binance_live_readiness(
    *,
    artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    readonly_path = root / _READONLY_FILENAME
    result: dict[str, Any] = {
        "ok": False,
        "status": "NOT_READY",
        "live_readiness_status": "NOT_READY",
        "live_submit_allowed": False,
        "base_url": None,
        "mainnet_readonly_ok": False,
        "live_trading_enabled": False,
        "live_kill_switch_active": DEFAULT_LIVE_KILL_SWITCH,
        "server_time_available": False,
        "exchange_filters_available": False,
        "account_checked": False,
        "balances_checked": False,
        "open_orders_checked": False,
        "reconciliation_summary": _empty_reconciliation_summary(),
        "blocking_reasons": [],
        "warnings": [],
        "next_allowed_mode": "blocked",
        "generated_at_utc": moment.isoformat(),
        "artifact_inputs": {
            "mainnet_readonly_preflight": {
                "path": str(readonly_path),
                "exists": readonly_path.exists(),
            }
        },
        "artifacts": {
            _READINESS_FILENAME: str(root / _READINESS_FILENAME),
        },
    }

    readonly_payload = _load_json(readonly_path)
    if not isinstance(readonly_payload, dict):
        result["blocking_reasons"].append("mainnet_readonly_artifact_missing_or_unreadable")
        return _write(root, result)

    result["base_url"] = readonly_payload.get("base_url")
    result["mainnet_readonly_ok"] = bool(readonly_payload.get("ok"))
    result["live_trading_enabled"] = bool(readonly_payload.get("live_trading_enabled"))
    result["live_kill_switch_active"] = bool(readonly_payload.get("live_kill_switch_active", DEFAULT_LIVE_KILL_SWITCH))
    result["server_time_available"] = bool(readonly_payload.get("server_time_available"))
    result["exchange_filters_available"] = bool(readonly_payload.get("exchange_filters_available"))
    result["account_checked"] = bool(readonly_payload.get("account_checked"))
    result["balances_checked"] = bool(readonly_payload.get("balances_checked"))
    result["open_orders_checked"] = bool(readonly_payload.get("open_orders_checked"))
    result["reconciliation_summary"] = dict(readonly_payload.get("reconciliation_summary") or _empty_reconciliation_summary())
    result["warnings"] = list(readonly_payload.get("warnings") or [])

    heartbeat = dict(readonly_payload.get("heartbeat") or {})
    heartbeat_timestamp = _parse_datetime(heartbeat.get("last_updated_at"))
    if heartbeat_timestamp is None:
        result["blocking_reasons"].append("mainnet_readonly_heartbeat_missing")
    elif moment - heartbeat_timestamp > timedelta(minutes=_MAX_ARTIFACT_AGE_MINUTES):
        result["blocking_reasons"].append("mainnet_readonly_artifact_stale")

    if readonly_payload.get("base_url") != DEFAULT_MAINNET_BASE_URL:
        result["blocking_reasons"].append("mainnet_base_url_invalid")
    if not bool(readonly_payload.get("ok")):
        result["blocking_reasons"].append("mainnet_readonly_not_ok")
    if bool(readonly_payload.get("live_trading_enabled")):
        result["blocking_reasons"].append("live_trading_must_remain_disabled")
    if not bool(readonly_payload.get("live_kill_switch_active", DEFAULT_LIVE_KILL_SWITCH)):
        result["blocking_reasons"].append("live_kill_switch_must_be_on_by_default")
    if not bool(readonly_payload.get("server_time_available")):
        result["blocking_reasons"].append("server_time_unavailable")
    if not bool(readonly_payload.get("exchange_filters_available")):
        result["blocking_reasons"].append("exchange_filters_unavailable")
    if not bool(readonly_payload.get("account_checked")):
        result["blocking_reasons"].append("account_check_missing")
    if not bool(readonly_payload.get("balances_checked")):
        result["blocking_reasons"].append("balances_check_missing")
    if not bool(readonly_payload.get("open_orders_checked")):
        result["blocking_reasons"].append("open_orders_check_missing")
    if int((result["reconciliation_summary"] or {}).get("blocking_count") or 0) > 0:
        result["blocking_reasons"].append("readonly_reconciliation_blocking")
    if list(readonly_payload.get("blocking_reasons") or []):
        result["blocking_reasons"].append("mainnet_readonly_has_blocking_reasons")

    result["blocking_reasons"] = _dedupe(result["blocking_reasons"])
    if not result["blocking_reasons"]:
        result["ok"] = True
        result["status"] = "READY_FOR_PREPARE_ONLY"
        result["live_readiness_status"] = "READY_FOR_PREPARE_ONLY"
        result["live_submit_allowed"] = False
        result["next_allowed_mode"] = "prepare_only"
    return _write(root, result)


def _write(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    atomic_write_json(root / _READINESS_FILENAME, payload)
    return payload


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _empty_reconciliation_summary() -> dict[str, Any]:
    return {
        "count": 0,
        "blocking_count": 0,
        "highest_severity": "INFO",
        "counts_by_severity": {"INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0},
        "counts_by_level": {"tolerable_drift": 0, "warning": 0, "error": 0, "critical_hard_stop": 0},
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered