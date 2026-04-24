from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from .crypto_paper_models import (
    CryptoPaperExecutionConfig,
    CryptoPaperFill,
    CryptoPaperPortfolioSnapshot,
    CryptoPaperPosition,
)


class CryptoPaperLedger:
    def __init__(self, config: CryptoPaperExecutionConfig):
        self.config = config
        self.cash = float(config.starting_cash)
        self.positions: dict[str, CryptoPaperPosition] = {}
        self.fees_paid = 0.0
        self.realized_pnl = 0.0

    def can_afford(self, gross_notional: float, fee: float) -> bool:
        return (gross_notional + fee) <= self.cash + 1e-9

    def apply_buy_fill(self, fill: CryptoPaperFill) -> None:
        total_cost = float(fill.gross_notional) + float(fill.fee)
        if total_cost > self.cash + 1e-9:
            raise ValueError("insufficient cash")
        existing = self.positions.get(fill.symbol)
        current_qty = float(existing.quantity) if existing else 0.0
        current_cost_basis = current_qty * float(existing.avg_entry_price) if existing else 0.0
        new_qty = current_qty + float(fill.quantity)
        new_cost_basis = current_cost_basis + float(fill.gross_notional)
        avg_entry = (new_cost_basis / new_qty) if new_qty > 0 else 0.0
        self.cash -= total_cost
        self.fees_paid += float(fill.fee)
        self.positions[fill.symbol] = CryptoPaperPosition(
            symbol=fill.symbol,
            quantity=new_qty,
            avg_entry_price=avg_entry,
            realized_pnl=float(existing.realized_pnl) if existing else 0.0,
            unrealized_pnl=float(existing.unrealized_pnl) if existing else 0.0,
            last_price=fill.fill_price,
            updated_at=fill.filled_at,
            metadata=dict(existing.metadata) if existing else {},
        )

    def mark_to_market(self, latest_prices: dict[str, float], as_of: datetime) -> None:
        for symbol, position in list(self.positions.items()):
            price = latest_prices.get(symbol)
            if price is None:
                continue
            unrealized = (float(price) - position.avg_entry_price) * position.quantity
            self.positions[symbol] = replace(
                position,
                last_price=float(price),
                unrealized_pnl=unrealized,
                updated_at=as_of,
            )

    def snapshot(self, as_of: datetime, metadata: dict[str, Any] | None = None) -> CryptoPaperPortfolioSnapshot:
        positions = list(self.positions.values())
        positions_value = sum((position.last_price or position.avg_entry_price) * position.quantity for position in positions)
        unrealized = sum(position.unrealized_pnl for position in positions)
        equity = self.cash + positions_value
        return CryptoPaperPortfolioSnapshot(
            as_of=as_of,
            cash=self.cash,
            equity=equity,
            positions_value=positions_value,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=unrealized,
            fees_paid=self.fees_paid,
            positions=positions,
            metadata=dict(metadata or {}),
        )
