"""Binance Spot **Testnet** execution layer for the crypto paper-forward bot.

Reads the existing semantic events emitted by
:mod:`src.reports.crypto_paper_semantics` (``BUY_FILLED_PAPER``,
``TAKE_PROFIT``, ``STOP_LOSS``) and, when explicitly enabled, sends mirroring
orders to the Binance Spot **Testnet** *only*.

Hard safety contract (each gate is enforced *before* any HTTP call):

#. ``ENABLE_BINANCE_TESTNET_EXECUTION`` must be ``"1"``. Anything else =>
   refuse and write an explanatory result with ``ok=false``.
#. ``BINANCE_TESTNET_BASE_URL`` must be a testnet host
   (:func:`src.brokers.binance_spot_testnet.is_testnet_base_url`).
#. ``BINANCE_TESTNET_ORDER_TEST_ONLY`` defaults to ``"1"``: in this mode the
   client uses ``POST /api/v3/order/test`` (Binance no-op validator) so no
   actual order is placed even on testnet. Real placement requires
   ``BINANCE_TESTNET_ORDER_TEST_ONLY=0``.
#. Symbol must be in ``BINANCE_TESTNET_ALLOWED_SYMBOLS``.
#. Per-order notional must not exceed ``BINANCE_TESTNET_MAX_NOTIONAL``.
#. Idempotency: the executor builds a deterministic ``newClientOrderId`` from
   the paper semantic ``event_id``. A persisted state file remembers which
   semantic event ids have already been placed; duplicates are skipped.
#. No live, futures, margin, or withdraw endpoint is callable — the broker
   client refuses them at construction and at the request site.

Artifact layout (separate from paper artifacts):

    artifacts/crypto_testnet/
        binance_testnet_orders.json
        binance_testnet_fills.json
        binance_testnet_positions.json
        binance_testnet_reconciliation.json
        binance_testnet_execution_result.json
        binance_testnet_state.json   # internal dedupe state
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.brokers.binance_spot_testnet import (
    DEFAULT_TESTNET_BASE_URL,
    BinanceSpotTestnetClient,
    BinanceTestnetConfigError,
    BinanceTestnetRequestError,
    is_testnet_base_url,
    mask_api_key,
    resolve_credentials,
)
from src.execution.binance_testnet_models import (
    BinanceTestnetExecutionConfig,
    BinanceTestnetExecutionResult,
    BinanceTestnetFill,
    BinanceTestnetOrder,
    BinanceTestnetPosition,
    BinanceTestnetReconciliationItem,
)
from src.reports.crypto_paper_semantics import build_semantic_layer
from src.utils.atomic_io import atomic_write_json


ENABLE_FLAG = "ENABLE_BINANCE_TESTNET_EXECUTION"
ORDER_TEST_ONLY_FLAG = "BINANCE_TESTNET_ORDER_TEST_ONLY"
BASE_URL_ENV = "BINANCE_TESTNET_BASE_URL"
MAX_NOTIONAL_ENV = "BINANCE_TESTNET_MAX_NOTIONAL"
ALLOWED_SYMBOLS_ENV = "BINANCE_TESTNET_ALLOWED_SYMBOLS"

DEFAULT_MAX_NOTIONAL = 25.0
DEFAULT_ALLOWED_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
DEFAULT_QUOTE = "USDT"

ARTIFACTS_SUBDIR = "crypto_testnet"
_ORDERS_FILENAME = "binance_testnet_orders.json"
_FILLS_FILENAME = "binance_testnet_fills.json"
_POSITIONS_FILENAME = "binance_testnet_positions.json"
_RECON_FILENAME = "binance_testnet_reconciliation.json"
_EXCHANGE_STATE_FILENAME = "binance_testnet_exchange_state.json"
_RESULT_FILENAME = "binance_testnet_execution_result.json"
_STATE_FILENAME = "binance_testnet_state.json"

_ACTIONABLE_EVENT_TYPES: frozenset[str] = frozenset(
    {"BUY_FILLED_PAPER", "TAKE_PROFIT", "STOP_LOSS"}
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_binance_testnet_execution(
    *,
    paper_artifacts_dir: str | Path,
    testnet_artifacts_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    client: BinanceSpotTestnetClient | None = None,
    rebuild_semantic: bool = False,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute the testnet mirroring run.

    Args:
        paper_artifacts_dir: Crypto paper-forward artifacts root (read-only
            for this function — paper artifacts are *never* modified).
        testnet_artifacts_dir: Override target directory. Defaults to
            ``<paper_artifacts_dir>/../crypto_testnet``.
        env: Override environment for unit tests.
        client: Optional pre-built broker client (tests inject a fake).
        rebuild_semantic: Force-rebuild the semantic layer; otherwise reuse
            cached ``crypto_semantic_*.json`` if present.
        now: UTC moment used for ``created_at`` stamping. Defaults to
            ``datetime.now(timezone.utc)``.
        dry_run: When ``True``, performs all gating logic and writes a
            preview result file but does not call the broker even if the
            client is provided. Useful for ops dry-runs.

    Returns:
        A JSON-serializable dict summarizing the run. Always contains
        ``ok``, ``paper_only`` (False — testnet still executes real testnet
        orders when not in order-test mode), ``live_trading`` (always
        ``False``), counts, and a ``reason`` field when blocked.
    """

    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    paper_root = Path(paper_artifacts_dir)
    testnet_root = (
        Path(testnet_artifacts_dir)
        if testnet_artifacts_dir is not None
        else paper_root.parent / ARTIFACTS_SUBDIR
    )
    testnet_root.mkdir(parents=True, exist_ok=True)

    source_env: Mapping[str, str] = env if env is not None else os.environ

    config, config_warnings = _resolve_config(source_env)

    base_result: dict[str, Any] = {
        "ok": False,
        "paper_only": False,
        "live_trading": False,
        "testnet": True,
        "dry_run": bool(dry_run),
        "order_test_only": config.order_test_only,
        "base_url": config.base_url,
        "max_notional": config.max_notional_per_order,
        "allowed_symbols": list(config.allowed_symbols),
        "considered_count": 0,
        "placed_count": 0,
        "test_ok_count": 0,
        "rejected_count": 0,
        "skipped_count": 0,
        "testnet_artifacts_dir": str(testnet_root),
    }

    # ------------------------------------------------------------------
    # Gate 1: enable flag
    # ------------------------------------------------------------------
    if not _is_flag_enabled(source_env.get(ENABLE_FLAG)):
        base_result["reason"] = (
            f"{ENABLE_FLAG} is not '1'. Testnet execution disabled."
        )
        _write_result(testnet_root, base_result)
        return base_result

    # ------------------------------------------------------------------
    # Gate 2: testnet base URL
    # ------------------------------------------------------------------
    if not is_testnet_base_url(config.base_url):
        base_result["reason"] = (
            f"Refusing non-testnet base URL: {config.base_url!r}"
        )
        _write_result(testnet_root, base_result)
        return base_result

    # ------------------------------------------------------------------
    # Gate 3: credentials (only when we will actually call out)
    # ------------------------------------------------------------------
    api_key: str | None = None
    if client is None and not dry_run:
        try:
            api_key, api_secret = resolve_credentials(env=source_env)
        except BinanceTestnetConfigError as exc:
            base_result["reason"] = str(exc)
            _write_result(testnet_root, base_result)
            return base_result
        client = BinanceSpotTestnetClient(
            api_key=api_key,
            api_secret=api_secret,
            base_url=config.base_url,
            recv_window_ms=config.recv_window_ms,
        )
    if client is not None and api_key is None:
        api_key = getattr(client, "api_key_masked", None) or ""
    base_result["api_key_masked"] = mask_api_key(api_key) if api_key else None
    time_sync = _perform_time_sync(
        client=client,
        recv_window_ms=config.recv_window_ms,
        local_time=moment,
    )
    base_result["time_sync"] = time_sync
    if time_sync.get("blocked"):
        base_result["reason"] = str(time_sync.get("reason") or "server_time_sync_blocked")
        base_result["warnings"] = list(time_sync.get("warnings") or [])
        _write_result(testnet_root, base_result)
        return base_result

    # ------------------------------------------------------------------
    # Load semantic events (paper artifacts are read-only).
    # ------------------------------------------------------------------
    semantic = _load_semantic_layer(
        paper_root=paper_root, rebuild=rebuild_semantic, moment=moment
    )
    events = list(semantic.get("events") or [])

    state_path = testnet_root / _STATE_FILENAME
    state = _load_state(state_path)
    placed_event_ids: set[str] = set(state.get("placed_event_ids") or [])

    accepted_orders: list[BinanceTestnetOrder] = []
    rejected_orders: list[BinanceTestnetOrder] = []
    fills: list[BinanceTestnetFill] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = list(config_warnings) + list(time_sync.get("warnings") or [])
    exchange_filters_by_symbol = _load_exchange_filters(
        client=client,
        allowed_symbols=config.allowed_symbols,
        warnings=warnings,
    )
    enforce_exchange_filters = client is not None

    actionable_events: list[dict[str, Any]] = [
        event
        for event in events
        if isinstance(event, dict)
        and str(event.get("event_type") or "") in _ACTIONABLE_EVENT_TYPES
    ]
    base_result["considered_count"] = len(actionable_events)

    for event in actionable_events:
        event_id = str(event.get("event_id") or "")
        event_type = str(event.get("event_type") or "")
        symbol = str(event.get("symbol") or "").upper()

        # Idempotency check first: never duplicate placement for a paper
        # event id, even across runs.
        if event_id and event_id in placed_event_ids and not dry_run:
            skipped.append({"event_id": event_id, "reason": "already_placed"})
            continue

        if symbol not in config.allowed_symbols:
            rejected_orders.append(
                _build_rejected_order(
                    event=event,
                    config=config,
                    moment=moment,
                    reason=f"symbol_not_allowed:{symbol or 'unknown'}",
                )
            )
            continue

        try:
            requested_notional = _resolve_notional_for_event(event=event, config=config)
        except _NotionalError as exc:
            rejected_orders.append(
                _build_rejected_order(
                    event=event,
                    config=config,
                    moment=moment,
                    reason=str(exc),
                )
            )
            continue

        if requested_notional > config.max_notional_per_order + 1e-9:
            rejected_orders.append(
                _build_rejected_order(
                    event=event,
                    config=config,
                    moment=moment,
                    reason=(
                        f"notional_exceeds_max:{requested_notional:.2f}>"
                        f"{config.max_notional_per_order:.2f}"
                    ),
                )
            )
            continue

        side = _side_for_event(event_type)
        client_order_id = build_client_order_id(event)
        order_record = _build_accepted_order(
            event=event,
            config=config,
            moment=moment,
            client_order_id=client_order_id,
            side=side,
            requested_notional=requested_notional,
        )
        if enforce_exchange_filters:
            filter_rejection = _validate_order_against_exchange_filters(
                order=order_record,
                symbol_filters=exchange_filters_by_symbol.get(symbol),
            )
            if filter_rejection is not None:
                rejected_orders.append(
                    _build_rejected_order(
                        event=event,
                        config=config,
                        moment=moment,
                        reason=filter_rejection,
                        client_order_id=client_order_id,
                    )
                )
                continue

        if dry_run or client is None:
            # Never call the broker in dry-run, but still record what would
            # have happened.
            skipped.append(
                {
                    "event_id": event_id,
                    "reason": "dry_run" if dry_run else "no_client",
                    "client_order_id": client_order_id,
                }
            )
            accepted_orders.append(order_record)
            continue

        try:
            broker_response, mode, fill = _call_broker(
                client=client,
                config=config,
                order=order_record,
            )
        except BinanceTestnetRequestError as exc:
            warnings.append(f"broker_error:{event_id}:{exc}")
            rejected_orders.append(
                _build_rejected_order(
                    event=event,
                    config=config,
                    moment=moment,
                    reason=f"broker_error:{exc}",
                    client_order_id=client_order_id,
                )
            )
            continue

        # On success, replace the in-flight order_record with the
        # broker-confirmed status / mode.
        confirmed = _with_confirmed_status(order_record, broker_response, mode)
        accepted_orders.append(confirmed)
        if fill is not None:
            fills.append(fill)
        if event_id:
            placed_event_ids.add(event_id)

    # ------------------------------------------------------------------
    # Persist artifacts.
    # ------------------------------------------------------------------
    positions = _derive_positions(fills=fills, moment=moment)
    exchange_state = _reconcile_exchange_state(
        client=client,
        config=config,
        accepted_orders=accepted_orders,
        derived_positions=positions,
        moment=moment,
        warnings=warnings,
    )
    reconciliation = _build_reconciliation(
        events=actionable_events,
        accepted_orders=accepted_orders,
        rejected_orders=rejected_orders,
    )

    _write_json(testnet_root / _ORDERS_FILENAME, [o.to_dict() for o in accepted_orders + rejected_orders])
    _write_json(testnet_root / _FILLS_FILENAME, [f.to_dict() for f in fills])
    _write_json(testnet_root / _POSITIONS_FILENAME, [p.to_dict() for p in positions])
    _write_json(testnet_root / _RECON_FILENAME, [r.to_dict() for r in reconciliation])
    _write_json(testnet_root / _EXCHANGE_STATE_FILENAME, exchange_state)

    if not dry_run:
        _save_state(
            state_path,
            {
                "placed_event_ids": sorted(placed_event_ids),
                "updated_at": moment.isoformat(),
            },
        )

    final_result_obj = BinanceTestnetExecutionResult(
        accepted_orders=accepted_orders,
        rejected_orders=rejected_orders,
        fills=fills,
        positions=positions,
        reconciliation=reconciliation,
        skipped=skipped,
        warnings=warnings,
        metadata={
            "generated_at": moment.isoformat(),
            "base_url": config.base_url,
            "order_test_only": config.order_test_only,
            "max_notional": config.max_notional_per_order,
            "allowed_symbols": list(config.allowed_symbols),
            "paper_artifacts_dir": str(paper_root),
            "time_sync": time_sync,
            "exchange_state": exchange_state,
        },
    )

    base_result.update(
        {
            "ok": True,
            "placed_count": sum(
                1 for order in accepted_orders if order.mode == "place_order"
            ),
            "test_ok_count": sum(
                1 for order in accepted_orders if order.mode == "order_test"
            ),
            "rejected_count": len(rejected_orders),
            "skipped_count": len(skipped),
            "warnings": warnings,
            "time_sync": time_sync,
            "exchange_state": exchange_state,
            "result": final_result_obj.to_dict(),
        }
    )
    _write_result(testnet_root, base_result)
    return base_result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


