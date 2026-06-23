from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.brokers.binance_spot_testnet import (
    BinanceSpotTestnetClient,
    BinanceTestnetConfigError,
    BinanceTestnetRequestError,
    is_testnet_base_url,
    mask_api_key,
    resolve_credentials,
)
from src.execution.binance_testnet_executor import (
    ALLOWED_SYMBOLS_ENV,
    ARTIFACTS_SUBDIR,
    BASE_URL_ENV,
    CONFIRM_SUBMIT_ENV,
    DEFAULT_QUOTE,
    ENABLE_FLAG,
    KILL_SWITCH_ENV,
    KILL_SWITCH_PATH_ENV,
    MAX_NOTIONAL_ENV,
    MAX_OPEN_ORDERS_ENV,
    ORDER_TEST_ONLY_FLAG,
    _annotate_result,
    _build_testnet_heartbeat,
    _call_broker,
    _check_kill_switch,
    _check_open_order_limit,
    _check_previous_exchange_state_gate,
    _check_submit_guard_gate,
    _derive_positions,
    _load_exchange_filters,
    _load_json_safe,
    _perform_time_sync,
    _previous_mismatch_gate_severity,
    _reconcile_exchange_state,
    _resolve_config,
    _validate_order_against_exchange_filters,
    _with_confirmed_status,
    _write_json,
)
from src.execution.binance_testnet_models import BinanceTestnetOrder


SMOKE_SYMBOL = "BTCUSDT"
_SMOKE_RESULT_FILENAME = "binance_testnet_smoke_submit_result.json"
_MAX_ALLOWED_SMOKE_NOTIONAL = 25.0


