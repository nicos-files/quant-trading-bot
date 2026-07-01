from __future__ import annotations

import json
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Mapping

from src.execution.binance_live_readiness import evaluate_binance_live_readiness
from src.execution.binance_live_soak_status import evaluate_binance_live_soak_status
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR, DEFAULT_MAINNET_BASE_URL
from src.utils.atomic_io import atomic_write_json

LIVE_TRADING_ENABLED_ENV = "BINANCE_LIVE_TRADING_ENABLED"
LIVE_CONFIRM_SUBMIT_ENV = "BINANCE_LIVE_CONFIRM_SUBMIT"
LIVE_KILL_SWITCH_ENV = "BINANCE_LIVE_KILL_SWITCH"
LIVE_BASE_URL_ENV = "BINANCE_LIVE_BASE_URL"
LIVE_ALLOWED_SYMBOLS_ENV = "BINANCE_LIVE_ALLOWED_SYMBOLS"
LIVE_MAX_NOTIONAL_ENV = "BINANCE_LIVE_MAX_NOTIONAL"
LIVE_MAX_DAILY_ORDERS_ENV = "BINANCE_LIVE_MAX_DAILY_ORDERS"
LIVE_MAX_OPEN_ORDERS_ENV = "BINANCE_LIVE_MAX_OPEN_ORDERS"
LIVE_QUOTE_BALANCE_BUFFER_PCT_ENV = "BINANCE_LIVE_QUOTE_BALANCE_BUFFER_PCT"
LIVE_MODE_ENV = "BINANCE_LIVE_MODE"
LIVE_MAX_DAILY_NOTIONAL_ENV = "BINANCE_LIVE_MAX_DAILY_NOTIONAL"
LIVE_START_TIME_UTC_ENV = "BINANCE_LIVE_START_TIME_UTC"
LIVE_END_TIME_UTC_ENV = "BINANCE_LIVE_END_TIME_UTC"
LIVE_REQUIRE_MANUAL_ARM_ENV = "BINANCE_LIVE_REQUIRE_MANUAL_ARM"
LIVE_ARM_TOKEN_ENV = "BINANCE_LIVE_ARM_TOKEN"
LIVE_SCHEDULED_WINDOW_ENABLED_ENV = "BINANCE_LIVE_SCHEDULED_WINDOW_ENABLED"
LIVE_SYMBOL = "BTCUSDT"
LIVE_QUOTE_ASSET = "USDT"

MODE_OFF = "OFF"
MODE_READ_ONLY = "READ_ONLY"
MODE_ARMED_MANUAL = "ARMED_MANUAL"
MODE_SINGLE_SHOT = "SINGLE_SHOT"
MODE_SCHEDULED_WINDOW = "SCHEDULED_WINDOW"
MODE_HALTED = "HALTED"
_ALLOWED_MODES = {
    MODE_OFF,
    MODE_READ_ONLY,
    MODE_ARMED_MANUAL,
    MODE_SINGLE_SHOT,
    MODE_SCHEDULED_WINDOW,
    MODE_HALTED,
}

_RESULT_FILENAME = "binance_live_micro_submit_result.json"
_STATUS_FILENAME = "binance_live_operations_status.json"
_HALT_FILENAME = "binance_live_halt_state.json"
_DEFAULT_MAX_DAILY_NOTIONAL = 5.0
_DEFAULT_QUOTE_BUFFER_PCT = 0.01