class _NotionalError(ValueError):
    pass


def _perform_time_sync(
    *,
    client: BinanceSpotTestnetClient | None,
    recv_window_ms: int,
    local_time: datetime,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "checked": False,
        "blocked": False,
        "warnings": [],
        "recv_window_ms": int(recv_window_ms),
    }
    if client is None:
        result["warnings"].append("server_time_unavailable:no_client")
        return result
    server_time_fn = getattr(client, "server_time", None)
    if not callable(server_time_fn):
        result["warnings"].append("server_time_unavailable:no_server_time_method")
        return result
    try:
        payload = server_time_fn()
    except Exception as exc:
        result["warnings"].append(f"server_time_unavailable:{exc}")
        return result
    result["checked"] = True
    server_time_ms = payload.get("serverTime") if isinstance(payload, Mapping) else None
    try:
        server_time_ms_int = int(server_time_ms)
    except (TypeError, ValueError):
        result["warnings"].append("server_time_invalid_payload")
        return result
    local_time_ms = int(local_time.astimezone(timezone.utc).timestamp() * 1000)
    skew_ms = local_time_ms - server_time_ms_int
    result["server_time_ms"] = server_time_ms_int
    result["local_time_ms"] = local_time_ms
    result["skew_ms"] = skew_ms
    if abs(skew_ms) > int(recv_window_ms):
        result["blocked"] = True
        result["reason"] = f"server_time_skew_exceeds_recv_window:{skew_ms}ms"
        result["warnings"].append(result["reason"])
    return result


