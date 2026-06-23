from __future__ import annotations

import hashlib
import os
from copy import deepcopy
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
    ENABLE_FLAG,
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
    _load_exchange_filters,
    _load_json_safe,
    _perform_time_sync,
    _previous_mismatch_gate_severity,
    _reconcile_exchange_state,
    _resolve_config,
    _summarize_exchange_mismatch_details,
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

    def _block(
        reason: str,
        *,
        category: str = "TESTNET_SUBMIT_FAILED",
        severity: str = "CRITICAL",
        phase: str = "blocked",
    ) -> dict[str, Any]:
        result["reason"] = reason
        result["status"] = "BLOCKED"
        result["blocking_reasons"] = [reason]
        result["warnings"] = _dedupe_warnings(list(result.get("warnings") or []))
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
        return _block(
            f"{ENABLE_FLAG} is not '1'. Testnet execution disabled.",
            severity="ERROR",
            phase="enable_gate",
        )
    if not is_testnet_base_url(config.base_url):
        return _block(
            f"Refusing non-testnet base URL: {config.base_url!r}",
            phase="base_url_gate",
        )
    if config.order_test_only:
        return _block(
            "smoke_submit_requires_order_test_only_zero",
            phase="order_test_only_gate",
        )
    if str(source_env.get(CONFIRM_SUBMIT_ENV) or "").strip() != "YES":
        return _block(
            f"missing_{CONFIRM_SUBMIT_ENV.lower()}:require_exact_value_YES",
            phase="confirm_submit_gate",
        )
    if tuple(config.allowed_symbols) != (SMOKE_SYMBOL,):
        return _block(
            "smoke_submit_requires_allowed_symbols_btcusdt_only",
            phase="allowed_symbols_gate",
        )
    if config.max_notional_per_order <= 0 or config.max_notional_per_order > _MAX_ALLOWED_SMOKE_NOTIONAL:
        return _block(
            f"smoke_submit_max_notional_out_of_bounds:{config.max_notional_per_order}>{_MAX_ALLOWED_SMOKE_NOTIONAL}",
            phase="max_notional_gate",
        )
    raw_open_order_limit = str(source_env.get(MAX_OPEN_ORDERS_ENV) or "").strip()
    if raw_open_order_limit != "1":
        return _block(
            "smoke_submit_requires_max_open_orders_equals_1",
            phase="open_order_limit_gate",
        )

    kill_switch_block = _check_kill_switch(source_env=source_env, testnet_root=testnet_root)
    if kill_switch_block is not None:
        return _block(
            kill_switch_block,
            category="TESTNET_KILL_SWITCH",
            phase="kill_switch_gate",
        )

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
    result["pre_submit_exchange_state"] = deepcopy(pre_exchange_state)
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
        requested_notional = _resolve_smoke_notional(
            symbol_filters=symbol_filters,
            max_notional=config.max_notional_per_order,
        )
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
        return _block(
            filter_rejection,
            category="EXCHANGE_FILTER_REJECT",
            severity="ERROR",
            phase="exchange_filters_gate",
        )

    try:
        broker_response, mode, fill = _call_broker(client=client, config=config, order=order)
    except BinanceTestnetRequestError as exc:
        result["submit_attempted"] = True
        result["rejected_count"] = 1
        result["warnings"] = list(result.get("warnings") or []) + [f"broker_error:{exc}"]
        return _block(str(exc), category="TESTNET_SUBMIT_FAILED", severity="ERROR", phase="submit_attempt")

    accepted_order = _with_confirmed_status(order, broker_response, mode)
    result["submit_attempted"] = True
    result["placed_count"] = 1
    result["order_summary"] = {
        "client_order_id": accepted_order.client_order_id,
        "status": accepted_order.status,
        "mode": accepted_order.mode,
        "binance_order_id": broker_response.get("orderId") if isinstance(broker_response, Mapping) else None,
    }

    post_exchange_state = _reconcile_exchange_state(
        client=client,
        config=config,
        accepted_orders=[accepted_order],
        derived_positions=[],
        moment=moment,
        warnings=result["warnings"],
        run_id=run_id,
    )
    result["post_submit_exchange_state"] = deepcopy(post_exchange_state)
    result["post_open_orders_count"] = int(((post_exchange_state.get("open_orders") or {}).get("count") or 0))

    delta_payload = _build_smoke_delta_payload(
        pre_exchange_state=pre_exchange_state,
        post_exchange_state=post_exchange_state,
        fill=fill,
        broker_response=broker_response,
        symbol=SMOKE_SYMBOL,
        quote_asset=config.quote_currency,
    )
    result.update(
        {
            "baseline_balances": delta_payload["baseline_balances"],
            "expected_delta": delta_payload["expected_delta"],
            "observed_delta": delta_payload["observed_delta"],
            "delta_reconciliation_summary": delta_payload["delta_reconciliation_summary"],
            "delta_reconciliation_mismatch_details": delta_payload["delta_reconciliation_mismatch_details"],
            "preexisting_balance_detected": delta_payload["preexisting_balance_detected"],
            "fill_summary": fill.to_dict() if fill is not None else None,
        }
    )
    if delta_payload["baseline_warning"]:
        result["warnings"].append(delta_payload["baseline_warning"])

    combined_details = list(post_exchange_state.get("mismatch_details") or []) + list(
        delta_payload["delta_reconciliation_mismatch_details"]
    )
    combined_summary = _summarize_exchange_mismatch_details(combined_details)
    combined_messages = [str(item.get("message") or "") for item in combined_details if str(item.get("message") or "").strip()]

    shared_exchange_state = deepcopy(post_exchange_state)
    shared_exchange_state["pre_submit_exchange_state"] = deepcopy(pre_exchange_state)
    shared_exchange_state["post_submit_exchange_state"] = deepcopy(post_exchange_state)
    shared_exchange_state["baseline_balances"] = delta_payload["baseline_balances"]
    shared_exchange_state["expected_delta"] = delta_payload["expected_delta"]
    shared_exchange_state["observed_delta"] = delta_payload["observed_delta"]
    shared_exchange_state["delta_reconciliation_summary"] = delta_payload["delta_reconciliation_summary"]
    shared_exchange_state["delta_reconciliation_mismatch_details"] = delta_payload["delta_reconciliation_mismatch_details"]
    shared_exchange_state["preexisting_balance_detected"] = delta_payload["preexisting_balance_detected"]
    shared_exchange_state["mismatch_details"] = combined_details
    shared_exchange_state["mismatches"] = combined_messages
    shared_exchange_state["reconciliation_summary"] = combined_summary
    _write_json(testnet_root / "binance_testnet_exchange_state.json", shared_exchange_state)
    _write_json(testnet_root / "binance_testnet_reconciliation.json", [])

    mismatch_count = int(combined_summary.get("count") or 0)
    highest_severity = str(combined_summary.get("highest_severity") or "INFO")
    result["reconciliation_summary"] = combined_summary
    result["exchange_state"] = shared_exchange_state
    result["warnings"] = _dedupe_warnings(
        list(result.get("warnings") or []) + [f"exchange_reconciliation_mismatch:{msg}" for msg in combined_messages]
    )

    if fill is None:
        result["reason"] = "smoke_submit_missing_fill"
        result["blocking_reasons"] = [result["reason"]]
    elif result["post_open_orders_count"] != 0:
        result["reason"] = f"unexpected_open_orders_after_submit:{result['post_open_orders_count']}"
        result["blocking_reasons"] = [result["reason"]]
    elif mismatch_count != 0:
        result["reason"] = f"post_submit_reconciliation_mismatch:{mismatch_count}:{highest_severity}"
        result["blocking_reasons"] = [result["reason"]]
    else:
        result["blocking_reasons"] = []

    result["ok"] = fill is not None and result["post_open_orders_count"] == 0 and mismatch_count == 0
    result["status"] = "SUCCESS" if result["ok"] else "ERROR"
    _annotate_result(
        result,
        category=None if result["ok"] else "TESTNET_RECONCILIATION_MISMATCH",
        severity="INFO" if result["ok"] else ("CRITICAL" if fill is None else highest_severity),
        action_taken="testnet_submit_attempted",
        submit_attempted=True,
    )
    result["heartbeat"] = _build_testnet_heartbeat(
        run_id=run_id,
        moment=moment,
        phase="completed",
        status="SUCCESS" if result["ok"] else "ERROR",
    )
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


