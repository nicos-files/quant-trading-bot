from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.brokers.binance_spot_mainnet_readonly import (
    DEFAULT_MAINNET_BASE_URL,
    BinanceMainnetReadonlyConfigError,
    BinanceMainnetReadonlyRequestError,
    BinanceSpotMainnetReadonlyClient,
    is_mainnet_base_url,
    mask_api_key,
    resolve_credentials,
)
from src.utils.atomic_io import atomic_write_json

ENABLE_READONLY_ENV = "ENABLE_BINANCE_MAINNET_READONLY"
MAINNET_API_KEY_ENV = "BINANCE_MAINNET_API_KEY"
MAINNET_API_SECRET_ENV = "BINANCE_MAINNET_API_SECRET"
MAINNET_BASE_URL_ENV = "BINANCE_MAINNET_BASE_URL"
LIVE_TRADING_ENABLED_ENV = "BINANCE_LIVE_TRADING_ENABLED"
LIVE_CONFIRM_SUBMIT_ENV = "BINANCE_LIVE_CONFIRM_SUBMIT"
LIVE_MAX_NOTIONAL_ENV = "BINANCE_LIVE_MAX_NOTIONAL"
LIVE_MAX_DAILY_ORDERS_ENV = "BINANCE_LIVE_MAX_DAILY_ORDERS"
LIVE_MAX_OPEN_ORDERS_ENV = "BINANCE_LIVE_MAX_OPEN_ORDERS"
LIVE_ALLOWED_SYMBOLS_ENV = "BINANCE_LIVE_ALLOWED_SYMBOLS"
LIVE_KILL_SWITCH_ENV = "BINANCE_LIVE_KILL_SWITCH"

DEFAULT_LIVE_ALLOWED_SYMBOLS: tuple[str, ...] = ("BTCUSDT",)
DEFAULT_LIVE_MAX_NOTIONAL = 25.0
DEFAULT_LIVE_MAX_DAILY_ORDERS = 1
DEFAULT_LIVE_MAX_OPEN_ORDERS = 1
DEFAULT_LIVE_KILL_SWITCH = True
ARTIFACTS_SUBDIR = "crypto_mainnet"
_RESULT_FILENAME = "binance_mainnet_readonly_preflight.json"
_TARGET_SYMBOL = "BTCUSDT"