def _reconcile_exchange_state(
    *,
    client: BinanceSpotTestnetClient | None,
    config: BinanceTestnetExecutionConfig,
    accepted_orders: Iterable[BinanceTestnetOrder],
    derived_positions: Iterable[BinanceTestnetPosition],
    moment: datetime,
    warnings: list[str],
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "checked_at": moment.isoformat(),
        "account_checked": False,
        "open_orders_checked": False,
        "local_position_symbols": sorted({position.symbol for position in derived_positions}),
        "open_order_symbols": [],
        "balance_symbols": [],
        "mismatches": [],
    }
    if client is None:
        warnings.append("exchange_reconciliation_unavailable:no_client")
        state["reason"] = "no_client"
        return state

    account_fn = getattr(client, "account", None)
    if callable(account_fn):
        try:
            account_payload = account_fn()
            state["account_checked"] = True
            account_summary = _summarize_account_payload(
                payload=account_payload,
                symbols=config.allowed_symbols,
                quote_currency=config.quote_currency,
            )
            state["account"] = account_summary
            state["balance_symbols"] = sorted(account_summary.get("balances", {}).keys())
        except Exception as exc:
            warnings.append(f"exchange_reconciliation_account_unavailable:{exc}")
            state["account_error"] = str(exc)
    else:
        warnings.append("exchange_reconciliation_unavailable:no_account_method")

    open_orders_fn = getattr(client, "open_orders", None)
    if callable(open_orders_fn):
        try:
            open_orders_payload = open_orders_fn()
            state["open_orders_checked"] = True
            open_orders_summary = _summarize_open_orders_payload(open_orders_payload)
            state["open_orders"] = open_orders_summary
            state["open_order_symbols"] = sorted(open_orders_summary.get("by_symbol", {}).keys())
        except Exception as exc:
            warnings.append(f"exchange_reconciliation_open_orders_unavailable:{exc}")
            state["open_orders_error"] = str(exc)
    else:
        warnings.append("exchange_reconciliation_unavailable:no_open_orders_method")

    mismatches = _find_exchange_reconciliation_mismatches(
        accepted_orders=accepted_orders,
        derived_positions=derived_positions,
        exchange_state=state,
        quote_currency=config.quote_currency,
    )
    state["mismatches"] = mismatches
    for mismatch in mismatches:
        warnings.append(f"exchange_reconciliation_mismatch:{mismatch}")
    return state