def run_binance_testnet_smoke_submit(
    *,
    paper_artifacts_dir: str | Path,
    testnet_artifacts_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    client: BinanceSpotTestnetClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    run_id = f"testnet-smoke-{moment.strftime('%Y%m%d-%H%M%S')}"
    paper_root = Path(paper_artifacts_dir)
    testnet_root = (
        Path(testnet_artifacts_dir)
        if testnet_artifacts_dir is not None
        else paper_root.parent / ARTIFACTS_SUBDIR
    )
    testnet_root.mkdir(parents=True, exist_ok=True)

    source_env: Mapping[str, str] = env if env is not None else os.environ
    config, config_warnings = _resolve_config(source_env)
    result: dict[str, Any] = {
        "run_id": run_id,
        "ok": False,
        "status": "BLOCKED",
        "mode": "TESTNET_SMOKE_SUBMIT",
        "environment": "binance_spot_testnet",
        "testnet": True,
        "live_trading": False,
        "paper_only": False,
        "mainnet_enabled": False,
        "dry_run": False,
        "order_test_only": config.order_test_only,
        "confirm_submit": str(source_env.get(CONFIRM_SUBMIT_ENV) or "").strip() == "YES",
        "base_url": config.base_url,
        "symbol": SMOKE_SYMBOL,
        "requested_notional": None,
        "submit_attempted": False,
        "placed_count": 0,
        "rejected_count": 0,
        "canceled_count": 0,
        "blocking_reasons": [],
        "warnings": list(config_warnings),
        "api_key_masked": None,
        "heartbeat": _build_testnet_heartbeat(
            run_id=run_id,
            moment=moment,
            phase="initializing",
            status="PENDING",
        ),
        "artifacts": {
            _SMOKE_RESULT_FILENAME: str(testnet_root / _SMOKE_RESULT_FILENAME),
        },
    }

    def _block(reason: str, *, category: str = "TESTNET_SUBMIT_FAILED", severity: str = "CRITICAL", phase: str = "blocked") -> dict[str, Any]:
        result["reason"] = reason
        result["status"] = "BLOCKED"
        result["blocking_reasons"] = [reason]
        _annotate_result(
            result,
            category=category,
            severity=severity,
            action_taken="testnet_submit_blocked",
            submit_attempted=bool(result.get("submit_attempted")),
        )
        result["heartbeat"] = _build_testnet_heartbeat(
            run_id=run_id,
            moment=moment,
            phase=phase,
            status="BLOCKED",
        )
        _write_json(testnet_root / _SMOKE_RESULT_FILENAME, result)
        return result

    if str(source_env.get(ENABLE_FLAG) or "").strip() != "1":
        return _block(f"{ENABLE_FLAG} is not '1'. Testnet execution disabled.", severity="ERROR", phase="enable_gate")
    if not is_testnet_base_url(config.base_url):
        return _block(f"Refusing non-testnet base URL: {config.base_url!r}", phase="base_url_gate")
    if config.order_test_only:
        return _block("smoke_submit_requires_order_test_only_zero", phase="order_test_only_gate")
    if str(source_env.get(CONFIRM_SUBMIT_ENV) or "").strip() != "YES":
        return _block(f"missing_{CONFIRM_SUBMIT_ENV.lower()}:require_exact_value_YES", phase="confirm_submit_gate")
    if tuple(config.allowed_symbols) != (SMOKE_SYMBOL,):
        return _block("smoke_submit_requires_allowed_symbols_btcusdt_only", phase="allowed_symbols_gate")
    if config.max_notional_per_order <= 0 or config.max_notional_per_order > _MAX_ALLOWED_SMOKE_NOTIONAL:
        return _block(
            f"smoke_submit_max_notional_out_of_bounds:{config.max_notional_per_order}>{_MAX_ALLOWED_SMOKE_NOTIONAL}",
            phase="max_notional_gate",
        )
    raw_open_order_limit = str(source_env.get(MAX_OPEN_ORDERS_ENV) or "").strip()
    if raw_open_order_limit != "1":
        return _block("smoke_submit_requires_max_open_orders_equals_1", phase="open_order_limit_gate")

    kill_switch_block = _check_kill_switch(source_env=source_env, testnet_root=testnet_root)
    if kill_switch_block is not None:
        return _block(kill_switch_block, category="TESTNET_KILL_SWITCH", phase="kill_switch_gate")

    previous_exchange_state = _load_json_safe(
        testnet_root / "binance_testnet_exchange_state.json",
        default={},
    )
    previous_mismatch_block = _check_previous_exchange_state_gate(
        source_env=source_env,
        previous_exchange_state=previous_exchange_state,
    )
    if previous_mismatch_block is not None:
        return _block(
            previous_mismatch_block,
            category="TESTNET_RECONCILIATION_MISMATCH",
            severity=_previous_mismatch_gate_severity(previous_exchange_state),
            phase="previous_reconciliation_gate",
        )

    submit_guard_block = _check_submit_guard_gate(
        source_env=source_env,
        paper_root=paper_root,
        testnet_root=testnet_root,
        order_test_only=False,
        dry_run=False,
    )
    if submit_guard_block is not None:
        return _block(submit_guard_block, phase="submit_guard_gate")

    api_key: str | None = None
    if client is None:
        try:
            api_key, api_secret = resolve_credentials(env=source_env)
        except BinanceTestnetConfigError as exc:
            return _block(str(exc), severity="ERROR", phase="credentials_gate")
        client = BinanceSpotTestnetClient(
            api_key=api_key,
            api_secret=api_secret,
            base_url=config.base_url,
            recv_window_ms=config.recv_window_ms,
        )
    if client is not None and api_key is None:
        api_key = getattr(client, "api_key_masked", None) or ""
    result["api_key_masked"] = mask_api_key(api_key) if api_key else None

    time_sync = _perform_time_sync(
        client=client,
        recv_window_ms=config.recv_window_ms,
        local_time=moment,
    )
    result["time_sync"] = time_sync
    if time_sync.get("blocked"):
        result["warnings"] = list(result.get("warnings") or []) + list(time_sync.get("warnings") or [])
        return _block(
            str(time_sync.get("reason") or "server_time_sync_blocked"),
            category="TESTNET_TIME_SYNC_FAILED",
            severity="ERROR",
            phase="time_sync_gate",
        )
    result["warnings"] = list(result.get("warnings") or []) + list(time_sync.get("warnings") or [])

    open_order_limit_gate = _check_open_order_limit(client=client, source_env=source_env)
    result["open_order_limit"] = open_order_limit_gate
    result["warnings"] = list(result.get("warnings") or []) + list(open_order_limit_gate.get("warnings") or [])
    if open_order_limit_gate.get("blocked"):
        return _block(
            str(open_order_limit_gate.get("reason") or "open_order_limit_exceeded"),
            category="TESTNET_OPEN_ORDERS_LIMIT",
            severity="ERROR",
            phase="open_order_limit_gate",
        )
    current_open_orders = int(open_order_limit_gate.get("current_count") or 0)
    if current_open_orders != 0:
        return _block(
            f"unexpected_open_orders_present:{current_open_orders}",
            category="TESTNET_OPEN_ORDERS_LIMIT",
            severity="ERROR",
            phase="unexpected_open_orders_gate",
        )

    pre_exchange_state = _reconcile_exchange_state(
        client=client,
        config=config,
        accepted_orders=[],
        derived_positions=[],
        moment=moment,
        warnings=result["warnings"],
        run_id=run_id,
    )
    result["pre_reconciliation_summary"] = dict(pre_exchange_state.get("reconciliation_summary") or {})
    result["pre_open_orders_count"] = int(((pre_exchange_state.get("open_orders") or {}).get("count") or 0))
    if result["pre_open_orders_count"] != 0:
        return _block(
            f"unexpected_open_orders_present:{result['pre_open_orders_count']}",
            category="TESTNET_OPEN_ORDERS_LIMIT",
            severity="ERROR",
            phase="pre_reconciliation_gate",
        )

    exchange_filters_by_symbol = _load_exchange_filters(
        client=client,
        allowed_symbols=(SMOKE_SYMBOL,),
        warnings=result["warnings"],
    )
    symbol_filters = exchange_filters_by_symbol.get(SMOKE_SYMBOL)
    if not symbol_filters:
        return _block(
            f"exchange_filters_missing:{SMOKE_SYMBOL}",
            category="EXCHANGE_FILTER_REJECT",
            severity="ERROR",
            phase="exchange_filters_gate",
        )

    try:
        requested_notional = _resolve_smoke_notional(symbol_filters=symbol_filters, max_notional=config.max_notional_per_order)
    except ValueError as exc:
        return _block(str(exc), category="EXCHANGE_FILTER_REJECT", severity="ERROR", phase="notional_gate")
    result["requested_notional"] = requested_notional

    client_order_id = _build_smoke_client_order_id(run_id)
    order = BinanceTestnetOrder(
        client_order_id=client_order_id,
        symbol=SMOKE_SYMBOL,
        side="BUY",
        type=config.order_type_default,
        quantity=None,
        quote_order_qty=float(requested_notional),
        requested_notional=float(requested_notional),
        reference_price=None,
        paper_event_id="",
        paper_event_type="SMOKE_SUBMIT",
        mode="place_order",
        status="PENDING",
        reason=None,
        created_at=moment,
        metadata={
            "smoke_submit": True,
            "occurred_at": moment.isoformat(),
        },
    )
    filter_rejection = _validate_order_against_exchange_filters(
        order=order,
        symbol_filters=symbol_filters,
    )
    if filter_rejection is not None:
        return _block(filter_rejection, category="EXCHANGE_FILTER_REJECT", severity="ERROR", phase="exchange_filters_gate")

    try:
        broker_response, mode, fill = _call_broker(client=client, config=config, order=order)
    except BinanceTestnetRequestError as exc:
        result["submit_attempted"] = True
        result["rejected_count"] = 1
        result["warnings"] = list(result.get("warnings") or []) + [f"broker_error:{exc}"]
        return _block(str(exc), category="TESTNET_SUBMIT_FAILED", severity="ERROR", phase="submit_attempt")

    accepted_order = _with_confirmed_status(order, broker_response, mode)
    fills = [fill] if fill is not None else []
    positions = _derive_positions(fills=fills, moment=moment)
    post_exchange_state = _reconcile_exchange_state(
        client=client,
        config=config,
        accepted_orders=[accepted_order],
        derived_positions=positions,
        moment=moment,
        warnings=result["warnings"],
        run_id=run_id,
    )
    _write_json(testnet_root / "binance_testnet_exchange_state.json", post_exchange_state)

    post_open_orders_count = int(((post_exchange_state.get("open_orders") or {}).get("count") or 0))
    reconciliation_summary = dict(post_exchange_state.get("reconciliation_summary") or {})
    mismatch_count = int(reconciliation_summary.get("count") or 0)
    highest_severity = str(reconciliation_summary.get("highest_severity") or "INFO")

    result.update(
        {
            "ok": mismatch_count == 0 and post_open_orders_count == 0,
            "status": "SUCCESS" if mismatch_count == 0 and post_open_orders_count == 0 else "ERROR",
            "submit_attempted": True,
            "placed_count": 1,
            "rejected_count": 0,
            "post_open_orders_count": post_open_orders_count,
            "order_summary": {
                "client_order_id": accepted_order.client_order_id,
                "status": accepted_order.status,
                "mode": accepted_order.mode,
                "binance_order_id": broker_response.get("orderId") if isinstance(broker_response, Mapping) else None,
            },
            "fill_summary": fill.to_dict() if fill is not None else None,
            "reconciliation_summary": reconciliation_summary,
            "exchange_state": post_exchange_state,
            "warnings": _dedupe_warnings(list(result.get("warnings") or [])),
        }
    )
    _annotate_result(
        result,
        category=None if result["ok"] else "TESTNET_RECONCILIATION_MISMATCH",
        severity="INFO" if result["ok"] else highest_severity,
        action_taken="testnet_submit_attempted",
        submit_attempted=True,
    )
    result["heartbeat"] = _build_testnet_heartbeat(
        run_id=run_id,
        moment=moment,
        phase="completed",
        status="SUCCESS" if result["ok"] else "ERROR",
    )
    if post_open_orders_count != 0:
        result["reason"] = f"unexpected_open_orders_after_submit:{post_open_orders_count}"
        result["blocking_reasons"] = [result["reason"]]
    elif mismatch_count != 0:
        result["reason"] = f"post_submit_reconciliation_mismatch:{mismatch_count}:{highest_severity}"
        result["blocking_reasons"] = [result["reason"]]
    else:
        result["blocking_reasons"] = []
    _write_json(testnet_root / _SMOKE_RESULT_FILENAME, result)
    return result


def _resolve_smoke_notional(*, symbol_filters: Mapping[str, dict[str, Any]], max_notional: float) -> float:
    candidates: list[float] = []
    min_notional_filter = symbol_filters.get("MIN_NOTIONAL") or {}
    notional_filter = symbol_filters.get("NOTIONAL") or {}
    for raw in (
        min_notional_filter.get("minNotional"),
        notional_filter.get("minNotional"),
    ):
        try:
            if raw is None:
                continue
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            candidates.append(value)
    if not candidates:
        raise ValueError("smoke_min_notional_unavailable")
    target = max(candidates)
    if target > float(max_notional):
        raise ValueError(f"smoke_min_notional_exceeds_cap:{target}>{float(max_notional)}")
    return round(target, 8)


def _build_smoke_client_order_id(run_id: str) -> str:
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:24]
    return f"tnsmk-{digest}"


def _dedupe_warnings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


__all__ = ["SMOKE_SYMBOL", "run_binance_testnet_smoke_submit"]
