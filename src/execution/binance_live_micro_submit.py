from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.brokers.binance_spot_mainnet import (
    BinanceMainnetConfigError,
    BinanceSpotMainnetClient,
    DEFAULT_MAINNET_BASE_URL,
    LIVE_API_KEY_ENV,
    LIVE_API_SECRET_ENV,
    is_mainnet_base_url,
    mask_api_key,
    resolve_credentials,
)
from src.execution.binance_live_readiness import evaluate_binance_live_readiness
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR
from src.execution.binance_testnet_executor import (
    _load_exchange_filters,
    _perform_time_sync,
    _reconcile_exchange_state,
    _summarize_exchange_mismatch_details,
)
from src.execution.binance_testnet_smoke_submit import (
    _build_smoke_delta_payload,
    _dedupe_warnings,
    _resolve_smoke_notional,
)
from src.utils.atomic_io import atomic_write_json

LIVE_TRADING_ENABLED_ENV = "BINANCE_LIVE_TRADING_ENABLED"
LIVE_CONFIRM_SUBMIT_ENV = "BINANCE_LIVE_CONFIRM_SUBMIT"
LIVE_KILL_SWITCH_ENV = "BINANCE_LIVE_KILL_SWITCH"
LIVE_KILL_SWITCH_PATH_ENV = "BINANCE_LIVE_KILL_SWITCH_PATH"
LIVE_BASE_URL_ENV = "BINANCE_LIVE_BASE_URL"
LIVE_ALLOWED_SYMBOLS_ENV = "BINANCE_LIVE_ALLOWED_SYMBOLS"
LIVE_MAX_NOTIONAL_ENV = "BINANCE_LIVE_MAX_NOTIONAL"
LIVE_MAX_DAILY_ORDERS_ENV = "BINANCE_LIVE_MAX_DAILY_ORDERS"
LIVE_MAX_OPEN_ORDERS_ENV = "BINANCE_LIVE_MAX_OPEN_ORDERS"
MAINNET_API_KEY_ENV = "BINANCE_MAINNET_API_KEY"
MAINNET_API_SECRET_ENV = "BINANCE_MAINNET_API_SECRET"

LIVE_SYMBOL = "BTCUSDT"
LIVE_QUOTE_ASSET = "USDT"
LIVE_ORDER_TYPE = "MARKET"
_MAX_FIRST_LIVE_NOTIONAL = 5.0
_PLAN_FILENAME = "binance_live_micro_submit_plan.json"
_RESULT_FILENAME = "binance_live_micro_submit_result.json"


@dataclass(frozen=True)
class _LiveReconConfig:
    allowed_symbols: tuple[str, ...] = (LIVE_SYMBOL,)
    quote_currency: str = LIVE_QUOTE_ASSET
    recv_window_ms: int = 5000


@dataclass(frozen=True)
class _LiveFill:
    quantity: float
    price: float | None
    commission: float
    commission_asset: str | None


def run_binance_live_micro_submit_prepare_only(
    *,
    artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
    prepare_only: bool = True,
    execute: bool = False,
) -> dict[str, Any]:
    return run_binance_live_micro_submit(
        artifacts_dir=artifacts_dir,
        env=env,
        now=now,
        prepare_only=prepare_only,
        execute=execute,
    )


def run_binance_live_micro_submit(
    *,
    artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR,
    env: Mapping[str, str] | None = None,
    client: BinanceSpotMainnetClient | Any | None = None,
    now: datetime | None = None,
    prepare_only: bool = False,
    execute: bool = False,
) -> dict[str, Any]:
    if prepare_only and execute:
        return _run_prepare_only(
            artifacts_dir=artifacts_dir,
            env=env,
            now=now,
            prepare_only=True,
            execute=True,
            forced_reason="prepare_only_and_execute_mutually_exclusive",
        )
    if not execute:
        return _run_prepare_only(
            artifacts_dir=artifacts_dir,
            env=env,
            now=now,
            prepare_only=True,
            execute=False,
            forced_reason=None,
        )
    return _run_execute(
        artifacts_dir=artifacts_dir,
        env=env,
        client=client,
        now=now,
    )