def _load_exchange_filters(
    *,
    client: BinanceSpotTestnetClient | None,
    allowed_symbols: Iterable[str],
    warnings: list[str],
) -> dict[str, dict[str, dict[str, Any]]]:
    if client is None:
        warnings.append("exchange_filters_unavailable:no_client")
        return {}
    exchange_info_fn = getattr(client, "exchange_info", None)
    if not callable(exchange_info_fn):
        warnings.append("exchange_filters_unavailable:no_exchange_info_method")
        return {}
    try:
        payload = exchange_info_fn(symbols=list(allowed_symbols))
    except Exception as exc:
        warnings.append(f"exchange_filters_unavailable:{exc}")
        return {}
    symbols = payload.get("symbols") if isinstance(payload, Mapping) else None
    if not isinstance(symbols, list):
        warnings.append("exchange_filters_unavailable:invalid_exchange_info")
        return {}

    result: dict[str, dict[str, dict[str, Any]]] = {}
    for item in symbols:
        if not isinstance(item, Mapping):
            continue
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        filters_payload = item.get("filters")
        if not isinstance(filters_payload, list):
            continue
        parsed_filters: dict[str, dict[str, Any]] = {}
        for filter_item in filters_payload:
            if not isinstance(filter_item, Mapping):
                continue
            filter_type = str(filter_item.get("filterType") or "").upper()
            if not filter_type:
                continue
            parsed_filters[filter_type] = dict(filter_item)
        result[symbol] = parsed_filters
    return result


def _validate_order_against_exchange_filters(
    *,
    order: BinanceTestnetOrder,
    symbol_filters: dict[str, dict[str, Any]] | None,
) -> str | None:
    if not symbol_filters:
        return f"exchange_filters_missing:{order.symbol}"

    price_filter = symbol_filters.get("PRICE_FILTER")
    if price_filter is not None:
        price_issue = _validate_reference_price(
            order.reference_price,
            price_filter=price_filter,
        )
        if price_issue is not None:
            return price_issue

    min_notional_issue = _validate_notional_filters(
        order=order,
        symbol_filters=symbol_filters,
    )
    if min_notional_issue is not None:
        return min_notional_issue

    lot_issue = _validate_lot_size_filters(
        order=order,
        symbol_filters=symbol_filters,
    )
    if lot_issue is not None:
        return lot_issue
    return None


def _validate_reference_price(
    reference_price: float | None,
    *,
    price_filter: Mapping[str, Any],
) -> str | None:
    if reference_price is None:
        return None
    price = _to_decimal(reference_price)
    min_price = _to_decimal(price_filter.get("minPrice"))
    max_price = _to_decimal(price_filter.get("maxPrice"))
    tick_size = _to_decimal(price_filter.get("tickSize"))
    if price is None or price <= 0:
        return "price_filter_invalid_reference_price"
    if min_price is not None and min_price > 0 and price < min_price:
        return f"price_below_min:{float(price)}<{float(min_price)}"
    if max_price is not None and max_price > 0 and price > max_price:
        return f"price_above_max:{float(price)}>{float(max_price)}"
    if tick_size is not None and tick_size > 0 and not _is_step_aligned(price, tick_size):
        return f"price_tick_mismatch:{float(price)}@{float(tick_size)}"
    return None


