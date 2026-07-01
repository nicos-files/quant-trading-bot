from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.brokers.binance_spot_mainnet_readonly import (
    BinanceMainnetReadonlyConfigError,
    BinanceSpotMainnetReadonlyClient,
    DEFAULT_MAINNET_BASE_URL,
    resolve_credentials,
)
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR, ENABLE_READONLY_ENV
from src.utils.atomic_io import atomic_write_json

LIVE_CANCEL_CONFIRM_ENV = "BINANCE_LIVE_CANCEL_CONFIRM"
LIVE_KILL_SWITCH_ENV = "BINANCE_LIVE_KILL_SWITCH"
LIVE_BASE_URL_ENV = "BINANCE_LIVE_BASE_URL"
LIVE_MAX_CANCEL_COUNT_ENV = "BINANCE_LIVE_MAX_CANCEL_COUNT"
_PLAN_FILENAME = "binance_live_cancel_open_orders_plan.json"


def run_binance_live_cancel_open_orders(
    *,
    artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR,
    env: Mapping[str, str] | None = None,
    client: BinanceSpotMainnetReadonlyClient | Any | None = None,
    now: datetime | None = None,
    prepare_only: bool = True,
    execute: bool = False,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    source_env: Mapping[str, str] = env if env is not None else os.environ
    run_id = f"live-cancel-{moment.strftime('%Y%m%d-%H%M%S')}"
    base_url = str(source_env.get(LIVE_BASE_URL_ENV) or DEFAULT_MAINNET_BASE_URL).strip().rstrip("/")
    max_cancel_count = _safe_int(source_env.get(LIVE_MAX_CANCEL_COUNT_ENV), 1)
    result: dict[str, Any] = {
        "run_id": run_id,
        "ok": False,
        "status": "BLOCKED",
        "prepare_only": bool(prepare_only or not execute),
        "execute": bool(execute),
        "submit_attempted": False,
        "cancel_attempted": False,
        "base_url": base_url,
        "open_orders_count": 0,
        "open_orders_summary": [],
        "cancel_candidates": [],
        "max_cancel_count": max_cancel_count,
        "blocking_reasons": [],
        "warnings": [],
        "generated_at_utc": moment.isoformat(),
        "artifacts": {
            _PLAN_FILENAME: str(root / _PLAN_FILENAME),
        },
    }

    if prepare_only and execute:
        result["blocking_reasons"].append("prepare_only_and_execute_mutually_exclusive")
        return _finalize(root=root, payload=result)
    if base_url != DEFAULT_MAINNET_BASE_URL:
        result["blocking_reasons"].append("mainnet_base_url_invalid")
        return _finalize(root=root, payload=result)
    if str(source_env.get(ENABLE_READONLY_ENV) or "").strip() != "1" and client is None:
        result["blocking_reasons"].append(f"{ENABLE_READONLY_ENV} is not '1'.")
        return _finalize(root=root, payload=result)

    if client is None:
        try:
            api_key, api_secret = resolve_credentials(env=source_env)
        except BinanceMainnetReadonlyConfigError as exc:
            result["blocking_reasons"].append(str(exc))
            return _finalize(root=root, payload=result)
        client = BinanceSpotMainnetReadonlyClient(
            api_key=api_key,
            api_secret=api_secret,
            base_url=base_url,
        )

    try:
        open_orders = client.open_orders()
    except Exception as exc:
        result["blocking_reasons"].append(f"open_orders_read_failed:{_safe_error_text(exc)}")
        return _finalize(root=root, payload=result)

    summary = [_summarize_open_order(item) for item in list(open_orders or []) if isinstance(item, Mapping)]
    result["open_orders_summary"] = summary
    result["open_orders_count"] = len(summary)
    result["cancel_candidates"] = [
        {
            "symbol": item.get("symbol"),
            "orderId": item.get("orderId"),
            "side": item.get("side"),
            "status": item.get("status"),
        }
        for item in summary
    ]

    if not execute:
        result["status"] = "PREPARED"
        result["ok"] = True
        if result["open_orders_count"] == 0:
            result["warnings"].append("no_open_orders_found")
        return _finalize(root=root, payload=result)

    result["prepare_only"] = False
    ambiguous = _find_ambiguous_orders(summary)
    if str(source_env.get(LIVE_CANCEL_CONFIRM_ENV) or "").strip() != "YES":
        result["blocking_reasons"].append("live_cancel_confirm_yes_required")
    if str(source_env.get(LIVE_KILL_SWITCH_ENV) or "1").strip() != "0":
        result["blocking_reasons"].append("live_kill_switch_must_be_zero_for_cancel_execute")
    if ambiguous:
        result["blocking_reasons"].append("live_cancel_open_orders_ambiguous")
        result["warnings"].extend(ambiguous)
    if result["open_orders_count"] > max_cancel_count:
        result["blocking_reasons"].append(f"live_cancel_count_exceeds_cap:{result['open_orders_count']}>{max_cancel_count}")
    if not result["blocking_reasons"]:
        result["blocking_reasons"].append("live_cancel_execute_not_implemented")
    return _finalize(root=root, payload=result)


def _summarize_open_order(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(item.get("symbol") or "").upper(),
        "orderId": item.get("orderId"),
        "clientOrderId": str(item.get("clientOrderId") or "") or None,
        "side": item.get("side"),
        "status": item.get("status"),
        "type": item.get("type"),
        "origQty": item.get("origQty"),
        "executedQty": item.get("executedQty"),
    }


def _find_ambiguous_orders(summary: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for item in summary:
        if not item.get("symbol"):
            warnings.append("ambiguous_open_order:missing_symbol")
        if item.get("orderId") in {None, ""}:
            warnings.append("ambiguous_open_order:missing_order_id")
        if not item.get("status"):
            warnings.append("ambiguous_open_order:missing_status")
    return _dedupe(warnings)


def _finalize(*, root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload["blocking_reasons"] = _dedupe([str(item) for item in list(payload.get("blocking_reasons") or []) if str(item).strip()])
    payload["warnings"] = _dedupe([str(item) for item in list(payload.get("warnings") or []) if str(item).strip()])
    if payload.get("status") != "PREPARED":
        payload["status"] = "BLOCKED"
        payload["ok"] = False
    atomic_write_json(root / _PLAN_FILENAME, payload)
    return payload


def _safe_int(raw: Any, default: int) -> int:
    try:
        value = int(str(raw).strip()) if raw is not None and str(raw).strip() else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _safe_error_text(exc: BaseException) -> str:
    return str(exc).replace("\n", " ").strip() or exc.__class__.__name__


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered
