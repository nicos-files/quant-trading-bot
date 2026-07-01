from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR
from src.execution.binance_live_readiness import evaluate_binance_live_readiness
from src.utils.atomic_io import atomic_write_json

LIVE_TRADING_ENABLED_ENV = "BINANCE_LIVE_TRADING_ENABLED"
LIVE_CONFIRM_SUBMIT_ENV = "BINANCE_LIVE_CONFIRM_SUBMIT"
LIVE_KILL_SWITCH_ENV = "BINANCE_LIVE_KILL_SWITCH"
LIVE_BASE_URL_ENV = "BINANCE_LIVE_BASE_URL"
LIVE_ALLOWED_SYMBOLS_ENV = "BINANCE_LIVE_ALLOWED_SYMBOLS"
LIVE_MAX_NOTIONAL_ENV = "BINANCE_LIVE_MAX_NOTIONAL"
LIVE_MAX_DAILY_ORDERS_ENV = "BINANCE_LIVE_MAX_DAILY_ORDERS"
LIVE_MAX_OPEN_ORDERS_ENV = "BINANCE_LIVE_MAX_OPEN_ORDERS"
LIVE_API_KEY_ENV = "BINANCE_LIVE_API_KEY"
LIVE_API_SECRET_ENV = "BINANCE_LIVE_API_SECRET"
MAINNET_API_KEY_ENV = "BINANCE_MAINNET_API_KEY"
MAINNET_API_SECRET_ENV = "BINANCE_MAINNET_API_SECRET"

DEFAULT_LIVE_BASE_URL = "https://api.binance.com"
_MAX_FIRST_LIVE_NOTIONAL = 5.0
_PLAN_FILENAME = "binance_live_micro_submit_plan.json"
_READINESS_FILENAME = "binance_live_readiness.json"


def run_binance_live_micro_submit_prepare_only(
    *,
    artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
    prepare_only: bool = True,
    execute: bool = False,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    source_env: Mapping[str, str] = env if env is not None else os.environ

    result: dict[str, Any] = {
        "ok": False,
        "status": "BLOCKED",
        "mode": "BINANCE_LIVE_MICRO_SUBMIT_PREPARE_ONLY",
        "prepare_only": bool(prepare_only),
        "execute_requested": bool(execute),
        "base_url": str(source_env.get(LIVE_BASE_URL_ENV) or DEFAULT_LIVE_BASE_URL).strip().rstrip("/"),
        "live_trading_enabled": str(source_env.get(LIVE_TRADING_ENABLED_ENV) or "").strip() == "1",
        "submit_attempted": False,
        "max_notional": _safe_float(source_env.get(LIVE_MAX_NOTIONAL_ENV), 0.0),
        "allowed_symbols": _parse_symbols(source_env.get(LIVE_ALLOWED_SYMBOLS_ENV)),
        "max_daily_orders": _safe_int(source_env.get(LIVE_MAX_DAILY_ORDERS_ENV), 0),
        "max_open_orders": _safe_int(source_env.get(LIVE_MAX_OPEN_ORDERS_ENV), 0),
        "kill_switch_status": "ACTIVE" if str(source_env.get(LIVE_KILL_SWITCH_ENV) or "1").strip() != "0" else "INACTIVE",
        "readiness_dependency": {
            "path": str(root / _READINESS_FILENAME),
            "exists": (root / _READINESS_FILENAME).exists(),
            "status": None,
            "live_readiness_status": None,
        },
        "blocking_reasons": [],
        "warnings": ["prepare_only_no_live_order_executed"],
        "generated_at_utc": moment.isoformat(),
        "artifacts": {
            _PLAN_FILENAME: str(root / _PLAN_FILENAME),
        },
    }

    readiness_payload = _load_json(root / _READINESS_FILENAME)
    if not isinstance(readiness_payload, dict):
        result["blocking_reasons"].append("live_readiness_artifact_missing_or_unreadable")
        return _write(root, result)
    result["readiness_dependency"]["status"] = readiness_payload.get("status")
    result["readiness_dependency"]["live_readiness_status"] = readiness_payload.get("live_readiness_status")

    if execute:
        result["blocking_reasons"].append("live_execute_not_implemented")
    if not bool(prepare_only):
        result["blocking_reasons"].append("prepare_only_required")
    if str(readiness_payload.get("status") or "") != "READY_FOR_PREPARE_ONLY":
        result["blocking_reasons"].append("live_readiness_not_ready_for_prepare_only")
    if not bool(source_env.get(LIVE_API_KEY_ENV) or ""):
        result["blocking_reasons"].append("missing_live_api_key")
    if not bool(source_env.get(LIVE_API_SECRET_ENV) or ""):
        result["blocking_reasons"].append("missing_live_api_secret")
    if str(source_env.get(LIVE_TRADING_ENABLED_ENV) or "").strip() != "1":
        result["blocking_reasons"].append("live_trading_enabled_flag_required")
    if str(source_env.get(LIVE_CONFIRM_SUBMIT_ENV) or "").strip() != "YES":
        result["blocking_reasons"].append("live_confirm_submit_yes_required")
    if str(source_env.get(LIVE_KILL_SWITCH_ENV) or "1").strip() != "0":
        result["blocking_reasons"].append("live_kill_switch_must_be_zero_for_future_submit")
    if result["base_url"] != DEFAULT_LIVE_BASE_URL:
        result["blocking_reasons"].append("live_base_url_must_be_api_binance_com")
    if result["allowed_symbols"] != ["BTCUSDT"]:
        result["blocking_reasons"].append("live_allowed_symbols_must_be_btcusdt_only")
    if not (0 < float(result["max_notional"] or 0.0) <= _MAX_FIRST_LIVE_NOTIONAL):
        result["blocking_reasons"].append("live_max_notional_must_be_between_0_and_5")
    if int(result["max_daily_orders"] or 0) != 1:
        result["blocking_reasons"].append("live_max_daily_orders_must_equal_1")
    if int(result["max_open_orders"] or 0) != 1:
        result["blocking_reasons"].append("live_max_open_orders_must_equal_1")

    readonly_key = str(source_env.get(MAINNET_API_KEY_ENV) or "").strip()
    live_key = str(source_env.get(LIVE_API_KEY_ENV) or "").strip()
    readonly_secret = str(source_env.get(MAINNET_API_SECRET_ENV) or "").strip()
    live_secret = str(source_env.get(LIVE_API_SECRET_ENV) or "").strip()
    if readonly_key and live_key and readonly_key == live_key:
        result["blocking_reasons"].append("live_api_key_must_not_reuse_mainnet_readonly_key")
    if readonly_secret and live_secret and readonly_secret == live_secret:
        result["blocking_reasons"].append("live_api_secret_must_not_reuse_mainnet_readonly_secret")

    result["blocking_reasons"] = _dedupe(result["blocking_reasons"])
    if not result["blocking_reasons"]:
        result["ok"] = True
        result["status"] = "PREPARED"
    return _write(root, result)


def _write(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    atomic_write_json(root / _PLAN_FILENAME, payload)
    return payload


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_symbols(raw: str | None) -> list[str]:
    if raw is None:
        return []
    return [item.strip().upper() for item in str(raw).split(",") if item.strip()]


def _safe_int(raw: str | None, default: int) -> int:
    try:
        return int(str(raw).strip()) if raw is not None and str(raw).strip() else default
    except (TypeError, ValueError):
        return default


def _safe_float(raw: str | None, default: float) -> float:
    try:
        return float(str(raw).strip()) if raw is not None and str(raw).strip() else default
    except (TypeError, ValueError):
        return default


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