def _validate_notional_filters(
    *,
    order: BinanceTestnetOrder,
    symbol_filters: Mapping[str, dict[str, Any]],
) -> str | None:
    notional = _to_decimal(order.requested_notional)
    if notional is None or notional <= 0:
        return "notional_invalid"

    min_notional_filter = symbol_filters.get("MIN_NOTIONAL")
    if min_notional_filter is not None:
        min_notional = _to_decimal(min_notional_filter.get("minNotional"))
        if min_notional is not None and min_notional > 0 and notional < min_notional:
            return f"min_notional_violation:{float(notional)}<{float(min_notional)}"

    notional_filter = symbol_filters.get("NOTIONAL")
    if notional_filter is not None:
        min_notional = _to_decimal(notional_filter.get("minNotional"))
        max_notional = _to_decimal(notional_filter.get("maxNotional"))
        if min_notional is not None and min_notional > 0 and notional < min_notional:
            return f"notional_below_exchange_min:{float(notional)}<{float(min_notional)}"
        if max_notional is not None and max_notional > 0 and notional > max_notional:
            return f"notional_above_exchange_max:{float(notional)}>{float(max_notional)}"
    return None


def _validate_lot_size_filters(
    *,
    order: BinanceTestnetOrder,
    symbol_filters: Mapping[str, dict[str, Any]],
) -> str | None:
    if order.side == "BUY" and order.quantity is None and order.quote_order_qty is not None:
        return None
    lot_filter = symbol_filters.get("MARKET_LOT_SIZE") or symbol_filters.get("LOT_SIZE")
    if lot_filter is None:
        return None

    quantity = _effective_quantity_for_validation(order)
    if quantity is None:
        return None
    min_qty = _to_decimal(lot_filter.get("minQty"))
    max_qty = _to_decimal(lot_filter.get("maxQty"))
    step_size = _to_decimal(lot_filter.get("stepSize"))
    if min_qty is not None and min_qty > 0 and quantity < min_qty:
        return f"quantity_below_min:{float(quantity)}<{float(min_qty)}"
    if max_qty is not None and max_qty > 0 and quantity > max_qty:
        return f"quantity_above_max:{float(quantity)}>{float(max_qty)}"
    if step_size is not None and step_size > 0 and not _is_step_aligned(quantity, step_size):
        return f"quantity_step_mismatch:{float(quantity)}@{float(step_size)}"
    return None


def _effective_quantity_for_validation(order: BinanceTestnetOrder) -> Decimal | None:
    if order.quantity is not None:
        return _to_decimal(order.quantity)
    if order.quote_order_qty is None or order.reference_price is None:
        return None
    quote_qty = _to_decimal(order.quote_order_qty)
    ref_price = _to_decimal(order.reference_price)
    if quote_qty is None or ref_price is None or ref_price <= 0:
        return None
    return quote_qty / ref_price


def _to_decimal(value: Any) -> Decimal | None:
    try:
        if value is None:
            return None
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _is_step_aligned(value: Decimal, step: Decimal) -> bool:
    if step <= 0:
        return True
    try:
        return (value % step) == 0
    except InvalidOperation:
        return False


def _summarize_account_payload(
    *,
    payload: Any,
    symbols: Iterable[str],
    quote_currency: str,
) -> dict[str, Any]:
    balances_payload = payload.get("balances") if isinstance(payload, Mapping) else None
    balances: dict[str, dict[str, float]] = {}
    interested_assets = {str(quote_currency or "").upper()}
    for symbol in symbols:
        normalized = str(symbol or "").upper()
        if normalized.endswith(str(quote_currency or "").upper()):
            base_asset = normalized[: -len(str(quote_currency or "").upper())]
            if base_asset:
                interested_assets.add(base_asset)
    if isinstance(balances_payload, list):
        for item in balances_payload:
            if not isinstance(item, Mapping):
                continue
            asset = str(item.get("asset") or "").upper()
            if not asset or asset not in interested_assets:
                continue
            try:
                free = float(item.get("free") or 0.0)
                locked = float(item.get("locked") or 0.0)
            except (TypeError, ValueError):
                continue
            balances[asset] = {
                "free": free,
                "locked": locked,
                "total": free + locked,
            }
    return {"balances": balances}


def _summarize_open_orders_payload(payload: Any) -> dict[str, Any]:
    orders = payload if isinstance(payload, list) else []
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for item in orders:
        if not isinstance(item, Mapping):
            continue
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        by_symbol.setdefault(symbol, []).append(
            {
                "clientOrderId": item.get("clientOrderId"),
                "status": item.get("status"),
                "side": item.get("side"),
                "type": item.get("type"),
                "origQty": item.get("origQty"),
                "executedQty": item.get("executedQty"),
            }
        )
    return {
        "count": sum(len(items) for items in by_symbol.values()),
        "by_symbol": by_symbol,
    }