def _run_prepare_only(
    *,
    artifacts_dir: str | Path,
    env: Mapping[str, str] | None,
    now: datetime | None,
    prepare_only: bool,
    execute: bool,
    forced_reason: str | None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    source_env: Mapping[str, str] = env if env is not None else os.environ
    result = _base_result(
        run_id=f"live-prepare-{moment.strftime('%Y%m%d-%H%M%S')}",
        moment=moment,
        root=root,
        artifact_filename=_PLAN_FILENAME,
        source_env=source_env,
        prepare_only=prepare_only,
        execute=execute,
    )
    result["mode"] = "BINANCE_LIVE_MICRO_SUBMIT_PREPARE_ONLY"
    result["warnings"] = ["prepare_only_no_live_order_executed"]
    readiness = evaluate_binance_live_readiness(artifacts_dir=root, now=moment)
    result["readiness_dependency"] = _summarize_readiness(root=root, readiness=readiness)

    if forced_reason is not None:
        result["blocking_reasons"].append(forced_reason)
    result["blocking_reasons"].extend(_preflight_gates(source_env=source_env, readiness=readiness, for_execute=False))
    result["blocking_reasons"] = _dedupe_warnings(list(result["blocking_reasons"]))
    if result["blocking_reasons"]:
        return _finalize(root=root, filename=_PLAN_FILENAME, payload=result, status="BLOCKED", phase="prepare_only_gate")
    return _finalize(root=root, filename=_PLAN_FILENAME, payload=result, status="PREPARED", phase="prepared")


def _run_execute(
    *,
    artifacts_dir: str | Path,
    env: Mapping[str, str] | None,
    client: BinanceSpotMainnetClient | Any | None,
    now: datetime | None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    source_env: Mapping[str, str] = env if env is not None else os.environ
    result = _base_result(
        run_id=f"live-micro-{moment.strftime('%Y%m%d-%H%M%S')}",
        moment=moment,
        root=root,
        artifact_filename=_RESULT_FILENAME,
        source_env=source_env,
        prepare_only=False,
        execute=True,
    )
    result["mode"] = "BINANCE_LIVE_MICRO_SUBMIT_EXECUTE"
    result["live_trading"] = True

    readiness = evaluate_binance_live_readiness(artifacts_dir=root, now=moment)
    result["readiness_dependency"] = _summarize_readiness(root=root, readiness=readiness)
    result["blocking_reasons"].extend(_preflight_gates(source_env=source_env, readiness=readiness, for_execute=True))

    daily_guard = _check_daily_order_cap(root=root, moment=moment, max_daily_orders=int(result["max_daily_orders"] or 0))
    result["daily_order_cap"] = daily_guard
    if daily_guard.get("warning"):
        result["warnings"] = _dedupe_warnings(list(result["warnings"]) + [str(daily_guard.get("warning"))])
    if daily_guard.get("blocked"):
        result["failure_stage"] = "daily_cap_gate"
        result["blocking_reasons"].append(str(daily_guard.get("reason") or "live_daily_order_cap_blocked"))

    result["blocking_reasons"] = _dedupe_warnings(list(result["blocking_reasons"]))
    if result["blocking_reasons"]:
        return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="BLOCKED", phase="pre_client_gates")

    api_key: str | None = None
    if client is None:
        try:
            api_key, api_secret = resolve_credentials(env=source_env)
        except BinanceMainnetConfigError as exc:
            result["blocking_reasons"] = [str(exc)]
            return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="BLOCKED", phase="credentials_gate")
        client = BinanceSpotMainnetClient(
            api_key=api_key,
            api_secret=api_secret,
            base_url=result["base_url"],
        )
    if client is not None and api_key is None:
        api_key = getattr(client, "api_key_masked", None) or ""
    result["api_key_masked"] = mask_api_key(api_key) if api_key else None

    time_sync = _perform_time_sync(client=client, recv_window_ms=5000, local_time=moment)
    result["time_sync"] = time_sync
    result["warnings"] = list(result["warnings"]) + list(time_sync.get("warnings") or [])
    if time_sync.get("blocked"):
        result["blocking_reasons"] = [str(time_sync.get("reason") or "server_time_sync_blocked")]
        return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="BLOCKED", phase="time_sync_gate")

    exchange_filters = _load_exchange_filters(client=client, allowed_symbols=[LIVE_SYMBOL], warnings=result["warnings"])
    result["exchange_filters"] = exchange_filters
    symbol_filters = exchange_filters.get(LIVE_SYMBOL)
    if not symbol_filters:
        result["blocking_reasons"] = [f"exchange_filters_missing:{LIVE_SYMBOL}"]
        return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="BLOCKED", phase="exchange_filters_gate")

    try:
        requested_notional = _resolve_live_notional(symbol_filters=symbol_filters, max_notional=float(result["max_notional"] or 0.0))
    except ValueError as exc:
        result["blocking_reasons"] = [str(exc)]
        return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="BLOCKED", phase="notional_gate")
    result["requested_notional"] = requested_notional

    warnings = list(result["warnings"])
    pre_state = _reconcile_exchange_state(
        client=client,
        config=_LiveReconConfig(),
        accepted_orders=[],
        derived_positions=[],
        moment=moment,
        warnings=warnings,
        run_id=str(result["run_id"]),
    )
    result["warnings"] = _dedupe_warnings(warnings)
    result["pre_submit_exchange_state"] = deepcopy(pre_state)
    result["pre_open_orders_count"] = int(((pre_state.get("open_orders") or {}).get("count") or 0))
    if not pre_state.get("account_checked") or not pre_state.get("open_orders_checked"):
        result["blocking_reasons"] = ["pre_submit_exchange_state_unavailable"]
        return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="BLOCKED", phase="pre_exchange_state_gate")
    if int(result["pre_open_orders_count"] or 0) != 0:
        result["blocking_reasons"] = [f"unexpected_open_orders_present:{result['pre_open_orders_count']}"]
        return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="BLOCKED", phase="pre_open_orders_gate")

    params = {
        "symbol": LIVE_SYMBOL,
        "side": "BUY",
        "type": LIVE_ORDER_TYPE,
        "quoteOrderQty": f"{requested_notional:.8f}",
        "newClientOrderId": _build_live_client_order_id(str(result["run_id"])),
        "newOrderRespType": "FULL",
    }
    result["placement_stage"] = "ready_to_submit"
    result["submit_attempted"] = True
    result["broker_order_request_attempted"] = True
    result["placement_stage"] = "broker_request_attempted"
    try:
        broker_response = client.place_order(params=params)
    except Exception as exc:
        result["exchange_order_request_sent"] = _exchange_order_request_may_have_been_sent(exc)
        result["failure_stage"] = _classify_submit_failure_stage(exc)
        result["blocking_reasons"] = [f"live_submit_failed:{_safe_error_text(exc)}"]
        return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="ERROR", phase="submit_attempt")

    result["exchange_order_request_sent"] = True
    result["placement_stage"] = "broker_response_received"
    if str((broker_response or {}).get("status") or "").upper() == "REJECTED":
        result["rejected_count"] = 1
        result["failure_stage"] = "broker_rejected"
        result["blocking_reasons"] = ["live_order_rejected"]
        return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="ERROR", phase="submit_rejected")

    fill_summary = _extract_fill(broker_response)
    result["placed_count"] = 1
    result["fill_summary"] = None if fill_summary is None else {
        "quantity": fill_summary.quantity,
        "price": fill_summary.price,
        "commission": fill_summary.commission,
        "commission_asset": fill_summary.commission_asset,
    }

    warnings = list(result["warnings"])
    post_state = _reconcile_exchange_state(
        client=client,
        config=_LiveReconConfig(),
        accepted_orders=[],
        derived_positions=[],
        moment=moment,
        warnings=warnings,
        run_id=str(result["run_id"]),
    )
    result["warnings"] = _dedupe_warnings(warnings)
    result["post_submit_exchange_state"] = deepcopy(post_state)
    result["post_open_orders_count"] = int(((post_state.get("open_orders") or {}).get("count") or 0))
    if not post_state.get("account_checked") or not post_state.get("open_orders_checked"):
        result["blocking_reasons"] = ["post_submit_exchange_state_unavailable"]
        return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="ERROR", phase="post_exchange_state_gate")

    delta_payload = _build_smoke_delta_payload(
        pre_exchange_state=pre_state,
        post_exchange_state=post_state,
        fill=fill_summary,
        broker_response=broker_response,
        symbol=LIVE_SYMBOL,
        quote_asset=LIVE_QUOTE_ASSET,
    )
    result["baseline_balances"] = delta_payload["baseline_balances"]
    result["expected_delta"] = delta_payload["expected_delta"]
    result["observed_delta"] = delta_payload["observed_delta"]
    result["delta_reconciliation_summary"] = delta_payload["delta_reconciliation_summary"]
    result["delta_reconciliation_mismatch_details"] = delta_payload["delta_reconciliation_mismatch_details"]
    result["preexisting_balance_detected"] = delta_payload["preexisting_balance_detected"]
    if delta_payload.get("baseline_warning"):
        result["warnings"] = _dedupe_warnings(list(result["warnings"]) + [str(delta_payload["baseline_warning"])])

    combined_details = list(post_state.get("mismatch_details") or []) + list(delta_payload["delta_reconciliation_mismatch_details"] or [])
    result["reconciliation_summary"] = _summarize_exchange_mismatch_details(combined_details)

    if fill_summary is None:
        result["blocking_reasons"] = ["live_submit_missing_fill"]
        return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="ERROR", phase="missing_fill")
    if int(result["post_open_orders_count"] or 0) != 0:
        result["blocking_reasons"] = [f"unexpected_open_orders_after_submit:{result['post_open_orders_count']}"]
        return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="ERROR", phase="post_open_orders_gate")
    if int(((result.get("reconciliation_summary") or {}).get("count") or 0)) != 0:
        summary = result["reconciliation_summary"]
        result["blocking_reasons"] = [f"post_submit_reconciliation_mismatch:{summary.get('count')}:{summary.get('highest_severity')}"]
        return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="ERROR", phase="post_reconciliation_gate")
    return _finalize(root=root, filename=_RESULT_FILENAME, payload=result, status="SUCCESS", phase="completed")