def evaluate_binance_live_operations(
    *,
    artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    import os

    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    source_env: Mapping[str, str] = env if env is not None else os.environ

    readonly_path = root / "binance_mainnet_readonly_preflight.json"
    readiness = evaluate_binance_live_readiness(artifacts_dir=root, now=moment)
    readonly_payload = _load_json(readonly_path)
    live_result = _load_json(root / _RESULT_FILENAME)
    halt_state = _load_json(root / _HALT_FILENAME)
    soak_status = evaluate_binance_live_soak_status(artifacts_dir=root, now=moment)

    live_mode = _normalize_mode(source_env.get(LIVE_MODE_ENV))
    max_notional = _safe_float(source_env.get(LIVE_MAX_NOTIONAL_ENV), 0.0)
    max_daily_notional = _safe_float(source_env.get(LIVE_MAX_DAILY_NOTIONAL_ENV), _DEFAULT_MAX_DAILY_NOTIONAL)
    max_daily_orders = _safe_int(source_env.get(LIVE_MAX_DAILY_ORDERS_ENV), 0)
    max_open_orders = _safe_int(source_env.get(LIVE_MAX_OPEN_ORDERS_ENV), 0)
    allowed_symbols = _parse_symbols(source_env.get(LIVE_ALLOWED_SYMBOLS_ENV))
    kill_switch_active = str(source_env.get(LIVE_KILL_SWITCH_ENV) or "1").strip() != "0"
    live_trading_enabled = str(source_env.get(LIVE_TRADING_ENABLED_ENV) or "").strip() == "1"
    require_manual_arm = str(source_env.get(LIVE_REQUIRE_MANUAL_ARM_ENV) or "1").strip() != "0"
    arm_token = str(source_env.get(LIVE_ARM_TOKEN_ENV) or "").strip()
    scheduled_window_enabled = str(source_env.get(LIVE_SCHEDULED_WINDOW_ENABLED_ENV) or "").strip() == "1"
    quote_free_balance = _extract_quote_free_balance_from_readonly(readonly_payload, LIVE_QUOTE_ASSET)
    quote_buffer_pct = _safe_float(source_env.get(LIVE_QUOTE_BALANCE_BUFFER_PCT_ENV), _DEFAULT_QUOTE_BUFFER_PCT)
    daily_usage = _derive_daily_usage(live_result=live_result, moment=moment)

    remaining_daily_notional: float | None = None
    if daily_usage["daily_notional_used"] is not None:
        remaining_daily_notional = max(0.0, max_daily_notional - float(daily_usage["daily_notional_used"]))
    effective_order_budget = _compute_effective_budget(
        max_notional=max_notional,
        remaining_daily_notional=remaining_daily_notional,
        quote_free_balance=quote_free_balance,
        quote_buffer_pct=quote_buffer_pct,
    )

    blocking_reasons: list[str] = []
    warnings: list[str] = []
    if str(readiness.get("status") or "") != "READY_FOR_PREPARE_ONLY":
        blocking_reasons.extend([str(item) for item in list(readiness.get("blocking_reasons") or []) if str(item).strip()])
        if not blocking_reasons:
            blocking_reasons.append("live_readiness_not_ready")
    if live_mode == MODE_OFF:
        blocking_reasons.append("live_mode_off")
    if live_mode == MODE_HALTED:
        blocking_reasons.append("live_mode_halted")
    if isinstance(halt_state, Mapping) and bool(halt_state.get("enabled")):
        blocking_reasons.append("live_halt_state_active")
    if allowed_symbols != [LIVE_SYMBOL]:
        blocking_reasons.append("live_allowed_symbols_must_be_btcusdt_only")
    if max_notional <= 0 or max_notional > 5.0:
        blocking_reasons.append("live_max_notional_must_be_between_0_and_5")
    if max_daily_notional <= 0:
        blocking_reasons.append("live_max_daily_notional_invalid")
    if max_daily_orders != 1:
        blocking_reasons.append("live_max_daily_orders_must_equal_1")
    if max_open_orders != 1:
        blocking_reasons.append("live_max_open_orders_must_equal_1")
    if isinstance(readonly_payload, Mapping) and str(readonly_payload.get("base_url") or DEFAULT_MAINNET_BASE_URL).strip().rstrip("/") != DEFAULT_MAINNET_BASE_URL:
        blocking_reasons.append("mainnet_base_url_invalid")
    if daily_usage["ambiguous"]:
        blocking_reasons.append("live_daily_usage_ambiguous")
    if daily_usage["daily_order_count"] >= max_daily_orders:
        blocking_reasons.append("live_max_daily_orders_reached")
    if remaining_daily_notional is not None and remaining_daily_notional <= 0:
        blocking_reasons.append("live_max_daily_notional_reached")
    if daily_usage["previous_error_requires_review"]:
        blocking_reasons.append("previous_live_error_requires_manual_review")
    if quote_free_balance is None:
        warnings.append("live_quote_balance_unavailable")
    elif effective_order_budget is None:
        warnings.append("live_effective_order_budget_unavailable")
    elif effective_order_budget <= 0:
        blocking_reasons.append("live_insufficient_quote_balance_precheck")
    else:
        required_for_first_order = min(float(max_notional), float(remaining_daily_notional or 0.0))
        if effective_order_budget < required_for_first_order:
            blocking_reasons.append("live_insufficient_quote_balance_precheck")

    window_ok = True
    if live_mode == MODE_SCHEDULED_WINDOW:
        window_ok = _is_inside_window(
            moment=moment,
            start_raw=source_env.get(LIVE_START_TIME_UTC_ENV),
            end_raw=source_env.get(LIVE_END_TIME_UTC_ENV),
        )
        if not window_ok:
            warnings.append("scheduled_window_closed")
        if not scheduled_window_enabled:
            blocking_reasons.append("live_scheduled_window_not_enabled")
        if str(soak_status.get("soak_status") or "") != "PASSED":
            blocking_reasons.append("live_scheduled_window_requires_soak_passed")

    if require_manual_arm and live_mode in {MODE_SINGLE_SHOT, MODE_SCHEDULED_WINDOW} and not arm_token:
        blocking_reasons.append("live_manual_arm_token_required")
    if live_mode == MODE_SINGLE_SHOT and not live_trading_enabled:
        blocking_reasons.append("live_trading_enabled_flag_required")
    if live_mode in {MODE_SINGLE_SHOT, MODE_SCHEDULED_WINDOW} and str(source_env.get(LIVE_CONFIRM_SUBMIT_ENV) or "").strip() != "YES":
        blocking_reasons.append("live_confirm_submit_yes_required")
    if live_mode in {MODE_SINGLE_SHOT, MODE_SCHEDULED_WINDOW} and kill_switch_active:
        blocking_reasons.append("live_kill_switch_must_be_zero_for_submit")
    if live_mode in {MODE_SINGLE_SHOT, MODE_SCHEDULED_WINDOW} and str(source_env.get(LIVE_BASE_URL_ENV) or DEFAULT_MAINNET_BASE_URL).strip().rstrip("/") != DEFAULT_MAINNET_BASE_URL:
        blocking_reasons.append("live_base_url_must_be_api_binance_com")

    blocking_reasons = _dedupe(blocking_reasons)
    warnings = _dedupe(
        warnings
        + [str(item) for item in list(readiness.get("warnings") or []) if str(item).strip()]
        + [str(item) for item in list(soak_status.get("blockers") or []) if str(item).strip()]
    )

    ignored_prepare_blockers = {
        "live_mode_off",
        "live_mode_halted",
        "live_max_daily_orders_reached",
        "live_max_daily_notional_reached",
        "live_insufficient_quote_balance_precheck",
        "live_effective_order_budget_unavailable",
        "live_quote_balance_unavailable",
        "live_manual_arm_token_required",
        "live_trading_enabled_flag_required",
        "live_confirm_submit_yes_required",
        "live_kill_switch_must_be_zero_for_submit",
        "live_scheduled_window_not_enabled",
        "live_scheduled_window_requires_soak_passed",
    }
    can_prepare = live_mode in {MODE_ARMED_MANUAL, MODE_SINGLE_SHOT, MODE_SCHEDULED_WINDOW} and not _has_hard_blocker(blocking_reasons, ignore=ignored_prepare_blockers)
    can_single_shot = live_mode == MODE_SINGLE_SHOT and not blocking_reasons
    can_scheduled_trade = live_mode == MODE_SCHEDULED_WINDOW and window_ok and not blocking_reasons

    if live_mode == MODE_OFF:
        status = MODE_OFF
        ok = False
        next_allowed_mode = MODE_READ_ONLY
    elif live_mode == MODE_HALTED or (isinstance(halt_state, Mapping) and bool(halt_state.get("enabled"))):
        status = MODE_HALTED
        ok = False
        next_allowed_mode = MODE_OFF
    elif live_mode == MODE_READ_ONLY:
        status = MODE_READ_ONLY
        ok = not _has_hard_blocker(blocking_reasons, ignore={"live_quote_balance_unavailable", "live_effective_order_budget_unavailable", "live_insufficient_quote_balance_precheck"})
        next_allowed_mode = MODE_ARMED_MANUAL if ok else MODE_READ_ONLY
    elif live_mode == MODE_ARMED_MANUAL:
        status = MODE_ARMED_MANUAL if can_prepare else "ARMED_MANUAL_BLOCKED"
        ok = can_prepare
        next_allowed_mode = MODE_SINGLE_SHOT if can_prepare else MODE_ARMED_MANUAL
    elif live_mode == MODE_SINGLE_SHOT:
        status = "READY_FOR_SINGLE_SHOT" if can_single_shot else "SINGLE_SHOT_BLOCKED"
        ok = can_single_shot
        next_allowed_mode = MODE_OFF if can_single_shot else MODE_SINGLE_SHOT
    else:
        status = "READY_IN_WINDOW" if can_scheduled_trade else "SCHEDULED_WINDOW_BLOCKED"
        ok = can_scheduled_trade
        next_allowed_mode = MODE_SCHEDULED_WINDOW

    result = {
        "ok": ok,
        "status": status,
        "live_mode": live_mode,
        "live_trading_enabled": live_trading_enabled,
        "kill_switch_active": kill_switch_active,
        "allowed_symbols": list(allowed_symbols),
        "max_notional": max_notional,
        "max_daily_notional": max_daily_notional,
        "max_daily_orders": max_daily_orders,
        "max_open_orders": max_open_orders,
        "daily_order_count": daily_usage["daily_order_count"],
        "daily_notional_used": daily_usage["daily_notional_used"],
        "remaining_daily_notional": remaining_daily_notional,
        "quote_asset": LIVE_QUOTE_ASSET,
        "quote_free_balance": quote_free_balance,
        "effective_order_budget": effective_order_budget,
        "can_prepare": can_prepare,
        "can_single_shot": can_single_shot,
        "can_scheduled_trade": can_scheduled_trade,
        "scheduled_window_enabled": scheduled_window_enabled,
        "soak_status": str(soak_status.get("soak_status") or "INCOMPLETE"),
        "soak_days_required": soak_status.get("days_required"),
        "soak_days_passed": soak_status.get("days_passed"),
        "next_allowed_mode": next_allowed_mode,
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "generated_at_utc": moment.isoformat(),
        "artifact_inputs": {
            "mainnet_readonly_preflight": str(readonly_path),
            "live_readiness": str(root / "binance_live_readiness.json"),
            "live_result": str(root / _RESULT_FILENAME),
            "live_halt_state": str(root / _HALT_FILENAME),
            "live_soak_status": str(root / "binance_live_soak_status.json"),
        },
        "artifacts": {
            _STATUS_FILENAME: str(root / _STATUS_FILENAME),
        },
    }
    atomic_write_json(root / _STATUS_FILENAME, result)
    return result


def halt_binance_live_operations(
    *,
    artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR,
    reason: str = "manual_halt",
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": True,
        "status": MODE_HALTED,
        "enabled": True,
        "live_mode": MODE_HALTED,
        "reason": str(reason or "manual_halt"),
        "generated_at_utc": moment.isoformat(),
        "artifacts": {
            _HALT_FILENAME: str(root / _HALT_FILENAME),
        },
    }
    atomic_write_json(root / _HALT_FILENAME, payload)
    return payload


def _normalize_mode(raw: str | None) -> str:
    candidate = str(raw or MODE_OFF).strip().upper() or MODE_OFF
    return candidate if candidate in _ALLOWED_MODES else MODE_OFF


def _derive_daily_usage(*, live_result: Any, moment: datetime) -> dict[str, Any]:
    result = {
        "daily_order_count": 0,
        "daily_notional_used": 0.0,
        "ambiguous": False,
        "previous_error_requires_review": False,
    }
    if not isinstance(live_result, Mapping):
        return result
    stamp = _parse_datetime(((live_result.get("heartbeat") or {}).get("last_updated_at"))) or _parse_datetime(live_result.get("generated_at_utc"))
    if stamp is None:
        result["ambiguous"] = True
        return result
    if stamp.date() != moment.date():
        return result
    status = str(live_result.get("status") or "").upper()
    if status == "ERROR" and not bool(live_result.get("manual_review_acknowledged")):
        result["previous_error_requires_review"] = True
    if bool(live_result.get("daily_cap_consumed")):
        requested = _safe_float(live_result.get("requested_notional"), None)
        if requested is None:
            result["ambiguous"] = True
            return result
        result["daily_order_count"] = 1
        result["daily_notional_used"] = requested
        return result
    daily_order_cap = live_result.get("daily_order_cap") if isinstance(live_result, Mapping) else None
    if isinstance(daily_order_cap, Mapping) and bool(daily_order_cap.get("history_consumed_cap")):
        requested = _safe_float(daily_order_cap.get("history_requested_notional"), None)
        if requested is None:
            requested = _safe_float(live_result.get("requested_notional"), None)
        if requested is None:
            result["ambiguous"] = True
            return result
        result["daily_order_count"] = 1
        result["daily_notional_used"] = requested
        return result
    if bool(live_result.get("submit_attempted")) and not bool(live_result.get("exchange_order_request_sent")) and _safe_int(live_result.get("placed_count"), 0) == 0:
        return result
    return result


def _extract_quote_free_balance_from_readonly(payload: Any, quote_asset: str) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    balances = payload.get("balances") if isinstance(payload.get("balances"), Mapping) else None
    if not isinstance(balances, Mapping):
        return None
    quote_payload = balances.get(str(quote_asset or "").upper())
    if not isinstance(quote_payload, Mapping):
        return None
    return _safe_float(quote_payload.get("free"), None)


def _compute_effective_budget(*, max_notional: float, remaining_daily_notional: float | None, quote_free_balance: float | None, quote_buffer_pct: float) -> float | None:
    if max_notional <= 0 or remaining_daily_notional is None or quote_free_balance is None:
        return None
    balance_after_buffer = max(0.0, float(quote_free_balance) - max(0.0, float(quote_free_balance) * max(0.0, quote_buffer_pct)))
    return min(float(max_notional), float(remaining_daily_notional), balance_after_buffer)


def _is_inside_window(*, moment: datetime, start_raw: str | None, end_raw: str | None) -> bool:
    start = _parse_hhmm(start_raw)
    end = _parse_hhmm(end_raw)
    if start is None or end is None:
        return False
    current = moment.astimezone(timezone.utc).time().replace(tzinfo=None)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _parse_hhmm(raw: str | None) -> time | None:
    text = str(raw or "").strip()
    if not text or ":" not in text:
        return None
    try:
        hours_text, minutes_text = text.split(":", 1)
        return time(hour=int(hours_text), minute=int(minutes_text))
    except Exception:
        return None


def _parse_symbols(raw: str | None) -> list[str]:
    if raw is None:
        return []
    return [item.strip().upper() for item in str(raw).split(",") if item.strip()]


def _safe_int(raw: Any, default: int | None) -> int | None:
    try:
        return int(str(raw).strip()) if raw is not None and str(raw).strip() else default
    except (TypeError, ValueError):
        return default


def _safe_float(raw: Any, default: float | None) -> float | None:
    try:
        return float(str(raw).strip()) if raw is not None and str(raw).strip() else default
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _has_hard_blocker(blocking_reasons: list[str], ignore: set[str] | None = None) -> bool:
    ignored = ignore or set()
    return any(reason not in ignored for reason in blocking_reasons)


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


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


__all__ = [
    "LIVE_ARM_TOKEN_ENV",
    "LIVE_MAX_DAILY_NOTIONAL_ENV",
    "LIVE_MODE_ENV",
    "LIVE_REQUIRE_MANUAL_ARM_ENV",
    "LIVE_SCHEDULED_WINDOW_ENABLED_ENV",
    "LIVE_START_TIME_UTC_ENV",
    "LIVE_END_TIME_UTC_ENV",
    "MODE_ARMED_MANUAL",
    "MODE_HALTED",
    "MODE_OFF",
    "MODE_READ_ONLY",
    "MODE_SCHEDULED_WINDOW",
    "MODE_SINGLE_SHOT",
    "evaluate_binance_live_operations",
    "halt_binance_live_operations",
]
