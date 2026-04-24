from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput
from src.decision_intel.utils.io import ensure_run_dir
from src.market_data.crypto_symbols import is_crypto_symbol, normalize_crypto_symbol
from src.risk import RiskCheckInput, RiskEngine

from .crypto_paper_ledger import CryptoPaperLedger
from .crypto_paper_models import (
    CryptoPaperExecutionConfig,
    CryptoPaperExecutionResult,
    CryptoPaperFill,
    CryptoPaperOrder,
)


class CryptoPaperExecutor:
    def __init__(
        self,
        config: CryptoPaperExecutionConfig | None = None,
        risk_engine: RiskEngine | None = None,
    ):
        self.config = config or CryptoPaperExecutionConfig()
        self.risk_engine = risk_engine or RiskEngine()

    def execute(
        self,
        recommendations: RecommendationOutput,
        latest_quotes: dict[str, Any],
        as_of: datetime,
        ledger: CryptoPaperLedger | None = None,
    ) -> CryptoPaperExecutionResult:
        active_ledger = ledger or CryptoPaperLedger(self.config)
        accepted_orders: list[CryptoPaperOrder] = []
        rejected_orders: list[CryptoPaperOrder] = []
        fills: list[CryptoPaperFill] = []
        warnings: list[str] = []

        for index, item in enumerate(recommendations.recommendations, start=1):
            order = self._build_order(item, as_of, index)
            if order is None:
                continue
            validation_error = self._validate_item(item, latest_quotes)
            if validation_error:
                rejected_orders.append(self._reject(order, validation_error))
                continue

            price = self._reference_price(item, latest_quotes)
            notional = self._requested_notional(item)
            risk_result = self.risk_engine.evaluate(
                RiskCheckInput(
                    symbol=item.asset_id,
                    side=item.action,
                    quantity=None,
                    notional=notional,
                    price=price,
                    cash_available=active_ledger.cash,
                    fees_estimate=self._estimate_fee(notional),
                    expected_net_edge=float(item.expected_return_net_pct or item.expected_return_gross_pct or 0.0),
                    provider_healthy=True,
                    data_quality_score=1.0,
                    metadata={"paper_only": item.extensions.get("paper_only", True)},
                )
            )
            if not risk_result.approved:
                rejected_orders.append(self._reject(order, f"risk:{risk_result.rejected_reason}"))
                continue

            fill = self._build_fill(order, item, price, notional, as_of, index)
            if not active_ledger.can_afford(fill.gross_notional, fill.fee):
                rejected_orders.append(self._reject(order, "insufficient_cash"))
                continue

            active_ledger.apply_buy_fill(fill)
            accepted_orders.append(order)
            fills.append(fill)

        marks = {
            normalize_crypto_symbol(symbol): self._extract_price(quote)
            for symbol, quote in latest_quotes.items()
            if self._extract_price(quote) is not None
        }
        active_ledger.mark_to_market(marks, as_of)
        snapshot = active_ledger.snapshot(as_of, metadata={"quote_currency": self.config.quote_currency})
        return CryptoPaperExecutionResult(
            accepted_orders=accepted_orders,
            rejected_orders=rejected_orders,
            fills=fills,
            portfolio_snapshot=snapshot,
            warnings=warnings,
            metadata={"quote_currency": self.config.quote_currency},
        )

    def _build_order(self, item: Any, as_of: datetime, index: int) -> CryptoPaperOrder | None:
        asset_id = normalize_crypto_symbol(item.asset_id or item.ticker)
        if not asset_id:
            return None
        return CryptoPaperOrder(
            order_id=f"crypto-paper-order-{index:04d}",
            symbol=asset_id,
            side=str(item.action or "").upper(),
            requested_notional=self._requested_notional(item),
            requested_quantity=None,
            reference_price=float(item.price_used or 0.0),
            status="PENDING",
            reason=None,
            created_at=as_of,
            metadata=dict(item.extensions or {}),
        )

    def _validate_item(self, item: Any, latest_quotes: dict[str, Any]) -> str | None:
        symbol = normalize_crypto_symbol(item.asset_id or item.ticker)
        if not is_crypto_symbol(symbol):
            return "non_crypto_symbol"
        if str(item.action or "").upper() != "BUY":
            return "unsupported_action"
        if bool(item.extensions.get("live_enabled")):
            return "live_disabled"
        if not bool(item.extensions.get("paper_only", True)):
            return "paper_only_required"
        price = self._reference_price(item, latest_quotes)
        if price is None or price <= 0:
            return "missing_price"
        notional = self._requested_notional(item)
        if notional < float(self.config.min_notional_per_order):
            return "below_min_notional"
        if notional > float(self.config.max_notional_per_order):
            return "above_max_notional"
        return None

    def _requested_notional(self, item: Any) -> float:
        extension_notional = item.extensions.get("max_paper_notional")
        if extension_notional is not None:
            try:
                return float(extension_notional)
            except (TypeError, ValueError):
                pass
        for value in (item.usd_target_effective, item.usd_target):
            try:
                numeric = float(value or 0.0)
            except (TypeError, ValueError):
                numeric = 0.0
            if numeric > 0:
                return numeric
        return float(self.config.max_notional_per_order)

    def _reference_price(self, item: Any, latest_quotes: dict[str, Any]) -> float | None:
        symbol = normalize_crypto_symbol(item.asset_id or item.ticker)
        quote = latest_quotes.get(symbol) or latest_quotes.get(item.asset_id) or latest_quotes.get(item.ticker)
        if isinstance(quote, dict):
            if quote.get("ask") is not None:
                return float(quote["ask"])
            if quote.get("last_price") is not None:
                return float(quote["last_price"])
        if item.price_used is not None:
            try:
                return float(item.price_used)
            except (TypeError, ValueError):
                return None
        return None

    def _extract_price(self, quote: Any) -> float | None:
        if isinstance(quote, dict):
            for key in ("last_price", "ask", "bid"):
                if quote.get(key) is not None:
                    return float(quote[key])
        if isinstance(quote, (int, float)):
            return float(quote)
        return None

    def _estimate_fee(self, notional: float) -> float:
        return float(notional) * float(self.config.fee_bps) / 10000.0

    def _build_fill(self, order: CryptoPaperOrder, item: Any, reference_price: float, notional: float, as_of: datetime, index: int) -> CryptoPaperFill:
        slippage = float(reference_price) * float(self.config.slippage_bps) / 10000.0
        fill_price = float(reference_price) + slippage
        gross_notional = float(notional)
        fee = self._estimate_fee(gross_notional)
        quantity = gross_notional / fill_price if fill_price > 0 else 0.0
        return CryptoPaperFill(
            fill_id=f"crypto-paper-fill-{index:04d}",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            fill_price=fill_price,
            gross_notional=gross_notional,
            fee=fee,
            slippage=slippage,
            net_notional=gross_notional + fee,
            filled_at=as_of,
            metadata={
                "stop_loss": item.extensions.get("stop_loss"),
                "take_profit": item.extensions.get("take_profit"),
                "provider": item.extensions.get("provider"),
            },
        )

    def _reject(self, order: CryptoPaperOrder, reason: str) -> CryptoPaperOrder:
        return CryptoPaperOrder(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            requested_notional=order.requested_notional,
            requested_quantity=order.requested_quantity,
            reference_price=order.reference_price,
            status="REJECTED",
            reason=reason,
            created_at=order.created_at,
            metadata=dict(order.metadata),
        )


def write_crypto_paper_execution_artifacts(
    run_id: str,
    result: CryptoPaperExecutionResult,
    base_path: str = "runs",
) -> dict[str, Path]:
    run_root = ensure_run_dir(run_id, base_path=base_path)
    target_dir = run_root / "artifacts" / "crypto_paper"
    target_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "crypto_paper_orders.json": [order.to_dict() for order in result.accepted_orders + result.rejected_orders],
        "crypto_paper_fills.json": [fill.to_dict() for fill in result.fills],
        "crypto_paper_positions.json": [position.to_dict() for position in result.portfolio_snapshot.positions],
        "crypto_paper_snapshot.json": result.portfolio_snapshot.to_dict(),
        "crypto_paper_execution_result.json": result.to_dict(),
    }
    written: dict[str, Path] = {}
    for filename, payload in payloads.items():
        path = target_dir / filename
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        written[filename] = path
    return written


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