def _base_result(
    *,
    run_id: str,
    moment: datetime,
    root: Path,
    artifact_filename: str,
    source_env: Mapping[str, str],
    prepare_only: bool,
    execute: bool,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "ok": False,
        "status": "BLOCKED",
        "environment": "binance_spot_mainnet",
        "mainnet": True,
        "testnet": False,
        "paper_only": False,
        "mainnet_enabled": True,
        "live_trading": False,
        "live_trading_enabled": str(source_env.get(LIVE_TRADING_ENABLED_ENV) or "").strip() == "1",
        "prepare_only": bool(prepare_only),
        "execute": bool(execute),
        "submit_attempted": False,
        "broker_order_request_attempted": False,
        "exchange_order_request_sent": False,
        "placed_count": 0,
        "rejected_count": 0,
        "requested_notional": None,
        "daily_cap_consumed": False,
        "daily_cap_reason": "not_submitted",
        "placement_stage": "not_started",
        "failure_stage": None,
        "symbol": LIVE_SYMBOL,
        "order_type": LIVE_ORDER_TYPE,
        "base_url": str(source_env.get(LIVE_BASE_URL_ENV) or DEFAULT_MAINNET_BASE_URL).strip().rstrip("/"),
        "allowed_symbols": _parse_symbols(source_env.get(LIVE_ALLOWED_SYMBOLS_ENV)),
        "max_notional": _safe_float(source_env.get(LIVE_MAX_NOTIONAL_ENV), 0.0),
        "max_daily_orders": _safe_int(source_env.get(LIVE_MAX_DAILY_ORDERS_ENV), 0),
        "max_open_orders": _safe_int(source_env.get(LIVE_MAX_OPEN_ORDERS_ENV), 0),
        "confirm_submit": str(source_env.get(LIVE_CONFIRM_SUBMIT_ENV) or "").strip() == "YES",
        "kill_switch_status": "ACTIVE" if str(source_env.get(LIVE_KILL_SWITCH_ENV) or "1").strip() != "0" else "INACTIVE",
        "blocking_reasons": [],
        "warnings": [],
        "api_key_masked": None,
        "generated_at_utc": moment.isoformat(),
        "heartbeat": _heartbeat(run_id=run_id, moment=moment, phase="initializing", status="PENDING"),
        "artifacts": {artifact_filename: str(root / artifact_filename)},
    }


def _summarize_readiness(*, root: Path, readiness: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": str(root / "binance_live_readiness.json"),
        "exists": True,
        "status": readiness.get("status"),
        "live_readiness_status": readiness.get("live_readiness_status"),
        "blocking_reasons": list(readiness.get("blocking_reasons") or []),
    }


def _preflight_gates(*, source_env: Mapping[str, str], readiness: Mapping[str, Any], for_execute: bool) -> list[str]:
    reasons: list[str] = []
    if str(readiness.get("status") or "") != "READY_FOR_PREPARE_ONLY":
        reasons.append("live_readiness_not_ready")
    readiness_blockers = [str(item) for item in list(readiness.get("blocking_reasons") or []) if str(item).strip()]
    if readiness_blockers:
        reasons.append("live_readiness_has_blocking_reasons")
        reasons.extend(readiness_blockers)
    if str(source_env.get(LIVE_TRADING_ENABLED_ENV) or "").strip() != "1":
        reasons.append("live_trading_enabled_flag_required")
    if str(source_env.get(LIVE_CONFIRM_SUBMIT_ENV) or "").strip() != "YES":
        reasons.append("live_confirm_submit_yes_required")
    expected_kill_value = "0"
    actual_kill = str(source_env.get(LIVE_KILL_SWITCH_ENV) or "1").strip()
    if actual_kill != expected_kill_value:
        reasons.append("live_kill_switch_must_be_zero_for_submit" if for_execute else "live_kill_switch_must_be_zero_for_future_submit")
    kill_switch_file = _check_kill_switch_file(source_env=source_env)
    if kill_switch_file is not None:
        reasons.append(kill_switch_file)
    base_url = str(source_env.get(LIVE_BASE_URL_ENV) or DEFAULT_MAINNET_BASE_URL).strip().rstrip("/")
    if base_url != DEFAULT_MAINNET_BASE_URL or not is_mainnet_base_url(base_url):
        reasons.append("live_base_url_must_be_api_binance_com")
    if _parse_symbols(source_env.get(LIVE_ALLOWED_SYMBOLS_ENV)) != [LIVE_SYMBOL]:
        reasons.append("live_allowed_symbols_must_be_btcusdt_only")
    max_notional = _safe_float(source_env.get(LIVE_MAX_NOTIONAL_ENV), 0.0)
    if not (0 < max_notional <= _MAX_FIRST_LIVE_NOTIONAL):
        reasons.append("live_max_notional_must_be_between_0_and_5")
    if _safe_int(source_env.get(LIVE_MAX_DAILY_ORDERS_ENV), 0) != 1:
        reasons.append("live_max_daily_orders_must_equal_1")
    if _safe_int(source_env.get(LIVE_MAX_OPEN_ORDERS_ENV), 0) != 1:
        reasons.append("live_max_open_orders_must_equal_1")
    if not bool(str(source_env.get(LIVE_API_KEY_ENV) or "").strip()):
        reasons.append("missing_live_api_key")
    if not bool(str(source_env.get(LIVE_API_SECRET_ENV) or "").strip()):
        reasons.append("missing_live_api_secret")
    readonly_key = str(source_env.get(MAINNET_API_KEY_ENV) or "").strip()
    live_key = str(source_env.get(LIVE_API_KEY_ENV) or "").strip()
    readonly_secret = str(source_env.get(MAINNET_API_SECRET_ENV) or "").strip()
    live_secret = str(source_env.get(LIVE_API_SECRET_ENV) or "").strip()
    if readonly_key and live_key and readonly_key == live_key:
        reasons.append("live_api_key_must_not_reuse_mainnet_readonly_key")
    if readonly_secret and live_secret and readonly_secret == live_secret:
        reasons.append("live_api_secret_must_not_reuse_mainnet_readonly_secret")
    return reasons


