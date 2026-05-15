from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput
from src.market_data.crypto_symbols import enabled_crypto_symbols, is_crypto_symbol, load_crypto_universe, normalize_crypto_symbol
from src.market_data.providers import (
    BinanceSpotMarketDataProvider,
    parse_quote_timestamp,
    quote_age_seconds,
)
from src.risk import RiskCheckInput, RiskEngine
from src.strategies import IntradayCryptoBaselineStrategy

from .base import EngineContext, EngineDiagnostics, EngineResult


class IntradayCryptoEngine:
    name = "intraday_crypto"
    horizon = "intraday"

    def run(self, context: EngineContext) -> EngineResult:
        diagnostics = EngineDiagnostics(engine_name=self.name)
        crypto_config = self._load_crypto_config(context)
        provider_name = str(context.metadata.get("crypto_provider_name") or "binance_spot")
        provider_health = context.provider_health.get(provider_name) if isinstance(context.provider_health, dict) else None

        diagnostics.metadata["provider_name"] = provider_name
        diagnostics.metadata["provider_health"] = provider_health

        if crypto_config is None:
            diagnostics.metadata["crypto_symbols_seen"] = []
            diagnostics.metadata["enabled_crypto_symbols"] = []
            diagnostics.metadata["strategy_enabled_count"] = 0
            diagnostics.metadata["non_crypto_symbols_ignored"] = sorted(
                symbol for symbol in (context.universe or []) if not is_crypto_symbol(symbol)
            )
            diagnostics.warnings.append("No crypto universe configured; intraday crypto engine skipped.")
            return self._result(context, diagnostics)

        strategy_config = self._strategy_config(context)
        if not bool(strategy_config.get("enabled", False)):
            diagnostics.metadata["crypto_symbols_seen"] = [str(item.get("symbol") or "").strip().upper() for item in crypto_config if item.get("symbol")]
            diagnostics.metadata["enabled_crypto_symbols"] = enabled_crypto_symbols(crypto_config)
            diagnostics.metadata["strategy_enabled_count"] = 0
            diagnostics.metadata["non_crypto_symbols_ignored"] = sorted(
                symbol for symbol in (context.universe or []) if not is_crypto_symbol(symbol, crypto_config)
            )
            diagnostics.warnings.append("Crypto strategy disabled globally; intraday crypto engine skipped.")
            return self._result(context, diagnostics)

        symbols_seen = [str(item.get("symbol") or "").strip().upper() for item in crypto_config if item.get("symbol")]
        enabled_symbols = enabled_crypto_symbols(crypto_config)
        strategy_enabled = [
            normalize_crypto_symbol(item.get("symbol", ""))
            for item in crypto_config
            if item.get("enabled") and item.get("strategy_enabled")
        ]
        diagnostics.metadata["crypto_symbols_seen"] = symbols_seen
        diagnostics.metadata["enabled_crypto_symbols"] = enabled_symbols
        diagnostics.metadata["strategy_enabled_count"] = len([item for item in strategy_enabled if item])
        diagnostics.metadata["non_crypto_symbols_ignored"] = sorted(
            symbol for symbol in (context.universe or []) if not is_crypto_symbol(symbol, crypto_config)
        )
        diagnostics.candidates_seen = len(enabled_symbols)

        if not enabled_symbols:
            diagnostics.warnings.append("No enabled crypto symbols configured; intraday crypto engine skipped.")
            return self._result(context, diagnostics)

        if isinstance(provider_health, dict) and provider_health.get("status") == "unhealthy":
            diagnostics.warnings.append("Crypto provider unhealthy; intraday crypto engine remains in no-op mode.")

        if not strategy_enabled:
            diagnostics.warnings.append("No strategy-enabled crypto symbols; intraday crypto engine skipped.")
            return self._result(context, diagnostics)

        if not bool(context.config.get("enable_crypto_market_data")):
            diagnostics.warnings.append("Crypto market data disabled; intraday crypto engine skipped.")
            return self._result(context, diagnostics)

        provider = self._provider(context)
        strategy = IntradayCryptoBaselineStrategy(strategy_config)
        risk_engine = self._risk_engine(context)
        items: list[dict[str, Any]] = []
        failures = 0
        timeframe = str(strategy_config.get("timeframe", "5m"))
        current_positions = self._positions_by_symbol(context.positions)
        open_positions_count = len(current_positions)
        total_open_exposure = sum(self._position_market_value(position) for position in current_positions.values())
        available_cash = float(context.cash) if context.cash is not None else None
        max_quote_age_seconds = self._max_quote_age_seconds(context, timeframe=timeframe)
        diagnostics.metadata["open_positions_count"] = open_positions_count
        diagnostics.metadata["open_position_symbols"] = sorted(current_positions.keys())
        diagnostics.metadata["cash_available"] = available_cash
        diagnostics.metadata["max_quote_age_seconds"] = max_quote_age_seconds

        for symbol in strategy_enabled:
            try:
                candles = provider.get_historical_bars(
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=int(strategy_config.get("lookback_limit", 120)),
                )
                candles = self._closed_candles(candles, timeframe=timeframe, as_of=context.as_of)
                if candles.empty:
                    diagnostics.warnings.append(f"No closed candles available for {symbol}; signal evaluation skipped.")
                    continue
                latest_quote = provider.get_latest_quote(symbol)
            except Exception as exc:
                failures += 1
                diagnostics.warnings.append(f"Crypto provider error for {symbol}: {exc}")
                continue

            quote_issue = self._quote_issue(
                latest_quote,
                as_of=context.as_of,
                max_quote_age_seconds=max_quote_age_seconds,
            )
            if quote_issue is not None:
                diagnostics.warnings.append(f"{quote_issue}:{symbol}")
                continue

            signal = strategy.evaluate(
                symbol=symbol,
                candles=candles,
                latest_quote=latest_quote,
                provider_healthy=not (isinstance(provider_health, dict) and provider_health.get("status") == "unhealthy"),
            )
            if signal is None:
                continue

            symbol_open_exposure = self._position_market_value(current_positions.get(signal.symbol))

            risk_result = risk_engine.evaluate(
                RiskCheckInput(
                    symbol=signal.symbol,
                    side=signal.action,
                    quantity=None,
                    notional=signal.max_notional,
                    price=signal.entry_price,
                    cash_available=available_cash,
                    fees_estimate=0.0,
                    expected_net_edge=float(signal.metadata.get("signal_strength") or signal.score),
                    data_quality_score=1.0,
                    provider_healthy=not (isinstance(provider_health, dict) and provider_health.get("status") == "unhealthy"),
                    open_positions_count=open_positions_count,
                    total_open_exposure=total_open_exposure,
                    symbol_open_exposure=symbol_open_exposure,
                    metadata={
                        "provider": provider_name,
                        "timeframe": timeframe,
                        "cash_available": available_cash,
                        "open_positions_count": open_positions_count,
                    },
                )
            )
            if not risk_result.approved:
                diagnostics.warnings.append(f"Risk rejected {symbol}: {risk_result.rejected_reason}")
                continue

            notional = float(signal.max_notional or 0.0)
            items.append(self._signal_to_item(context, signal, provider_name, available_cash=available_cash))
            if str(signal.action).upper() == "BUY":
                if available_cash is not None:
                    available_cash = max(0.0, available_cash - notional)
                if symbol_open_exposure <= 1e-9:
                    open_positions_count += 1
                total_open_exposure += notional
                current_positions[signal.symbol] = {
                    "symbol": signal.symbol,
                    "notional": max(symbol_open_exposure, 0.0) + notional,
                    "last_price": signal.entry_price,
                    "avg_entry_price": signal.entry_price,
                    "quantity": 1.0,
                }

        diagnostics.candidates_scored = len(items)
        diagnostics.candidates_rejected = max(diagnostics.candidates_seen - diagnostics.candidates_scored, 0)
        diagnostics.metadata["provider_failures"] = failures

        if not items:
            if failures and failures >= len(strategy_enabled):
                diagnostics.warnings.append("Crypto provider failed for all enabled symbols; engine returned no-op.")
            else:
                diagnostics.warnings.append("Crypto strategy produced no trade candidates.")
            return self._result(context, diagnostics)

        return EngineResult(
            engine_name=self.name,
            horizon=self.horizon,
            recommendations=RecommendationOutput.build(
                run_id=context.run_id,
                horizon=self.horizon.upper(),
                asof_date=context.metadata.get("asof_date") or context.as_of.strftime("%Y-%m-%d"),
                policy_id=self.name,
                policy_version="1",
                constraints=[],
                sizing_rule="crypto.paper.fixed_notional",
                recommendations=items,
                cash_summary={},
                cash_policy="engine.paper_only",
                execution_date=context.metadata.get("execution_date"),
                execution_hour=context.metadata.get("execution_hour"),
                metadata={"engine_name": self.name},
            ),
            diagnostics=diagnostics,
        )

    def _load_crypto_config(self, context: EngineContext) -> list[dict] | None:
        config_payload = context.config.get("crypto_universe")
        if isinstance(config_payload, list):
            return config_payload

        explicit = context.config.get("crypto_symbols")
        if isinstance(explicit, list):
            return [
                {
                    "symbol": normalize_crypto_symbol(symbol),
                    "exchange": "binance_spot",
                    "asset_class": "crypto",
                    "enabled": True,
                    "strategy_enabled": False,
                    "paper_enabled": True,
                    "live_enabled": False,
                }
                for symbol in explicit
                if normalize_crypto_symbol(symbol)
            ]

        config_path = context.config.get("crypto_universe_path")
        if config_path:
            return load_crypto_universe(config_path)
        return None

    def _strategy_config(self, context: EngineContext) -> dict[str, Any]:
        strategy = context.config.get("crypto_strategy")
        if isinstance(strategy, dict):
            return dict(strategy)
        return {}

    def _provider(self, context: EngineContext) -> Any:
        provider = context.metadata.get("crypto_provider")
        if provider is not None:
            return provider
        return BinanceSpotMarketDataProvider()

    def _risk_engine(self, context: EngineContext) -> RiskEngine:
        config = context.config.get("crypto_risk")
        if isinstance(config, dict):
            return RiskEngine(config)
        return RiskEngine()

    def _max_quote_age_seconds(self, context: EngineContext, *, timeframe: str) -> float:
        risk_config = context.config.get("crypto_risk") if isinstance(context.config, dict) else None
        strategy_config = context.config.get("crypto_strategy") if isinstance(context.config, dict) else None
        for payload in (risk_config, strategy_config):
            if isinstance(payload, dict) and payload.get("max_quote_age_seconds") is not None:
                try:
                    value = float(payload["max_quote_age_seconds"])
                    if value > 0:
                        return value
                except (TypeError, ValueError):
                    pass
        default_by_timeframe = {
            "1m": 120.0,
            "5m": 600.0,
            "15m": 1800.0,
            "1h": 7200.0,
            "1d": 172800.0,
        }
        return default_by_timeframe.get(str(timeframe or "").strip().lower(), 600.0)

    def _quote_issue(
        self,
        latest_quote: Any,
        *,
        as_of: datetime,
        max_quote_age_seconds: float,
    ) -> str | None:
        if not isinstance(latest_quote, dict):
            return "missing_quote"
        last_price = latest_quote.get("last_price")
        try:
            if last_price is None or float(last_price) <= 0.0:
                return "quote_invalid:last_price"
        except (TypeError, ValueError):
            return "quote_invalid:last_price"

        raw_timestamp = latest_quote.get("timestamp")
        if raw_timestamp is None:
            return "quote_invalid:timestamp_missing"
        if parse_quote_timestamp(raw_timestamp) is None:
            return "quote_invalid:timestamp_unparseable"

        age_seconds = quote_age_seconds(latest_quote, as_of=as_of)
        if age_seconds is None:
            return "quote_invalid:timestamp_missing"
        if age_seconds < -1.0:
            return f"quote_invalid:timestamp_in_future:{age_seconds:.3f}s"
        if age_seconds > float(max_quote_age_seconds):
            return f"quote_stale:{age_seconds:.3f}s"
        return None

    def _signal_to_item(
        self,
        context: EngineContext,
        signal: Any,
        provider_name: str,
        *,
        available_cash: float | None,
    ) -> dict[str, Any]:
        return {
            "ticker": signal.symbol,
            "asset_id": signal.symbol,
            "horizon": self.horizon,
            "action": signal.action,
            "weight": 1.0,
            "usd_target": float(signal.max_notional or 0.0),
            "usd_target_effective": float(signal.max_notional or 0.0),
            "broker_selected": "",
            "current_qty": 0.0,
            "qty_target": 0.0,
            "delta_qty": 0.0,
            "order_side": signal.action,
            "order_type": "PAPER",
            "time_in_force": "GTC",
            "order_qty": 0.0,
            "order_notional_usd": float(signal.max_notional or 0.0),
            "order_notional_ccy": float(signal.max_notional or 0.0),
            "min_notional_usd": 0.0,
            "order_status": "PAPER_SIGNAL",
            "cash_available_usd": available_cash,
            "cash_used_usd": float(signal.max_notional or 0.0),
            "min_capital_viable_usd": None,
            "price_used": signal.entry_price,
            "price_source": provider_name,
            "currency": "USDT",
            "fx_rate_used": 1.0,
            "fx_rate_source": "native_usdt",
            "lot_size": 1,
            "allow_fractional": True,
            "expected_return_gross_pct": float(signal.metadata.get("signal_strength") or signal.score),
            "expected_return_net_pct": float(signal.metadata.get("signal_strength") or signal.score),
            "expected_return_net_usd": float(signal.max_notional or 0.0) * float(signal.metadata.get("signal_strength") or signal.score),
            "expected_return_source": "crypto_baseline",
            "fees_estimated_usd": 0.0,
            "fees_one_way": 0.0,
            "fees_round_trip": 0.0,
            "broker_costs": {},
            "reason": signal.reason,
            "policy_id": self.name,
            "policy_version": "1",
            "constraints": list(signal.risk_tags or []),
            "sizing_rule": "crypto.paper.fixed_notional",
            "asof_date": context.metadata.get("asof_date") or context.as_of.strftime("%Y-%m-%d"),
            "execution_date": context.metadata.get("execution_date"),
            "execution_hour": context.metadata.get("execution_hour"),
            "provider": provider_name,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "confidence": signal.confidence,
            "paper_only": True,
            "live_enabled": False,
            "asset_class": "crypto",
            "max_paper_notional": signal.max_notional,
        }

    def _result(self, context: EngineContext, diagnostics: EngineDiagnostics) -> EngineResult:
        diagnostics.candidates_scored = 0
        diagnostics.candidates_rejected = diagnostics.candidates_seen
        return EngineResult(
            engine_name=self.name,
            horizon=self.horizon,
            recommendations=self._empty_output(context),
            diagnostics=diagnostics,
        )

    def _empty_output(self, context: EngineContext) -> RecommendationOutput:
        return RecommendationOutput.build(
            run_id=context.run_id,
            horizon=self.horizon.upper(),
            asof_date=context.metadata.get("asof_date") or context.as_of.strftime("%Y-%m-%d"),
            policy_id=self.name,
            policy_version="1",
            constraints=[],
            sizing_rule="engine.noop",
            recommendations=[],
            cash_summary={},
            cash_policy="engine.noop",
            execution_date=context.metadata.get("execution_date"),
            execution_hour=context.metadata.get("execution_hour"),
            metadata={"engine_name": self.name},
        )

    def _positions_by_symbol(self, positions: Any) -> dict[str, Any]:
        if isinstance(positions, dict):
            items = positions.values()
        elif isinstance(positions, list):
            items = positions
        else:
            return {}
        result: dict[str, Any] = {}
        for item in items:
            symbol = self._position_symbol(item)
            if not symbol:
                continue
            result[symbol] = item
        return result

    def _position_symbol(self, position: Any) -> str:
        if hasattr(position, "symbol"):
            return normalize_crypto_symbol(getattr(position, "symbol"))
        if isinstance(position, dict):
            return normalize_crypto_symbol(position.get("symbol") or "")
        return ""

    def _position_market_value(self, position: Any) -> float:
        if position is None:
            return 0.0
        if isinstance(position, dict) and position.get("notional") is not None:
            try:
                return max(float(position.get("notional") or 0.0), 0.0)
            except (TypeError, ValueError):
                return 0.0
        quantity = self._position_numeric(position, "quantity")
        last_price = self._position_numeric(position, "last_price")
        avg_entry_price = self._position_numeric(position, "avg_entry_price")
        reference_price = last_price if last_price > 0.0 else avg_entry_price
        return max(quantity, 0.0) * max(reference_price, 0.0)

    def _position_numeric(self, position: Any, field: str) -> float:
        if hasattr(position, field):
            value = getattr(position, field)
        elif isinstance(position, dict):
            value = position.get(field)
        else:
            value = None
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _closed_candles(self, candles: Any, *, timeframe: str, as_of: datetime) -> pd.DataFrame:
        if candles is None or not isinstance(candles, pd.DataFrame) or candles.empty or "date" not in candles.columns:
            return pd.DataFrame() if isinstance(candles, pd.DataFrame) else pd.DataFrame()
        delta = self._timeframe_delta(timeframe)
        if delta is None:
            return candles.copy()
        normalized_as_of = self._naive_utc(as_of)
        frame = candles.copy()
        timestamps = pd.to_datetime(frame["date"], errors="coerce", utc=True)
        close_times = timestamps + pd.Timedelta(delta)
        mask = close_times <= pd.Timestamp(normalized_as_of, tz="UTC")
        filtered = frame.loc[mask.fillna(False)].copy()
        normalized = pd.to_datetime(filtered["date"], errors="coerce", utc=True)
        filtered["date"] = normalized.dt.tz_convert(None)
        return filtered.reset_index(drop=True)

    def _timeframe_delta(self, timeframe: str) -> timedelta | None:
        mapping = {
            "1m": timedelta(minutes=1),
            "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15),
            "1h": timedelta(hours=1),
            "1d": timedelta(days=1),
        }
        return mapping.get(str(timeframe or "").strip().lower())

    def _naive_utc(self, value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
