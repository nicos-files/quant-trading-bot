import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_forward import run_crypto_paper_forward


class CryptoPaperForwardTests(unittest.TestCase):
    def _candidate_config(self, **overrides) -> dict:
        base = {
            "version": 1,
            "market": "crypto",
            "default_quote_currency": "USDT",
            "strategy": {
                "name": "intraday_crypto_baseline",
                "enabled": True,
                "timeframe": "5m",
                "lookback_limit": 120,
                "fast_ma_window": 2,
                "slow_ma_window": 3,
                "min_abs_signal_strength": 0.0001,
                "max_volatility_pct": 1.0,
                "risk_reward_ratio": 1.5,
                "stop_loss_pct": 0.02,
                "take_profit_pct": 0.01,
                "max_paper_notional": 25.0,
                "allow_short": False,
            },
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "base": "BTC",
                    "quote": "USDT",
                    "exchange": "binance_spot",
                    "asset_class": "crypto",
                    "enabled": True,
                    "min_timeframe": "1m",
                    "strategy_enabled": True,
                    "paper_enabled": True,
                    "live_enabled": False,
                }
            ],
        }
        for key, value in overrides.items():
            if key == "strategy":
                merged = dict(base["strategy"])
                merged.update(value)
                base["strategy"] = merged
            else:
                base[key] = value
        return base

    def _prices_bundle(self) -> dict:
        return {
            "candles": {
                "BTCUSDT": [
                    {"timestamp": "2026-04-25T10:00:00Z", "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 10.0},
                    {"timestamp": "2026-04-25T10:05:00Z", "open": 100.0, "high": 101.5, "low": 99.9, "close": 101.0, "volume": 10.0},
                    {"timestamp": "2026-04-25T10:10:00Z", "open": 101.0, "high": 102.5, "low": 100.9, "close": 102.0, "volume": 11.0},
                    {"timestamp": "2026-04-25T10:15:00Z", "open": 102.0, "high": 103.5, "low": 101.8, "close": 103.0, "volume": 12.0},
                    {"timestamp": "2026-04-25T10:20:00Z", "open": 103.0, "high": 104.0, "low": 102.8, "close": 103.5, "volume": 12.0},
                ]
            }
        }

    def _write_candidate_and_prices(self, root: Path, *, candidate: dict | None = None, bundle: dict | None = None) -> tuple[Path, Path]:
        candidate_path = root / "candidate.json"
        prices_path = root / "prices.json"
        candidate_path.write_text(json.dumps(candidate or self._candidate_config(), ensure_ascii=False), encoding="utf-8")
        prices_path.write_text(json.dumps(bundle or self._prices_bundle(), ensure_ascii=False), encoding="utf-8")
        return candidate_path, prices_path

    def test_candidate_with_live_enabled_true_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self._candidate_config()
            candidate["symbols"][0]["live_enabled"] = True
            candidate_path, prices_path = self._write_candidate_and_prices(root, candidate=candidate)
            result = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=root / "artifacts" / "crypto_paper",
                prices_json=prices_path,
            )
            self.assertEqual(result["status"], "FAILED")
            self.assertIn("live_enabled_true:BTCUSDT", result["validation_errors"])

    def test_candidate_with_api_keys_or_broker_settings_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self._candidate_config()
            candidate["api_key"] = "secret"
            candidate["broker_settings"] = {"name": "bad"}
            candidate_path, prices_path = self._write_candidate_and_prices(root, candidate=candidate)
            result = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=root / "artifacts" / "crypto_paper",
                prices_json=prices_path,
            )
            self.assertEqual(result["status"], "FAILED")
            self.assertIn("candidate_contains_api_keys", result["validation_errors"])
            self.assertIn("candidate_contains_broker_settings", result["validation_errors"])

    def test_valid_candidate_runs_with_static_data_and_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path, prices_path = self._write_candidate_and_prices(root)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            result = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-04-25T10:20:00+00:00",
            )
            self.assertEqual(result["status"], "SUCCESS")
            self.assertTrue((artifacts_dir / "paper_forward" / "crypto_paper_forward_result.json").exists())
            self.assertTrue((artifacts_dir / "paper_forward" / "crypto_paper_forward_report.md").exists())
            self.assertTrue((artifacts_dir / "paper_forward" / "crypto_manual_trade_tickets.json").exists())
            self.assertGreaterEqual(result["manual_trade_ticket_count"], 1)

    def test_no_execution_plan_or_equity_artifacts_are_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path, prices_path = self._write_candidate_and_prices(root)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            equity_artifact = root / "artifacts" / "paper.day_close.v1.0.0.json"
            execution_plan = root / "artifacts" / "execution.plan.v1.0.0.json"
            equity_artifact.parent.mkdir(parents=True, exist_ok=True)
            equity_artifact.write_text("{}", encoding="utf-8")
            execution_plan.write_text("{}", encoding="utf-8")
            result = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-04-25T10:20:00+00:00",
            )
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(equity_artifact.read_text(encoding="utf-8"), "{}")
            self.assertEqual(execution_plan.read_text(encoding="utf-8"), "{}")

    def test_partial_failure_produces_warnings_not_silent_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path, prices_path = self._write_candidate_and_prices(root)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            with patch("src.execution.crypto_paper_forward.evaluate_crypto_paper_strategy", side_effect=RuntimeError("boom")):
                result = run_crypto_paper_forward(
                    candidate_config=candidate_path,
                    artifacts_dir=artifacts_dir,
                    prices_json=prices_path,
                    as_of="2026-04-25T10:20:00+00:00",
                )
            self.assertEqual(result["status"], "PARTIAL")
            self.assertTrue(any("evaluation_failed:boom" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