def _check_kill_switch_file(*, source_env: Mapping[str, str]) -> str | None:
    raw_path = str(source_env.get(LIVE_KILL_SWITCH_PATH_ENV) or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.exists():
        return None
    payload = _load_json(path)
    if isinstance(payload, Mapping) and bool(payload.get("enabled")):
        return "live_kill_switch_file_active"
    return None


def _check_daily_order_cap(*, root: Path, moment: datetime, max_daily_orders: int) -> dict[str, Any]:
    result = {
        "checked": True,
        "blocked": False,
        "count_today": 0,
        "max_daily_orders": int(max_daily_orders),
        "history_path": str(root / _RESULT_FILENAME),
        "history_run_id": None,
        "history_status": None,
        "history_consumed_cap": False,
        "history_consumed_reason": None,
        "warning": None,
    }
    if max_daily_orders <= 0:
        result["blocked"] = True
        result["reason"] = "live_max_daily_orders_invalid"
        return result
    path = root / _RESULT_FILENAME
    if not path.exists():
        return result
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        result["blocked"] = True
        result["reason"] = "live_daily_order_history_unreadable"
        return result
    result["history_run_id"] = payload.get("run_id")
    result["history_status"] = payload.get("status")
    stamp = _parse_datetime(((payload.get("heartbeat") or {}).get("last_updated_at"))) or _parse_datetime(payload.get("generated_at_utc"))
    if stamp is None:
        result["blocked"] = True
        result["reason"] = "live_daily_order_history_ambiguous"
        return result
    if stamp.date() != moment.date():
        return result
    classification = _classify_daily_cap_history(payload)
    result["history_consumed_cap"] = bool(classification.get("consumed"))
    result["history_consumed_reason"] = classification.get("reason")
    if classification.get("warning"):
        result["warning"] = classification.get("warning")
    if classification.get("blocked"):
        result["blocked"] = True
        result["reason"] = str(classification.get("reason") or "live_daily_order_history_ambiguous")
        return result
    if not classification.get("consumed"):
        return result
    result["count_today"] = 1
    if result["count_today"] >= max_daily_orders:
        result["blocked"] = True
        result["reason"] = f"live_daily_order_cap_reached:{result['count_today']}>={max_daily_orders}"
    return result


def _classify_daily_cap_history(payload: Mapping[str, Any]) -> dict[str, Any]:
    placed_count = _safe_int(payload.get("placed_count"), 0)
    rejected_count = _safe_int(payload.get("rejected_count"), 0)
    submit_attempted = bool(payload.get("submit_attempted"))
    broker_order_request_attempted = payload.get("broker_order_request_attempted")
    exchange_order_request_sent = payload.get("exchange_order_request_sent")
    blocking_reasons = [str(item) for item in list(payload.get("blocking_reasons") or []) if str(item).strip()]
    failure_stage = str(payload.get("failure_stage") or "").strip()
    run_id = str(payload.get("run_id") or "unknown")

    if bool(payload.get("daily_cap_consumed")):
        return {"consumed": True, "blocked": False, "reason": str(payload.get("daily_cap_reason") or "daily_cap_consumed_explicit")}
    if placed_count > 0:
        return {"consumed": True, "blocked": False, "reason": f"prior_live_order_placed:{placed_count}"}
    if exchange_order_request_sent is True:
        if rejected_count > 0:
            return {"consumed": True, "blocked": False, "reason": f"prior_exchange_rejected_after_submit:{rejected_count}"}
        return {"consumed": True, "blocked": False, "reason": "prior_exchange_order_request_sent"}
    if _is_explicit_pre_exchange_history_failure(blocking_reasons=blocking_reasons, failure_stage=failure_stage):
        return {
            "consumed": False,
            "blocked": False,
            "reason": "pre_exchange_submit_failure_not_counted",
            "warning": f"daily_cap_not_consumed_pre_exchange_failure:{run_id}",
        }
    if not submit_attempted and placed_count == 0 and rejected_count == 0:
        return {"consumed": False, "blocked": False, "reason": "no_submit_attempt_recorded"}
    if exchange_order_request_sent is False and broker_order_request_attempted is True:
        return {
            "consumed": False,
            "blocked": False,
            "reason": "pre_exchange_submit_failure_not_counted",
            "warning": f"daily_cap_not_consumed_pre_exchange_failure:{run_id}",
        }
    return {
        "consumed": False,
        "blocked": True,
        "reason": "live_daily_order_history_ambiguous",
    }


def _derive_current_run_daily_cap_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    placed_count = _safe_int(payload.get("placed_count"), 0)
    rejected_count = _safe_int(payload.get("rejected_count"), 0)
    if placed_count > 0:
        return {"consumed": True, "reason": f"placed_count={placed_count}"}
    if bool(payload.get("exchange_order_request_sent")):
        if rejected_count > 0:
            return {"consumed": True, "reason": f"exchange_rejected_count={rejected_count}"}
        return {"consumed": True, "reason": "exchange_order_request_sent"}
    if bool(payload.get("broker_order_request_attempted")):
        return {"consumed": False, "reason": "pre_exchange_submit_failure_not_counted"}
    return {"consumed": False, "reason": "not_submitted"}


def _resolve_live_notional(*, symbol_filters: Mapping[str, dict[str, Any]], max_notional: float) -> float:
    try:
        return float(_resolve_smoke_notional(symbol_filters=symbol_filters, max_notional=max_notional))
    except ValueError as exc:
        message = str(exc).replace("smoke_", "live_").replace("live_min_notional_exceeds_cap", "live_min_notional_exceeds_configured_cap")
        raise ValueError(message) from None


def _extract_fill(broker_response: Mapping[str, Any] | Any) -> _LiveFill | None:
    if not isinstance(broker_response, Mapping):
        return None
    fills = broker_response.get("fills")
    if not isinstance(fills, list) or not fills:
        return None
    total_qty = 0.0
    total_commission = 0.0
    last_price: float | None = None
    commission_asset: str | None = None
    for item in fills:
        if not isinstance(item, Mapping):
            continue
        try:
            qty = float(item.get("qty") or 0.0)
            total_qty += qty
        except (TypeError, ValueError):
            pass
        try:
            price = float(item.get("price") or 0.0)
            if price > 0:
                last_price = price
        except (TypeError, ValueError):
            pass
        try:
            total_commission += float(item.get("commission") or 0.0)
        except (TypeError, ValueError):
            pass
        asset = str(item.get("commissionAsset") or "").upper() or None
        if asset and commission_asset is None:
            commission_asset = asset
    if total_qty <= 0:
        return None
    return _LiveFill(quantity=total_qty, price=last_price, commission=total_commission, commission_asset=commission_asset)


def _build_live_client_order_id(run_id: str) -> str:
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:24]
    return f"livemk-{digest}"