def _build_smoke_delta_payload(
    *,
    pre_exchange_state: Mapping[str, Any],
    post_exchange_state: Mapping[str, Any],
    fill: Any,
    broker_response: Mapping[str, Any] | Any,
    symbol: str,
    quote_asset: str,
) -> dict[str, Any]:
    base_asset = symbol[: -len(quote_asset)] if symbol.endswith(quote_asset) else symbol
    pre_base = _balance_total(pre_exchange_state, base_asset)
    post_base = _balance_total(post_exchange_state, base_asset)
    pre_quote = _balance_total(pre_exchange_state, quote_asset)
    post_quote = _balance_total(post_exchange_state, quote_asset)

    baseline_balances = {
        base_asset: {"pre_total": pre_base, "post_total": post_base},
        quote_asset: {"pre_total": pre_quote, "post_total": post_quote},
    }
    observed_delta = {
        "base_asset": base_asset,
        "quote_asset": quote_asset,
        "base_qty": None if pre_base is None or post_base is None else (post_base - pre_base),
        "quote_qty": None if pre_quote is None or post_quote is None else (post_quote - pre_quote),
    }

    details: list[dict[str, Any]] = []
    baseline_warning: str | None = None
    preexisting_balance_detected = bool(pre_base is not None and abs(pre_base) > 1e-12)
    if preexisting_balance_detected:
        baseline_warning = f"baseline_external_balance_detected:{base_asset}:{pre_base:.12f}"

    if fill is None:
        details.append(
            _delta_mismatch_detail(
                code="missing_fill",
                message="smoke_submit_missing_fill",
                expected=None,
                observed=None,
            )
        )
        return {
            "baseline_balances": baseline_balances,
            "expected_delta": {
                "base_asset": base_asset,
                "quote_asset": quote_asset,
                "base_qty": None,
                "quote_qty": None,
            },
            "observed_delta": observed_delta,
            "delta_reconciliation_summary": _summarize_exchange_mismatch_details(details),
            "delta_reconciliation_mismatch_details": details,
            "preexisting_balance_detected": preexisting_balance_detected,
            "baseline_warning": baseline_warning,
        }

    fill_quantity = float(getattr(fill, "quantity", 0.0) or 0.0)
    fill_price = float(getattr(fill, "price", 0.0) or 0.0)
    commission = float(getattr(fill, "commission", 0.0) or 0.0)
    commission_asset = str(getattr(fill, "commission_asset", "") or "").upper()
    executed_quote = _safe_float((broker_response or {}).get("cummulativeQuoteQty")) if isinstance(broker_response, Mapping) else None
    if executed_quote is None or executed_quote <= 0:
        executed_quote = fill_quantity * fill_price if fill_quantity > 0 and fill_price > 0 else None

    expected_base_delta = fill_quantity - commission if commission_asset == base_asset and fill_quantity > 0 else fill_quantity
    expected_quote_delta = None
    if executed_quote is not None:
        expected_quote_delta = -executed_quote
        if commission_asset == quote_asset:
            expected_quote_delta -= commission

    expected_delta = {
        "base_asset": base_asset,
        "quote_asset": quote_asset,
        "base_qty": expected_base_delta,
        "quote_qty": expected_quote_delta,
        "commission_asset": commission_asset or None,
        "commission": commission,
    }

    if observed_delta["base_qty"] is None:
        details.append(
            _delta_mismatch_detail(
                code="missing_base_balance_snapshot",
                message=f"missing_base_balance_snapshot:{base_asset}",
                expected=expected_base_delta,
                observed=None,
            )
        )
    elif not _delta_matches(expected_base_delta, observed_delta["base_qty"]):
        details.append(
            _delta_mismatch_detail(
                code="base_delta_mismatch",
                message=(
                    f"base_delta_mismatch:{base_asset}:"
                    f"expected={expected_base_delta:.12f}:observed={observed_delta['base_qty']:.12f}"
                ),
                expected=expected_base_delta,
                observed=observed_delta["base_qty"],
            )
        )

    if expected_quote_delta is None:
        details.append(
            _delta_mismatch_detail(
                code="missing_executed_quote",
                message="missing_executed_quote",
                expected=None,
                observed=observed_delta["quote_qty"],
            )
        )
    elif observed_delta["quote_qty"] is None:
        details.append(
            _delta_mismatch_detail(
                code="missing_quote_balance_snapshot",
                message=f"missing_quote_balance_snapshot:{quote_asset}",
                expected=expected_quote_delta,
                observed=None,
            )
        )
    elif not _delta_matches(expected_quote_delta, observed_delta["quote_qty"]):
        details.append(
            _delta_mismatch_detail(
                code="quote_delta_mismatch",
                message=(
                    f"quote_delta_mismatch:{quote_asset}:"
                    f"expected={expected_quote_delta:.12f}:observed={observed_delta['quote_qty']:.12f}"
                ),
                expected=expected_quote_delta,
                observed=observed_delta["quote_qty"],
            )
        )

    return {
        "baseline_balances": baseline_balances,
        "expected_delta": expected_delta,
        "observed_delta": observed_delta,
        "delta_reconciliation_summary": _summarize_exchange_mismatch_details(details),
        "delta_reconciliation_mismatch_details": details,
        "preexisting_balance_detected": preexisting_balance_detected,
        "baseline_warning": baseline_warning,
    }