def _find_exchange_reconciliation_mismatches(
    *,
    accepted_orders: Iterable[BinanceTestnetOrder],
    derived_positions: Iterable[BinanceTestnetPosition],
    exchange_state: Mapping[str, Any],
    quote_currency: str,
) -> list[str]:
    mismatches: list[str] = []
    open_orders = ((exchange_state.get("open_orders") or {}).get("by_symbol") or {}) if isinstance(exchange_state.get("open_orders"), Mapping) else {}
    balances = ((exchange_state.get("account") or {}).get("balances") or {}) if isinstance(exchange_state.get("account"), Mapping) else {}

    for order in accepted_orders:
        if order.status == "FILLED":
            symbol_open_orders = open_orders.get(order.symbol) or []
            if any(str(item.get("clientOrderId") or "") == order.client_order_id for item in symbol_open_orders):
                mismatches.append(f"filled_order_still_open:{order.client_order_id}")

    for position in derived_positions:
        symbol = str(position.symbol or "").upper()
        base_asset = symbol[: -len(quote_currency)] if symbol.endswith(quote_currency) else symbol
        balance = balances.get(base_asset)
        if balance is None:
            mismatches.append(f"missing_exchange_balance:{base_asset}")
            continue
        exchange_qty = float(balance.get("total") or 0.0)
        if abs(exchange_qty - float(position.quantity)) > 1e-9:
            mismatches.append(
                f"position_qty_mismatch:{symbol}:local={float(position.quantity):.12f}:exchange={exchange_qty:.12f}"
            )
    return mismatches


def _resolve_config(env: Mapping[str, str]) -> tuple[BinanceTestnetExecutionConfig, list[str]]:
    warnings: list[str] = []
    base_url = (env.get(BASE_URL_ENV) or DEFAULT_TESTNET_BASE_URL).strip()
    order_test_only = _is_flag_enabled(env.get(ORDER_TEST_ONLY_FLAG, "1"))
    enable = _is_flag_enabled(env.get(ENABLE_FLAG))

    raw_max = env.get(MAX_NOTIONAL_ENV)
    try:
        max_notional = float(raw_max) if raw_max is not None and str(raw_max).strip() != "" else DEFAULT_MAX_NOTIONAL
    except (TypeError, ValueError):
        warnings.append(f"invalid_{MAX_NOTIONAL_ENV.lower()}:{raw_max!r}_using_default_{DEFAULT_MAX_NOTIONAL}")
        max_notional = DEFAULT_MAX_NOTIONAL
    if max_notional <= 0:
        warnings.append(f"non_positive_max_notional:{max_notional}_clamped_to_default_{DEFAULT_MAX_NOTIONAL}")
        max_notional = DEFAULT_MAX_NOTIONAL

    raw_symbols = env.get(ALLOWED_SYMBOLS_ENV)
    if raw_symbols is None or not str(raw_symbols).strip():
        allowed_symbols: tuple[str, ...] = DEFAULT_ALLOWED_SYMBOLS
    else:
        parsed = tuple(
            symbol.strip().upper()
            for symbol in str(raw_symbols).split(",")
            if symbol.strip()
        )
        allowed_symbols = parsed or DEFAULT_ALLOWED_SYMBOLS

    return (
        BinanceTestnetExecutionConfig(
            base_url=base_url,
            quote_currency=DEFAULT_QUOTE,
            max_notional_per_order=float(max_notional),
            allowed_symbols=allowed_symbols,
            order_type_default="MARKET",
            order_test_only=order_test_only,
            enable_testnet_execution=enable,
            exit_full_position=True,
            recv_window_ms=5000,
        ),
        warnings,
    )


def _is_flag_enabled(value: Any) -> bool:
    return str(value or "").strip() == "1"


def _load_semantic_layer(
    *, paper_root: Path, rebuild: bool, moment: datetime
) -> dict[str, Any]:
    semantic_dir = paper_root / "semantic"
    summary_path = semantic_dir / "crypto_semantic_summary.json"
    events_path = semantic_dir / "crypto_semantic_events.json"
    if not rebuild and summary_path.exists() and events_path.exists():
        summary = _load_json_safe(summary_path, default={})
        events = _load_json_safe(events_path, default=[])
        if isinstance(summary, dict) and isinstance(events, list):
            return {"summary": summary, "events": events}
    return build_semantic_layer(
        artifacts_dir=paper_root,
        output_dir=semantic_dir,
        write=True,
        now=moment,
    )


def build_client_order_id(event: Mapping[str, Any]) -> str:
    """Return a deterministic, Binance-safe ``newClientOrderId`` for ``event``.

    Binance accepts 1..36 chars, ``[A-Za-z0-9_-]``. We hash the semantic
    ``event_id`` to keep the output safe and short, and we prefix the hash
    with a short event-type tag so logs are human-readable.
    """

    event_id = str(event.get("event_id") or "")
    event_type = str(event.get("event_type") or "")
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:24]
    prefix_map = {
        "BUY_FILLED_PAPER": "tnbuy",
        "TAKE_PROFIT": "tntp",
        "STOP_LOSS": "tnsl",
    }
    prefix = prefix_map.get(event_type, "tnxx")
    return f"{prefix}-{digest}"


def _side_for_event(event_type: str) -> str:
    if event_type == "BUY_FILLED_PAPER":
        return "BUY"
    return "SELL"


def _resolve_notional_for_event(
    *, event: Mapping[str, Any], config: BinanceTestnetExecutionConfig
) -> float:
    metadata = event.get("metadata") or {}
    event_type = str(event.get("event_type") or "")
    if event_type == "BUY_FILLED_PAPER":
        notional = metadata.get("gross_notional")
        if notional is None or float(notional) <= 0:
            raise _NotionalError("missing_or_zero_gross_notional")
        return float(notional)
    # TAKE_PROFIT / STOP_LOSS: notional = exit_quantity * fill_price
    qty = metadata.get("exit_quantity")
    price = metadata.get("fill_price") or metadata.get("trigger_price")
    if qty is None or price is None or float(qty) <= 0 or float(price) <= 0:
        raise _NotionalError("missing_exit_quantity_or_price")
    return float(qty) * float(price)