def run_binance_mainnet_readonly_preflight(
    *,
    artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR,
    env: Mapping[str, str] | None = None,
    client: BinanceSpotMainnetReadonlyClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    run_id = f"mainnet-readonly-{moment.strftime('%Y%m%d-%H%M%S')}"
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    source_env: Mapping[str, str] = env if env is not None else os.environ

    base_url = str(source_env.get(MAINNET_BASE_URL_ENV) or DEFAULT_MAINNET_BASE_URL).strip().rstrip("/")
    allowed_symbols = _parse_symbols(source_env.get(LIVE_ALLOWED_SYMBOLS_ENV)) or list(DEFAULT_LIVE_ALLOWED_SYMBOLS)
    live_kill_switch_active = _flag_enabled(source_env.get(LIVE_KILL_SWITCH_ENV), default=DEFAULT_LIVE_KILL_SWITCH)
    requested_live_trading = _flag_enabled(source_env.get(LIVE_TRADING_ENABLED_ENV), default=False)
    result: dict[str, Any] = {
        "run_id": run_id,
        "ok": False,
        "status": "BLOCKED",
        "mode": "MAINNET_READONLY_PREFLIGHT",
        "environment": "binance_spot_mainnet_readonly",
        "mainnet": True,
        "testnet": False,
        "paper_only": False,
        "live_trading_enabled": False,
        "live_readiness_status": "NOT_READY",
        "live_submit_allowed": False,
        "submit_attempted": False,
        "base_url": base_url,
        "allowed_symbols": list(allowed_symbols),
        "max_notional": _safe_float(source_env.get(LIVE_MAX_NOTIONAL_ENV), DEFAULT_LIVE_MAX_NOTIONAL),
        "max_daily_orders": _safe_int(source_env.get(LIVE_MAX_DAILY_ORDERS_ENV), DEFAULT_LIVE_MAX_DAILY_ORDERS),
        "max_open_orders": _safe_int(source_env.get(LIVE_MAX_OPEN_ORDERS_ENV), DEFAULT_LIVE_MAX_OPEN_ORDERS),
        "live_kill_switch_active": live_kill_switch_active,
        "requested_live_trading_enabled": requested_live_trading,
        "server_time_available": False,
        "exchange_filters_available": False,
        "account_checked": False,
        "balances_checked": False,
        "open_orders_checked": False,
        "reconciliation_summary": _empty_reconciliation_summary(),
        "blocking_reasons": [],
        "warnings": [],
        "api_key_masked": None,
        "heartbeat": _build_heartbeat(run_id=run_id, moment=moment, phase="initializing", status="PENDING"),
        "artifacts": {_RESULT_FILENAME: str(root / _RESULT_FILENAME)},
    }
    if live_kill_switch_active:
        result["warnings"].append("live_kill_switch_active_default_on")

    def _finish(status: str, *, ok: bool, phase: str, reason: str | None = None) -> dict[str, Any]:
        result["ok"] = ok
        result["status"] = status
        if reason:
            result["reason"] = reason
            if reason not in result["blocking_reasons"]:
                result["blocking_reasons"].append(reason)
        result["heartbeat"] = _build_heartbeat(run_id=run_id, moment=moment, phase=phase, status=status)
        atomic_write_json(root / _RESULT_FILENAME, result)
        return result

    if str(source_env.get(ENABLE_READONLY_ENV) or "").strip() != "1":
        return _finish("BLOCKED", ok=False, phase="enable_gate", reason=f"{ENABLE_READONLY_ENV} is not '1'. Mainnet readonly preflight disabled.")
    if base_url != DEFAULT_MAINNET_BASE_URL or not is_mainnet_base_url(base_url):
        return _finish("BLOCKED", ok=False, phase="base_url_gate", reason=f"Refusing non-mainnet readonly base URL: {base_url!r}")
    if requested_live_trading:
        return _finish("BLOCKED", ok=False, phase="live_gate", reason="live_trading_must_remain_disabled_for_readonly_preflight")

    api_key: str | None = None
    if client is None:
        try:
            api_key, api_secret = resolve_credentials(env=source_env)
        except BinanceMainnetReadonlyConfigError as exc:
            return _finish("BLOCKED", ok=False, phase="credentials_gate", reason=str(exc))
        client = BinanceSpotMainnetReadonlyClient(
            api_key=api_key,
            api_secret=api_secret,
            base_url=base_url,
        )
    if client is not None and api_key is None:
        api_key = getattr(client, "api_key_masked", None) or ""
    result["api_key_masked"] = mask_api_key(api_key) if api_key else None

    try:
        server_time = client.server_time()
        result["server_time_available"] = isinstance(server_time, dict) and server_time.get("serverTime") is not None
        result["server_time"] = server_time if isinstance(server_time, dict) else {}
    except BinanceMainnetReadonlyRequestError as exc:
        return _finish("ERROR", ok=False, phase="server_time", reason=str(exc))

    try:
        exchange_info = client.exchange_info(symbols=[_TARGET_SYMBOL])
        symbol_filters = _extract_symbol_filters(exchange_info, _TARGET_SYMBOL)
        result["exchange_filters_available"] = bool(symbol_filters)
        result["exchange_filters"] = {_TARGET_SYMBOL: symbol_filters} if symbol_filters else {}
        if not symbol_filters:
            return _finish("ERROR", ok=False, phase="exchange_info", reason=f"exchange_filters_missing:{_TARGET_SYMBOL}")
    except BinanceMainnetReadonlyRequestError as exc:
        return _finish("ERROR", ok=False, phase="exchange_info", reason=str(exc))

    try:
        account = client.account()
        balances = list(account.get("balances") or []) if isinstance(account, dict) else []
        result["account_checked"] = True
        result["balances_checked"] = isinstance(balances, list)
        result["account_snapshot"] = {
            "canTrade": bool(account.get("canTrade")) if isinstance(account, dict) else None,
            "makerCommission": account.get("makerCommission") if isinstance(account, dict) else None,
            "takerCommission": account.get("takerCommission") if isinstance(account, dict) else None,
        }
        result["balances"] = _summarize_balances(balances)
    except BinanceMainnetReadonlyRequestError as exc:
        return _finish("ERROR", ok=False, phase="account", reason=str(exc))

    try:
        open_orders = client.open_orders()
        result["open_orders_checked"] = True
        result["open_orders"] = [
            {
                "symbol": str(item.get("symbol") or ""),
                "side": item.get("side"),
                "status": item.get("status"),
                "type": item.get("type"),
                "origQty": item.get("origQty"),
                "executedQty": item.get("executedQty"),
            }
            for item in open_orders
        ]
    except BinanceMainnetReadonlyRequestError as exc:
        return _finish("ERROR", ok=False, phase="open_orders", reason=str(exc))

    mismatch_details = _build_reconciliation_mismatches(
        open_orders=result["open_orders"],
        allowed_symbols=allowed_symbols,
        max_open_orders=int(result["max_open_orders"]),
    )
    reconciliation_summary = _summarize_mismatches(mismatch_details)
    result["reconciliation_summary"] = reconciliation_summary
    result["reconciliation_mismatch_details"] = mismatch_details
    result["reconciliation_mismatches"] = [str(item.get("message") or "") for item in mismatch_details]

    if int(reconciliation_summary.get("count") or 0) > 0:
        return _finish(
            "ERROR",
            ok=False,
            phase="reconciliation",
            reason=f"readonly_reconciliation_mismatch:{reconciliation_summary.get('count')}:{reconciliation_summary.get('highest_severity')}",
        )

    result["blocking_reasons"] = []
    return _finish("SUCCESS", ok=True, phase="completed")


def _parse_symbols(raw: str | None) -> list[str]:
    if raw is None:
        return []
    return [item.strip().upper() for item in str(raw).split(",") if item.strip()]


def _flag_enabled(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return str(raw).strip() == "1"


def _safe_int(raw: str | None, default: int) -> int:
    try:
        value = int(str(raw).strip()) if raw is not None and str(raw).strip() else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _safe_float(raw: str | None, default: float) -> float:
    try:
        value = float(str(raw).strip()) if raw is not None and str(raw).strip() else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _build_heartbeat(*, run_id: str, moment: datetime, phase: str, status: str) -> dict[str, Any]:
    stamp = moment.isoformat()
    return {
        "run_id": run_id,
        "run_started_at": stamp,
        "run_completed_at": stamp if status in {"SUCCESS", "ERROR", "BLOCKED"} else None,
        "last_updated_at": stamp,
        "phase": phase,
        "status": status,
    }


def _extract_symbol_filters(exchange_info: Mapping[str, Any], symbol: str) -> dict[str, Any]:
    for item in list(exchange_info.get("symbols") or []):
        if str(item.get("symbol") or "").upper() != symbol.upper():
            continue
        filters: dict[str, Any] = {}
        for filt in list(item.get("filters") or []):
            filter_type = str(filt.get("filterType") or "").upper()
            if filter_type:
                filters[filter_type] = dict(filt)
        return filters
    return {}


def _summarize_balances(balances: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    summary: dict[str, dict[str, str]] = {}
    for item in balances:
        asset = str(item.get("asset") or "").upper()
        if not asset:
            continue
        summary[asset] = {
            "free": str(item.get("free") or "0"),
            "locked": str(item.get("locked") or "0"),
        }
    return summary


def _build_reconciliation_mismatches(
    *,
    open_orders: list[dict[str, Any]],
    allowed_symbols: list[str],
    max_open_orders: int,
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    if len(open_orders) > max_open_orders:
        details.append(
            {
                "message": f"open_order_count_exceeds_limit:{len(open_orders)}>{max_open_orders}",
                "severity": "ERROR",
                "level": "error",
                "code": "open_order_count_exceeds_limit",
            }
        )
    allowed = {item.upper() for item in allowed_symbols}
    for order in open_orders:
        symbol = str(order.get("symbol") or "").upper()
        if symbol and symbol not in allowed:
            details.append(
                {
                    "message": f"open_order_symbol_not_allowed:{symbol}",
                    "severity": "ERROR",
                    "level": "error",
                    "code": "open_order_symbol_not_allowed",
                }
            )
    return details


def _empty_reconciliation_summary() -> dict[str, Any]:
    return {
        "count": 0,
        "blocking_count": 0,
        "highest_severity": "INFO",
        "counts_by_severity": {"INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0},
        "counts_by_level": {"tolerable_drift": 0, "warning": 0, "error": 0, "critical_hard_stop": 0},
    }


def _summarize_mismatches(details: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _empty_reconciliation_summary()
    if not details:
        return summary
    severity_rank = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}
    highest = "INFO"
    for item in details:
        severity = str(item.get("severity") or "INFO").upper()
        level = str(item.get("level") or "warning")
        summary["count"] += 1
        summary["counts_by_severity"][severity] = summary["counts_by_severity"].get(severity, 0) + 1
        summary["counts_by_level"][level] = summary["counts_by_level"].get(level, 0) + 1
        if severity in {"ERROR", "CRITICAL"}:
            summary["blocking_count"] += 1
        if severity_rank.get(severity, 0) > severity_rank.get(highest, 0):
            highest = severity
    summary["highest_severity"] = highest
    return summary