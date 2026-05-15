from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_RISK_CONFIG = {
    "min_data_quality_score": None,
    "min_expected_net_edge": None,
    "min_notional": None,
    "max_notional": None,
    "max_spread_pct": None,
    "max_open_positions": None,
    "max_total_open_exposure": None,
    "max_symbol_open_exposure": None,
    "reject_reentry_on_open_position": True,
    "reject_if_provider_unhealthy": True,
}


@dataclass
class RiskCheckInput:
    symbol: str
    side: str
    quantity: float | None = None
    notional: float | None = None
    price: float | None = None
    cash_available: float | None = None
    fees_estimate: float | None = None
    expected_net_edge: float | None = None
    spread_pct: float | None = None
    liquidity_score: float | None = None
    data_quality_score: float | None = None
    provider_healthy: bool = True
    open_positions_count: int | None = None
    total_open_exposure: float | None = None
    symbol_open_exposure: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskCheckResult:
    approved: bool
    rejected_reason: str | None = None
    adjusted_quantity: float | None = None
    adjusted_notional: float | None = None
    risk_tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RiskEngine:
    def __init__(self, config: dict[str, Any] | None = None):
        merged = dict(DEFAULT_RISK_CONFIG)
        merged.update(config or {})
        self.config = merged

    def evaluate(self, check: RiskCheckInput) -> RiskCheckResult:
        symbol = str(check.symbol or "").strip().upper()
        side = str(check.side or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if not side:
            raise ValueError("side is required")

        if self.config.get("reject_if_provider_unhealthy", True) and not check.provider_healthy:
            return self._reject("provider_unhealthy", "provider_unhealthy", check)

        minimum = self.config.get("min_data_quality_score")
        if minimum is not None and check.data_quality_score is not None and check.data_quality_score < float(minimum):
            return self._reject("data_quality_below_min", "data_quality", check)

        minimum = self.config.get("min_expected_net_edge")
        if minimum is not None and check.expected_net_edge is not None and check.expected_net_edge < float(minimum):
            return self._reject("expected_net_edge_below_min", "expected_net_edge", check)

        if side == "BUY":
            symbol_open_exposure = float(check.symbol_open_exposure or 0.0)
            if self.config.get("reject_reentry_on_open_position", True) and symbol_open_exposure > 1e-9:
                return self._reject("symbol_position_exists", "symbol_position_exists", check)

            maximum = self.config.get("max_open_positions")
            if (
                maximum is not None
                and check.open_positions_count is not None
                and symbol_open_exposure <= 1e-9
                and int(check.open_positions_count) >= int(maximum)
            ):
                return self._reject("max_open_positions_reached", "max_open_positions", check)

            maximum = self.config.get("max_total_open_exposure")
            if (
                maximum is not None
                and check.notional is not None
                and (float(check.total_open_exposure or 0.0) + float(check.notional)) > float(maximum) + 1e-9
            ):
                return self._reject("max_total_open_exposure_exceeded", "max_total_open_exposure", check)

            maximum = self.config.get("max_symbol_open_exposure")
            if (
                maximum is not None
                and check.notional is not None
                and (symbol_open_exposure + float(check.notional)) > float(maximum) + 1e-9
            ):
                return self._reject("max_symbol_open_exposure_exceeded", "max_symbol_open_exposure", check)

        if (
            check.cash_available is not None
            and check.notional is not None
            and (float(check.notional) + float(check.fees_estimate or 0.0)) > float(check.cash_available) + 1e-9
        ):
            return self._reject("cash_insufficient", "cash", check)

        minimum = self.config.get("min_notional")
        if minimum is not None and check.notional is not None and float(check.notional) < float(minimum):
            return self._reject("notional_below_min", "min_notional", check)

        maximum = self.config.get("max_notional")
        if maximum is not None and check.notional is not None and float(check.notional) > float(maximum):
            return self._reject("notional_above_max", "max_notional", check)

        maximum = self.config.get("max_spread_pct")
        if maximum is not None and check.spread_pct is not None and float(check.spread_pct) > float(maximum):
            return self._reject("spread_above_max", "spread", check)

        return RiskCheckResult(
            approved=True,
            adjusted_quantity=check.quantity,
            adjusted_notional=check.notional,
            risk_tags=["approved"],
            metadata={"symbol": symbol, "side": side},
        )

    def _reject(self, reason: str, tag: str, check: RiskCheckInput) -> RiskCheckResult:
        return RiskCheckResult(
            approved=False,
            rejected_reason=reason,
            adjusted_quantity=check.quantity,
            adjusted_notional=check.notional,
            risk_tags=[tag, "rejected"],
            metadata={"symbol": str(check.symbol or "").strip().upper(), "side": str(check.side or "").strip().upper()},
        )