def _build_accepted_order(
    *,
    event: Mapping[str, Any],
    config: BinanceTestnetExecutionConfig,
    moment: datetime,
    client_order_id: str,
    side: str,
    requested_notional: float,
) -> BinanceTestnetOrder:
    metadata = event.get("metadata") or {}
    event_id = str(event.get("event_id") or "")
    event_type = str(event.get("event_type") or "")
    symbol = str(event.get("symbol") or "").upper()
    if event_type == "BUY_FILLED_PAPER":
        quote_qty = round(requested_notional, 8)
        base_qty = None
    else:
        quote_qty = None
        raw_qty = metadata.get("exit_quantity")
        base_qty = float(raw_qty) if raw_qty is not None else None
    return BinanceTestnetOrder(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        type=config.order_type_default,
        quantity=base_qty,
        quote_order_qty=quote_qty,
        requested_notional=float(requested_notional),
        reference_price=_extract_reference_price(metadata),
        paper_event_id=event_id,
        paper_event_type=event_type,
        mode="order_test" if config.order_test_only else "place_order",
        status="PENDING",
        reason=None,
        created_at=moment,
        metadata={
            "paper_metadata": dict(metadata),
        },
    )


def _build_rejected_order(
    *,
    event: Mapping[str, Any],
    config: BinanceTestnetExecutionConfig,
    moment: datetime,
    reason: str,
    client_order_id: str | None = None,
) -> BinanceTestnetOrder:
    metadata = event.get("metadata") or {}
    event_id = str(event.get("event_id") or "")
    event_type = str(event.get("event_type") or "")
    symbol = str(event.get("symbol") or "").upper()
    return BinanceTestnetOrder(
        client_order_id=client_order_id or build_client_order_id(event),
        symbol=symbol,
        side=_side_for_event(event_type),
        type=config.order_type_default,
        quantity=None,
        quote_order_qty=None,
        requested_notional=float(metadata.get("gross_notional") or 0.0),
        reference_price=_extract_reference_price(metadata),
        paper_event_id=event_id,
        paper_event_type=event_type,
        mode="order_test" if config.order_test_only else "place_order",
        status="REJECTED",
        reason=reason,
        created_at=moment,
        metadata={"paper_metadata": dict(metadata)},
    )


def _extract_reference_price(metadata: Mapping[str, Any]) -> float | None:
    for key in ("fill_price", "trigger_price", "reference_price"):
        value = metadata.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _call_broker(
    *,
    client: BinanceSpotTestnetClient,
    config: BinanceTestnetExecutionConfig,
    order: BinanceTestnetOrder,
) -> tuple[dict[str, Any], str, BinanceTestnetFill | None]:
    params: dict[str, Any] = {
        "symbol": order.symbol,
        "side": order.side,
        "type": order.type,
        "newClientOrderId": order.client_order_id,
    }
    if order.type == "MARKET":
        if order.side == "BUY":
            if order.quote_order_qty is not None:
                params["quoteOrderQty"] = order.quote_order_qty
            elif order.quantity is not None:
                params["quantity"] = order.quantity
            else:
                raise BinanceTestnetRequestError("MARKET BUY requires quantity or quoteOrderQty")
        else:  # SELL
            if order.quantity is not None:
                params["quantity"] = order.quantity
            elif order.quote_order_qty is not None:
                params["quoteOrderQty"] = order.quote_order_qty
            else:
                raise BinanceTestnetRequestError("MARKET SELL requires quantity or quoteOrderQty")

    if config.order_test_only:
        response = client.order_test(params=params)
        return response, "order_test", None

    response = client.place_order(params=params)
    fill = _maybe_build_fill(response=response, order=order)
    return response, "place_order", fill


def _maybe_build_fill(
    *, response: Mapping[str, Any], order: BinanceTestnetOrder
) -> BinanceTestnetFill | None:
    if not isinstance(response, Mapping):
        return None
    status = str(response.get("status") or "").upper()
    fills = response.get("fills") or []
    if not fills and status not in ("FILLED", "PARTIALLY_FILLED"):
        return None
    total_qty = 0.0
    weighted_price = 0.0
    commission = 0.0
    commission_asset = ""
    for fill_payload in fills:
        if not isinstance(fill_payload, Mapping):
            continue
        try:
            qty = float(fill_payload.get("qty") or 0.0)
            price = float(fill_payload.get("price") or 0.0)
            commission += float(fill_payload.get("commission") or 0.0)
        except (TypeError, ValueError):
            continue
        commission_asset = str(fill_payload.get("commissionAsset") or commission_asset or "")
        total_qty += qty
        weighted_price += qty * price
    avg_price = (weighted_price / total_qty) if total_qty > 0 else 0.0
    if total_qty <= 0:
        return None
    transact_time = response.get("transactTime")
    try:
        transact_time_ms = int(transact_time) if transact_time is not None else None
    except (TypeError, ValueError):
        transact_time_ms = None
    return BinanceTestnetFill(
        fill_id=f"tn-{order.client_order_id}",
        client_order_id=order.client_order_id,
        binance_order_id=response.get("orderId") or "",
        symbol=order.symbol,
        side=order.side,
        quantity=float(total_qty),
        price=float(avg_price),
        commission=float(commission),
        commission_asset=commission_asset,
        status=status or "FILLED",
        transact_time_ms=transact_time_ms,
        filled_at=order.created_at,
        metadata={"raw_fill_count": len(fills)},
    )


