from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from .crypto_paper_models import CryptoPaperExecutionConfig, CryptoPaperExitEvent, CryptoPaperPosition


def evaluate_crypto_exit_triggers(
    positions: list[CryptoPaperPosition],
    candles_by_symbol: dict[str, Any],
    as_of: datetime,
    config: CryptoPaperExecutionConfig,
) -> list[CryptoPaperExitEvent]:
    events: list[CryptoPaperExitEvent] = []
    for position in positions:
        quantity = float(position.quantity or 0.0)
        if quantity <= 0.0:
            continue
        stop_loss = _optional_float(position.metadata.get("stop_loss"))
        take_profit = _optional_float(position.metadata.get("take_profit"))
        if stop_loss is None and take_profit is None:
            continue
        rows = _normalize_candles(candles_by_symbol.get(position.symbol))
        if not rows:
            continue
        entry_time = position.updated_at
        for row in rows:
            timestamp = row.get("timestamp")
            if entry_time is not None and isinstance(timestamp, datetime) and timestamp <= entry_time:
                continue
            low = row.get("low")
            high = row.get("high")
            if low is None or high is None:
                continue
            stop_hit = stop_loss is not None and float(low) <= float(stop_loss)
            take_hit = take_profit is not None and float(high) >= float(take_profit)
            if not stop_hit and not take_hit:
                continue
            if stop_hit:
                trigger_price = float(stop_loss)
                reason = "STOP_LOSS"
            else:
                trigger_price = float(take_profit)
                reason = "TAKE_PROFIT"
            events.append(
                CryptoPaperExitEvent(
                    exit_id=f"crypto-exit-{position.symbol}-{len(events) + 1:04d}",
                    symbol=position.symbol,
                    position_quantity_before=quantity,
                    exit_quantity=quantity if bool(config.exit_full_position) else quantity,
                    exit_reason=reason,
                    trigger_price=trigger_price,
                    fill_price=trigger_price,
                    gross_notional=quantity * trigger_price,
                    fee=0.0,
                    slippage=0.0,
                    realized_pnl=0.0,
                    exited_at=timestamp if isinstance(timestamp, datetime) else as_of,
                    source="stop_take_evaluator",
                    metadata={
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "same_candle_conflict": bool(stop_hit and take_hit),
                        "avg_entry_price": float(position.avg_entry_price),
                    },
                )
            )
            break
    return events


def _normalize_candles(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, pd.DataFrame):
        rows = []
        for _, row in payload.sort_values("date").iterrows():
            rows.append(
                {
                    "timestamp": _to_datetime(row.get("date")),
                    "open": _optional_float(row.get("open")),
                    "high": _optional_float(row.get("high")),
                    "low": _optional_float(row.get("low")),
                    "close": _optional_float(row.get("close")),
                    "volume": _optional_float(row.get("volume")),
                }
            )
        return rows
    if isinstance(payload, list):
        rows = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "timestamp": _to_datetime(item.get("timestamp") or item.get("date")),
                    "open": _optional_float(item.get("open")),
                    "high": _optional_float(item.get("high")),
                    "low": _optional_float(item.get("low")),
                    "close": _optional_float(item.get("close")),
                    "volume": _optional_float(item.get("volume")),
                }
            )
        return sorted(rows, key=lambda row: row.get("timestamp") or datetime.min)
    return []


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    try:
        return pd.Timestamp(value).to_pydatetime()
    except Exception:
        return None
