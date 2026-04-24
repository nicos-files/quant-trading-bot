import sys
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput
from src.engines import EngineContext, EngineResult, IntradayCryptoEngine


class IntradayCryptoEngineTests(unittest.TestCase):
    def test_engine_identity(self) -> None:
        engine = IntradayCryptoEngine()
        self.assertEqual(engine.name, "intraday_crypto")
        self.assertEqual(engine.horizon, "intraday")

    def test_empty_universe_is_safe(self) -> None:
        engine = IntradayCryptoEngine()
        context = EngineContext(
            as_of=datetime(2026, 4, 21, 12, 0, 0),
            run_id="20260421-1200",
            mode="test",
            universe=[],
            metadata={"asof_date": "2026-04-21"},
        )

        result = engine.run(context)

        self.assertIsInstance(result, EngineResult)
        self.assertIsInstance(result.recommendations, RecommendationOutput)
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertTrue(any("No crypto symbols configured" in warning for warning in result.diagnostics.warnings))

    def test_non_crypto_universe_is_noop(self) -> None:
        engine = IntradayCryptoEngine()
        context = EngineContext(
            as_of=datetime(2026, 4, 21, 12, 0, 0),
            run_id="20260421-1200",
            mode="test",
            universe=["AAPL", "MSFT", "GGAL.BA"],
            metadata={"asof_date": "2026-04-21"},
        )

        result = engine.run(context)

        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertEqual(result.diagnostics.metadata["crypto_symbols_seen"], [])

    def test_crypto_universe_detects_symbols_and_returns_safe_noop(self) -> None:
        engine = IntradayCryptoEngine()
        context = EngineContext(
            as_of=datetime(2026, 4, 21, 12, 0, 0),
            run_id="20260421-1200",
            mode="test",
            universe=["BTC-USD", "ETH/USDT", "AAPL"],
            metadata={"asof_date": "2026-04-21"},
        )

        result = engine.run(context)

        self.assertEqual(result.diagnostics.metadata["crypto_symbols_seen"], ["BTC-USD", "ETH/USDT"])
        self.assertIn("AAPL", result.diagnostics.metadata["non_crypto_symbols_ignored"])
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertTrue(
            any("Crypto-specific scoring is not implemented yet" in warning for warning in result.diagnostics.warnings)
        )

    def test_explicit_crypto_config_is_supported(self) -> None:
        engine = IntradayCryptoEngine()
        context = EngineContext(
            as_of=datetime(2026, 4, 21, 12, 0, 0),
            run_id="20260421-1200",
            mode="test",
            universe=["AAPL"],
            config={"crypto_symbols": ["btc-usd"]},
            metadata={"asof_date": "2026-04-21"},
        )

        result = engine.run(context)

        self.assertEqual(result.diagnostics.metadata["crypto_symbols_seen"], ["BTC-USD"])
        self.assertIsInstance(result.recommendations, RecommendationOutput)


if __name__ == "__main__":
    unittest.main()
