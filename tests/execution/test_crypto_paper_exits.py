import sys
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_exits import evaluate_crypto_exit_triggers
from src.execution.crypto_paper_models import CryptoPaperExecutionConfig, CryptoPaperPosition


class CryptoPaperExitsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.as_of = datetime(2026, 4, 24, 12, 0, 0)
        self.config = CryptoPaperExecutionConfig(enable_exits=True)

    def _position(self, qty=0.1, stop_loss=None, take_profit=None, updated_at=None):
        return CryptoPaperPosition(
            symbol="BTCUSDT",
            quantity=qty,
            avg_entry_price=100.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            last_price=100.0,
            updated_at=updated_at,
            metadata={"stop_loss": stop_loss, "take_profit": take_profit, "avg_entry_price": 100.0},
        )

    def _candles(self, rows):
        return pd.DataFrame(rows)

    def test_position_with_no_stop_take_has_no_exit(self) -> None:
        events = evaluate_crypto_exit_triggers([self._position()], {"BTCUSDT": self._candles([])}, self.as_of, self.config)
        self.assertEqual(events, [])

    def test_candle_low_below_stop_loss_triggers_stop(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(stop_loss=95.0)],
            {"BTCUSDT": self._candles([{"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 101, "low": 94, "close": 95}])},
            self.as_of,
            self.config,
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].exit_reason, "STOP_LOSS")

    def test_candle_high_above_take_profit_triggers_take_profit(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(take_profit=105.0)],
            {"BTCUSDT": self._candles([{"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 106, "low": 99, "close": 105}])},
            self.as_of,
            self.config,
        )
        self.assertEqual(events[0].exit_reason, "TAKE_PROFIT")

    def test_same_candle_hits_both_stop_wins(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(stop_loss=95.0, take_profit=105.0)],
            {"BTCUSDT": self._candles([{"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 106, "low": 94, "close": 100}])},
            self.as_of,
            self.config,
        )
        self.assertEqual(events[0].exit_reason, "STOP_LOSS")
        self.assertTrue(events[0].metadata["same_candle_conflict"])

    def test_only_first_trigger_creates_exit(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(take_profit=105.0)],
            {"BTCUSDT": self._candles([
                {"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 106, "low": 99, "close": 105},
                {"date": datetime(2026, 4, 24, 11, 5), "open": 105, "high": 110, "low": 104, "close": 109},
            ])},
            self.as_of,
            self.config,
        )
        self.assertEqual(len(events), 1)

    def test_exit_is_full_quantity_by_default(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(qty=0.25, take_profit=105.0)],
            {"BTCUSDT": self._candles([{"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 106, "low": 99, "close": 105}])},
            self.as_of,
            self.config,
        )
        self.assertEqual(events[0].exit_quantity, 0.25)

    def test_zero_quantity_position_is_ignored(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(qty=0.0, take_profit=105.0)],
            {"BTCUSDT": self._candles([{"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 106, "low": 99, "close": 105}])},
            self.as_of,
            self.config,
        )
        self.assertEqual(events, [])

    def test_candles_are_evaluated_chronologically(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(stop_loss=95.0, take_profit=105.0)],
            {"BTCUSDT": [
                {"date": datetime(2026, 4, 24, 11, 5), "open": 100, "high": 106, "low": 99, "close": 105},
                {"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 101, "low": 94, "close": 95},
            ]},
            self.as_of,
            self.config,
        )
        self.assertEqual(events[0].exited_at, datetime(2026, 4, 24, 11, 0))

    def test_no_future_candles_before_entry_are_used(self) -> None:
        updated = datetime(2026, 4, 24, 11, 2)
        events = evaluate_crypto_exit_triggers(
            [self._position(stop_loss=95.0, updated_at=updated)],
            {"BTCUSDT": self._candles([
                {"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 101, "low": 94, "close": 95},
                {"date": datetime(2026, 4, 24, 11, 5), "open": 100, "high": 101, "low": 94, "close": 95},
            ])},
            self.as_of,
            self.config,
        )
        self.assertEqual(events[0].exited_at, datetime(2026, 4, 24, 11, 5))

    def test_missing_candle_fields_are_handled_cleanly(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(stop_loss=95.0)],
            {"BTCUSDT": [{"date": datetime(2026, 4, 24, 11, 0), "open": 100}]},
            self.as_of,
            self.config,
        )
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