def _heartbeat(*, run_id: str, moment: datetime, phase: str, status: str) -> dict[str, Any]:
    stamp = moment.astimezone(timezone.utc).isoformat()
    return {
        "run_id": run_id,
        "run_started_at": stamp,
        "run_completed_at": stamp if status in {"PREPARED", "SUCCESS", "ERROR", "BLOCKED"} else None,
        "last_updated_at": stamp,
        "phase": phase,
        "status": status,
    }


def _finalize(*, root: Path, filename: str, payload: dict[str, Any], status: str, phase: str) -> dict[str, Any]:
    payload["ok"] = status in {"PREPARED", "SUCCESS"}
    payload["status"] = status
    payload["blocking_reasons"] = _dedupe_warnings(list(payload.get("blocking_reasons") or []))
    payload["warnings"] = _dedupe_warnings(list(payload.get("warnings") or []))
    current_cap_state = _derive_current_run_daily_cap_state(payload)
    payload["daily_cap_consumed"] = bool(current_cap_state.get("consumed"))
    payload["daily_cap_reason"] = str(current_cap_state.get("reason") or "")
    payload["heartbeat"] = _heartbeat(run_id=str(payload.get("run_id") or ""), moment=_parse_datetime(payload.get("generated_at_utc")) or datetime.now(timezone.utc), phase=phase, status=status)
    atomic_write_json(root / filename, payload)
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


def _safe_int(raw: Any, default: int) -> int:
    try:
        return int(str(raw).strip()) if raw is not None and str(raw).strip() else default
    except (TypeError, ValueError):
        return default


def _safe_float(raw: Any, default: float) -> float:
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


def _safe_error_text(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def _is_explicit_pre_exchange_history_failure(*, blocking_reasons: list[str], failure_stage: str) -> bool:
    lowered = [item.lower() for item in blocking_reasons]
    if failure_stage == "pre_exchange_client_validation":
        return True
    return any("endpoint not in readonly allowlist" in item or "endpoint not in live allowlist" in item for item in lowered)


def _exchange_order_request_may_have_been_sent(exc: Exception) -> bool:
    return not _is_known_pre_exchange_submit_failure(exc)


def _classify_submit_failure_stage(exc: Exception) -> str:
    if _is_known_pre_exchange_submit_failure(exc):
        return "pre_exchange_client_validation"
    return "broker_submit_exception"


def _is_known_pre_exchange_submit_failure(exc: Exception) -> bool:
    message = _safe_error_text(exc).lower()
    return "endpoint not in readonly allowlist" in message or "endpoint not in live allowlist" in message


__all__ = [
    "LIVE_ALLOWED_SYMBOLS_ENV",
    "LIVE_BASE_URL_ENV",
    "LIVE_CONFIRM_SUBMIT_ENV",
    "LIVE_KILL_SWITCH_ENV",
    "LIVE_KILL_SWITCH_PATH_ENV",
    "LIVE_MAX_DAILY_ORDERS_ENV",
    "LIVE_MAX_NOTIONAL_ENV",
    "LIVE_MAX_OPEN_ORDERS_ENV",
    "LIVE_SYMBOL",
    "LIVE_TRADING_ENABLED_ENV",
    "run_binance_live_micro_submit",
    "run_binance_live_micro_submit_prepare_only",
]


