import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput
from src.engines import EngineContext, IntradayCryptoEngine


def _fresh_quote(last_price: float = 107.8) -> dict:
    return {
        "last_price": last_price,
        "timestamp": "2026-04-24T11:59:30+00:00",
    }


def _bullish_candles():
    closes = [100.0 + (i * 0.2) for i in range(40)]
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-04-24 10:00:00", periods=len(closes), freq="5min"),
            "close": closes,
            "volume": [10.0] * len(closes),
        }
    )


def _flat_candles():
    closes = [100.0 + ((i % 2) * 0.0001) for i in range(40)]
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-04-24 10:00:00", periods=len(closes), freq="5min"),
            "close": closes,
            "volume": [10.0] * len(closes),
        }
    )


def _open_candle_only_bullish_signal():
    closes = [100.0] * 39 + [120.0]
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-04-24 08:45:00", periods=len(closes), freq="5min"),
            "close": closes,
            "volume": [10.0] * len(closes),
        }
    )


class IntradayCryptoPaperSignalsTests(unittest.TestCase):
    def _context(self, **overrides):
        base = dict(
            as_of=datetime(2026, 4, 24, 12, 0, 0),
            run_id="20260424-1200",
            mode="test",
            universe=["BTCUSDT", "ETHUSDT"],
            config={
                "enable_crypto_market_data": True,
                "crypto_universe": [
                    {"symbol": "BTCUSDT", "enabled": True, "strategy_enabled": True},
                    {"symbol": "ETHUSDT", "enabled": False, "strategy_enabled": False},
                ],
                "crypto_strategy": {
                    "enabled": True,
                    "timeframe": "5m",
                    "lookback_limit": 120,
                    "fast_ma_window": 9,
                    "slow_ma_window": 21,
                    "min_abs_signal_strength": 0.001,
                    "max_volatility_pct": 0.08,
                    "stop_loss_pct": 0.006,
                    "take_profit_pct": 0.009,
                    "max_paper_notional": 25.0,
                    "allow_short": False,
                },
            },
            provider_health={"binance_spot": {"status": "healthy", "message": "ok"}},
            metadata={"crypto_provider_name": "binance_spot"},
        )
        base.update(overrides)
        return EngineContext(**base)

    def test_strategy_disabled_globally_is_noop(self) -> None:
        engine = IntradayCryptoEngine()
        context = self._context(config={"crypto_universe": [{"symbol": "BTCUSDT", "enabled": True, "strategy_enabled": True}], "crypto_strategy": {"enabled": False}})
        result = engine.run(context)
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertTrue(any("disabled globally" in warning for warning in result.diagnostics.warnings))

    def test_no_symbol_strategy_enabled_is_noop(self) -> None:
        engine = IntradayCryptoEngine()
        context = self._context(
            config={
                "enable_crypto_market_data": True,
                "crypto_universe": [{"symbol": "BTCUSDT", "enabled": True, "strategy_enabled": False}],
                "crypto_strategy": {"enabled": True},
            }
        )
        result = engine.run(context)
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertTrue(any("No strategy-enabled crypto symbols" in warning for warning in result.diagnostics.warnings))

    def test_market_data_disabled_is_noop(self) -> None:
        engine = IntradayCryptoEngine()
        context = self._context(config={**self._context().config, "enable_crypto_market_data": False})
        result = engine.run(context)
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertTrue(any("market data disabled" in warning.lower() for warning in result.diagnostics.warnings))

    def test_bullish_mocked_provider_returns_buy_recommendation(self) -> None:
        engine = IntradayCryptoEngine()
        provider = Mock()
        provider.get_historical_bars.return_value = _bullish_candles()
        provider.get_latest_quote.return_value = _fresh_quote()
        context = self._context(metadata={"crypto_provider_name": "binance_spot", "crypto_provider": provider})
        result = engine.run(context)

        self.assertIsInstance(result.recommendations, RecommendationOutput)
        payload = result.recommendations.to_payload()["recommendations"]
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["action"], "BUY")
        self.assertEqual(payload[0]["ticker"], "BTCUSDT")

    def test_flat_mocked_provider_returns_empty_recommendations(self) -> None:
        engine = IntradayCryptoEngine()
        provider = Mock()
        provider.get_historical_bars.return_value = _flat_candles()
        provider.get_latest_quote.return_value = _fresh_quote(100.0)
        context = self._context(metadata={"crypto_provider_name": "binance_spot", "crypto_provider": provider})
        result = engine.run(context)

        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertTrue(any("no trade candidates" in warning.lower() for warning in result.diagnostics.warnings))

    def test_provider_failure_for_one_symbol_skips_without_crash(self) -> None:
        engine = IntradayCryptoEngine()
        provider = Mock()
        provider.get_historical_bars.side_effect = RuntimeError("boom")
        context = self._context(metadata={"crypto_provider_name": "binance_spot", "crypto_provider": provider})
        result = engine.run(context)

        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertTrue(any("provider error" in warning.lower() for warning in result.diagnostics.warnings))

    def test_provider_failure_for_all_symbols_is_noop(self) -> None:
        engine = IntradayCryptoEngine()
        provider = Mock()
        provider.get_historical_bars.side_effect = RuntimeError("boom")
        context = self._context(metadata={"crypto_provider_name": "binance_spot", "crypto_provider": provider})
        result = engine.run(context)
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])

    def test_risk_engine_rejection_blocks_recommendation(self) -> None:
        engine = IntradayCryptoEngine()
        provider = Mock()
        provider.get_historical_bars.return_value = _bullish_candles()
        provider.get_latest_quote.return_value = _fresh_quote()
        context = self._context(
            metadata={"crypto_provider_name": "binance_spot", "crypto_provider": provider},
            config={**self._context().config, "crypto_risk": {"min_expected_net_edge": 1.0}},
        )
        result = engine.run(context)
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertTrue(any("Risk rejected" in warning for warning in result.diagnostics.warnings))

    def test_engine_returns_recommendation_output_in_all_paths(self) -> None:
        engine = IntradayCryptoEngine()
        context = self._context(config={"crypto_universe": [], "crypto_strategy": {"enabled": False}})
        result = engine.run(context)
        self.assertIsInstance(result.recommendations, RecommendationOutput)

    def test_existing_open_position_blocks_duplicate_buy_signal(self) -> None:
        engine = IntradayCryptoEngine()
        provider = Mock()
        provider.get_historical_bars.return_value = _bullish_candles()
        provider.get_latest_quote.return_value = _fresh_quote()
        context = self._context(
            cash=75.0,
            positions=[{"symbol": "BTCUSDT", "quantity": 0.2, "last_price": 107.8, "avg_entry_price": 100.0}],
            metadata={"crypto_provider_name": "binance_spot", "crypto_provider": provider},
        )
        result = engine.run(context)
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertTrue(any("symbol_position_exists" in warning for warning in result.diagnostics.warnings))

    def test_cash_available_in_recommendation_comes_from_context(self) -> None:
        engine = IntradayCryptoEngine()
        provider = Mock()
        provider.get_historical_bars.return_value = _bullish_candles()
        provider.get_latest_quote.return_value = _fresh_quote()
        context = self._context(
            cash=83.5,
            metadata={"crypto_provider_name": "binance_spot", "crypto_provider": provider},
        )
        result = engine.run(context)
        payload = result.recommendations.to_payload()["recommendations"]
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["cash_available_usd"], 83.5)

    def test_open_candle_is_excluded_from_signal_generation(self) -> None:
        engine = IntradayCryptoEngine()
        provider = Mock()
        provider.get_historical_bars.return_value = _open_candle_only_bullish_signal()
        provider.get_latest_quote.return_value = {
            "last_price": 120.0,
            "timestamp": "2026-04-24T12:01:30+00:00",
        }
        context = self._context(
            as_of=datetime(2026, 4, 24, 12, 2, 0),
            config={
                **self._context().config,
                "crypto_strategy": {**self._context().config["crypto_strategy"], "max_volatility_pct": 10.0},
            },
            metadata={"crypto_provider_name": "binance_spot", "crypto_provider": provider},
        )
        result = engine.run(context)
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])

    def test_stale_quote_blocks_signal_generation(self) -> None:
        engine = IntradayCryptoEngine()
        provider = Mock()
        provider.get_historical_bars.return_value = _bullish_candles()
        stale_at = datetime(2026, 4, 24, 11, 40, tzinfo=timezone.utc)
        provider.get_latest_quote.return_value = {
            "last_price": 107.8,
            "timestamp": stale_at.isoformat(),
        }
        context = self._context(
            as_of=datetime(2026, 4, 24, 12, 0, 0),
            metadata={"crypto_provider_name": "binance_spot", "crypto_provider": provider},
        )
        result = engine.run(context)
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertTrue(any("quote_stale" in warning for warning in result.diagnostics.warnings))

    def test_no_live_order_or_broker_method_is_called(self) -> None:
        engine = IntradayCryptoEngine()
        provider = Mock()
        provider.get_historical_bars.return_value = _bullish_candles()
        provider.get_latest_quote.return_value = _fresh_quote()
        context = self._context(metadata={"crypto_provider_name": "binance_spot", "crypto_provider": provider})
        engine.run(context)
        self.assertFalse(any(call[0] == "place_order" for call in provider.mock_calls))


if __name__ == "__main__":
    unittest.main()
