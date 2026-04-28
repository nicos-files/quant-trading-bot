from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_evaluation import evaluate_crypto_paper_strategy
from src.execution.crypto_paper_forward import run_crypto_paper_forward


def _candidate_config() -> dict:
    return {
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


def _bundle_with_buy_signal() -> dict:
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


def _bundle_no_signal_no_exit(*, price: float) -> dict:
    """Flat-price bundle: no fast/slow crossover, low/high never cross SL/TP."""
    rows = []
    timestamps = [
        "2026-04-26T10:00:00Z",
        "2026-04-26T10:05:00Z",
        "2026-04-26T10:10:00Z",
        "2026-04-26T10:15:00Z",
        "2026-04-26T10:20:00Z",
    ]
    for timestamp in timestamps:
        rows.append(
            {
                "timestamp": timestamp,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1.0,
            }
        )
    return {"candles": {"BTCUSDT": rows}}


def _write_inputs(root: Path, *, candidate: dict, bundle: dict) -> tuple[Path, Path]:
    candidate_path = root / "candidate.json"
    prices_path = root / "prices.json"
    candidate_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
    prices_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    return candidate_path, prices_path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class CryptoPaperForwardCumulativeArtifactsTests(unittest.TestCase):
    def test_fills_orders_are_cumulative_across_runs_with_no_new_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            candidate = _candidate_config()

            candidate_path, prices_path = _write_inputs(
                root, candidate=candidate, bundle=_bundle_with_buy_signal()
            )
            run1 = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-04-25T10:20:00+00:00",
            )
            self.assertEqual(run1["status"], "SUCCESS")
            self.assertGreaterEqual(run1["fills_count"], 1)

            fills_path = artifacts_dir / "crypto_paper_fills.json"
            orders_path = artifacts_dir / "crypto_paper_orders.json"
            positions_path = artifacts_dir / "crypto_paper_positions.json"

            fills_after_run1 = _read_json(fills_path)
            orders_after_run1 = _read_json(orders_path)
            positions_after_run1 = _read_json(positions_path)
            self.assertEqual(len(fills_after_run1), 1)
            self.assertGreaterEqual(len(orders_after_run1), 1)
            self.assertEqual(len(positions_after_run1), 1)
            self.assertEqual(positions_after_run1[0]["symbol"], "BTCUSDT")

            entry_price = float(positions_after_run1[0]["avg_entry_price"])

            candidate_path2, prices_path2 = _write_inputs(
                root,
                candidate=candidate,
                bundle=_bundle_no_signal_no_exit(price=entry_price),
            )
            run2 = run_crypto_paper_forward(
                candidate_config=candidate_path2,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path2,
                as_of="2026-04-26T10:20:00+00:00",
            )
            self.assertIn(run2["status"], ("SUCCESS", "PARTIAL"))
            self.assertEqual(run2["fills_count"], 0)
            self.assertEqual(run2["exits_count"], 0)

            fills_after_run2 = _read_json(fills_path)
            orders_after_run2 = _read_json(orders_path)
            positions_after_run2 = _read_json(positions_path)

            self.assertEqual(
                len(fills_after_run2),
                len(fills_after_run1),
                "cumulative fills must not be cleared by a zero-fill run",
            )
            run1_fill_ids = sorted(item.get("fill_id") for item in fills_after_run1)
            run2_fill_ids = sorted(item.get("fill_id") for item in fills_after_run2)
            self.assertEqual(run1_fill_ids, run2_fill_ids)

            run1_order_ids = sorted(item.get("order_id") for item in orders_after_run1)
            run2_order_ids = sorted(item.get("order_id") for item in orders_after_run2)
            self.assertTrue(set(run1_order_ids).issubset(set(run2_order_ids)))

            self.assertEqual(len(positions_after_run2), 1)
            self.assertEqual(positions_after_run2[0]["symbol"], "BTCUSDT")

    def test_exit_events_remain_unchanged_when_no_new_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            candidate = _candidate_config()
            candidate_path, prices_path = _write_inputs(
                root, candidate=candidate, bundle=_bundle_with_buy_signal()
            )
            run1 = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-04-25T10:20:00+00:00",
            )
            self.assertEqual(run1["status"], "SUCCESS")

            exits_path = artifacts_dir / "crypto_paper_exit_events.json"
            seeded_event = {
                "exit_id": "seeded-exit-0001",
                "symbol": "BTCUSDT",
                "position_quantity_before": 0.1,
                "exit_quantity": 0.1,
                "exit_reason": "SEEDED",
                "trigger_price": 100.0,
                "fill_price": 100.0,
                "gross_notional": 10.0,
                "fee": 0.0,
                "slippage": 0.0,
                "realized_pnl": 0.0,
                "exited_at": "2026-04-24T09:00:00",
                "source": "test_seed",
                "metadata": {},
            }
            exits_path.write_text(
                json.dumps([seeded_event], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )

            entry_price = float(
                _read_json(artifacts_dir / "crypto_paper_positions.json")[0]["avg_entry_price"]
            )
            candidate_path2, prices_path2 = _write_inputs(
                root,
                candidate=candidate,
                bundle=_bundle_no_signal_no_exit(price=entry_price),
            )
            run2 = run_crypto_paper_forward(
                candidate_config=candidate_path2,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path2,
                as_of="2026-04-26T10:20:00+00:00",
            )
            self.assertEqual(run2["exits_count"], 0)

            exits_after_run2 = _read_json(exits_path)
            exit_ids = [item.get("exit_id") for item in exits_after_run2]
            self.assertIn("seeded-exit-0001", exit_ids)

    def test_evaluation_reconstructs_one_open_trade_from_cumulative_fills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            candidate = _candidate_config()
            candidate_path, prices_path = _write_inputs(
                root, candidate=candidate, bundle=_bundle_with_buy_signal()
            )
            run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-04-25T10:20:00+00:00",
            )

            entry_price = float(
                _read_json(artifacts_dir / "crypto_paper_positions.json")[0]["avg_entry_price"]
            )
            candidate_path2, prices_path2 = _write_inputs(
                root,
                candidate=candidate,
                bundle=_bundle_no_signal_no_exit(price=entry_price),
            )
            run2 = run_crypto_paper_forward(
                candidate_config=candidate_path2,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path2,
                as_of="2026-04-26T10:20:00+00:00",
            )

            evaluation = run2.get("evaluation") or {}
            self.assertEqual(
                evaluation.get("open_trades_count"), 1,
                "cumulative fills should let evaluation reconstruct the open trade",
            )

    def test_inconsistent_state_emits_ledger_history_warning_without_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            (artifacts_dir / "crypto_paper_fills.json").write_text(
                json.dumps([], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            (artifacts_dir / "crypto_paper_orders.json").write_text(
                json.dumps([], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            (artifacts_dir / "crypto_paper_exit_events.json").write_text(
                json.dumps([], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            (artifacts_dir / "crypto_paper_positions.json").write_text(
                json.dumps(
                    [
                        {
                            "symbol": "BTCUSDT",
                            "quantity": 0.001,
                            "avg_entry_price": 76000.0,
                            "realized_pnl": 0.0,
                            "unrealized_pnl": 0.0,
                            "last_price": 76000.0,
                            "updated_at": "2026-04-25T10:20:00",
                            "metadata": {},
                        }
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "crypto_paper_snapshot.json").write_text(
                json.dumps(
                    {
                        "as_of": "2026-04-25T10:20:00",
                        "cash": 75.0,
                        "equity": 100.0,
                        "positions_value": 25.0,
                        "realized_pnl": 0.0,
                        "unrealized_pnl": 0.0,
                        "fees_paid": 0.0,
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "quantity": 0.001,
                                "avg_entry_price": 76000.0,
                                "realized_pnl": 0.0,
                                "unrealized_pnl": 0.0,
                                "last_price": 76000.0,
                                "updated_at": "2026-04-25T10:20:00",
                                "metadata": {},
                            }
                        ],
                        "metadata": {},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )

            closed_trades, open_trades, metrics, _, _, _, all_warnings = evaluate_crypto_paper_strategy(
                artifacts_dir=artifacts_dir,
                output_dir=artifacts_dir / "evaluation",
            )
            self.assertEqual(closed_trades, [])
            self.assertEqual(open_trades, [])
            self.assertTrue(
                any("ledger_history_inconsistency" in str(item) for item in all_warnings),
                f"expected ledger_history_inconsistency warning, got: {all_warnings}",
            )
            self.assertTrue(
                any("ledger_history_inconsistency" in str(item) for item in metrics.warnings),
                f"expected ledger_history_inconsistency warning in metrics, got: {metrics.warnings}",
            )


if __name__ == "__main__":
    unittest.main()