def _delta_mismatch_detail(*, code: str, message: str, expected: float | None, observed: float | None) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "code": code,
        "severity": "CRITICAL",
        "level": "critical_hard_stop",
        "blocking": True,
        "message": message,
    }
    if expected is not None:
        detail["expected"] = float(expected)
    if observed is not None:
        detail["observed"] = float(observed)
        if expected is not None:
            absolute_delta = abs(float(observed) - float(expected))
            detail["absolute_delta"] = absolute_delta
            reference = max(abs(float(expected)), abs(float(observed)), 1e-12)
            detail["relative_delta"] = absolute_delta / reference
    return detail


def _balance_total(exchange_state: Mapping[str, Any], asset: str) -> float | None:
    account = exchange_state.get("account") if isinstance(exchange_state, Mapping) else None
    balances = account.get("balances") if isinstance(account, Mapping) else None
    if not isinstance(balances, Mapping):
        return None
    payload = balances.get(str(asset).upper())
    if not isinstance(payload, Mapping):
        return None
    return _safe_float(payload.get("total"))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta_matches(expected: float, observed: float) -> bool:
    absolute_delta = abs(float(expected) - float(observed))
    reference = max(abs(float(expected)), abs(float(observed)), 1e-12)
    relative_delta = absolute_delta / reference
    return absolute_delta <= 1e-8 or relative_delta <= 5e-4


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