def _with_confirmed_status(
    order: BinanceTestnetOrder, response: Mapping[str, Any], mode: str
) -> BinanceTestnetOrder:
    if mode == "order_test":
        new_status = "TEST_OK"
    else:
        raw = str((response or {}).get("status") or "ACCEPTED").upper()
        new_status = raw or "ACCEPTED"
    payload = asdict(order)
    payload["status"] = new_status
    payload["mode"] = mode
    payload["metadata"] = dict(payload.get("metadata") or {})
    payload["metadata"]["broker_response_summary"] = _summarize_response(response)
    return BinanceTestnetOrder(**payload)


def _summarize_response(response: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response, Mapping):
        return {}
    keep = ("orderId", "clientOrderId", "status", "transactTime", "executedQty", "cummulativeQuoteQty")
    return {key: response.get(key) for key in keep if key in response}


def _derive_positions(
    *, fills: Iterable[BinanceTestnetFill], moment: datetime
) -> list[BinanceTestnetPosition]:
    accumulator: dict[str, dict[str, float]] = {}
    last_event_at: dict[str, datetime] = {}
    for fill in fills:
        bucket = accumulator.setdefault(
            fill.symbol, {"quantity": 0.0, "cost": 0.0}
        )
        signed_qty = fill.quantity if fill.side == "BUY" else -fill.quantity
        bucket["quantity"] += signed_qty
        bucket["cost"] += signed_qty * fill.price
        last_event_at[fill.symbol] = fill.filled_at
    positions: list[BinanceTestnetPosition] = []
    for symbol, agg in accumulator.items():
        qty = float(agg["quantity"])
        cost = float(agg["cost"])
        avg = (cost / qty) if abs(qty) > 1e-12 else 0.0
        positions.append(
            BinanceTestnetPosition(
                symbol=symbol,
                quantity=qty,
                avg_entry_price=avg,
                last_event_at=last_event_at.get(symbol, moment),
                metadata={},
            )
        )
    return positions


def _build_reconciliation(
    *,
    events: Iterable[Mapping[str, Any]],
    accepted_orders: Iterable[BinanceTestnetOrder],
    rejected_orders: Iterable[BinanceTestnetOrder],
) -> list[BinanceTestnetReconciliationItem]:
    by_event_id: dict[str, BinanceTestnetOrder] = {}
    for order in list(accepted_orders) + list(rejected_orders):
        if order.paper_event_id:
            by_event_id[order.paper_event_id] = order
    items: list[BinanceTestnetReconciliationItem] = []
    for event in events:
        event_id = str(event.get("event_id") or "")
        event_type = str(event.get("event_type") or "")
        symbol = str(event.get("symbol") or "").upper()
        metadata = event.get("metadata") or {}
        expected_notional = (
            float(metadata.get("gross_notional"))
            if metadata.get("gross_notional") is not None
            else None
        )
        order = by_event_id.get(event_id)
        mismatches: list[str] = []
        match = True
        if order is None:
            match = False
            mismatches.append("no_testnet_order")
            items.append(
                BinanceTestnetReconciliationItem(
                    paper_event_id=event_id,
                    paper_event_type=event_type,
                    symbol=symbol,
                    paper_side=_side_for_event(event_type),
                    expected_notional=expected_notional,
                    testnet_client_order_id=None,
                    testnet_status=None,
                    testnet_mode=None,
                    match=False,
                    mismatches=mismatches,
                )
            )
            continue
        if order.symbol != symbol:
            mismatches.append(f"symbol_mismatch:{order.symbol}!={symbol}")
            match = False
        if order.side != _side_for_event(event_type):
            mismatches.append(f"side_mismatch:{order.side}")
            match = False
        if (
            expected_notional is not None
            and order.requested_notional > 0
            and abs(order.requested_notional - expected_notional) > 1e-6
            and event_type == "BUY_FILLED_PAPER"
        ):
            mismatches.append(
                f"notional_mismatch:{order.requested_notional}!={expected_notional}"
            )
            match = False
        if order.status == "REJECTED":
            mismatches.append(f"rejected:{order.reason}")
            match = False
        items.append(
            BinanceTestnetReconciliationItem(
                paper_event_id=event_id,
                paper_event_type=event_type,
                symbol=symbol,
                paper_side=_side_for_event(event_type),
                expected_notional=expected_notional,
                testnet_client_order_id=order.client_order_id,
                testnet_status=order.status,
                testnet_mode=order.mode,
                match=match,
                mismatches=mismatches,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


def _write_result(testnet_root: Path, payload: dict[str, Any]) -> None:
    _write_json(testnet_root / _RESULT_FILENAME, payload)


def _load_json_safe(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return default
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _load_state(path: Path) -> dict[str, Any]:
    payload = _load_json_safe(path, default=None)
    if not isinstance(payload, dict):
        return {"placed_event_ids": []}
    if not isinstance(payload.get("placed_event_ids"), list):
        payload["placed_event_ids"] = []
    return payload


def _save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


__all__ = [
    "ALLOWED_SYMBOLS_ENV",
    "ARTIFACTS_SUBDIR",
    "BASE_URL_ENV",
    "DEFAULT_ALLOWED_SYMBOLS",
    "DEFAULT_MAX_NOTIONAL",
    "ENABLE_FLAG",
    "MAX_NOTIONAL_ENV",
    "ORDER_TEST_ONLY_FLAG",
    "build_client_order_id",
    "run_binance_testnet_execution",
]
