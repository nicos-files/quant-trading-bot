import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.reports.crypto_paper_semantics import (
    ALERTABLE_EVENT_TYPES,
    OPERATIONAL_EVENT_CATEGORIES,
    OPERATIONAL_SEVERITIES,
    PAPER_DISCLAIMER,
    SEMANTIC_EVENT_TYPES,
    SEMANTIC_SEVERITIES,
    build_semantic_layer,
)


class CryptoPaperSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.now = datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, relative_path: str, payload) -> None:
        path = self.artifacts_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _build(self, *, write: bool = True):
        return build_semantic_layer(
            artifacts_dir=self.artifacts_dir,
            output_dir=self.artifacts_dir / "semantic",
            write=write,
            now=self.now,
        )

    def _types(self, events) -> list[str]:
        return [event["event_type"] for event in events]

    def test_no_artifacts_produces_summary_with_warning_no_crash(self) -> None:
        result = self._build()
        self.assertIn("no_paper_artifacts_found", " ".join(result["warnings"]))
        self.assertIn("NO_ACTION", self._types(result["events"]))
        self.assertIsInstance(result["summary"], dict)
        self.assertTrue(result["summary"]["paper_only"])
        self.assertFalse(result["summary"]["live_trading"])

    def test_open_position_emits_position_open(self) -> None:
        position = {
            "symbol": "BTCUSDT",
            "quantity": 0.001,
            "avg_entry_price": 76286.0,
            "last_price": 76500.0,
            "unrealized_pnl": 0.5,
            "updated_at": "2026-05-03T17:00:00",
            "metadata": {"stop_loss": 74840.0, "take_profit": 77131.0},
        }
        self._write("crypto_paper_positions.json", [position])
        self._write("crypto_paper_snapshot.json", {"equity": 100.0, "positions": [position]})

        result = self._build()
        types = self._types(result["events"])
        self.assertIn("POSITION_OPEN", types)
        position_event = next(e for e in result["events"] if e["event_type"] == "POSITION_OPEN")
        self.assertEqual(position_event["symbol"], "BTCUSDT")
        self.assertEqual(position_event["severity"], "INFO")
        self.assertTrue(position_event["paper_only"])
        self.assertTrue(position_event["not_auto_executed"])
        self.assertIn(PAPER_DISCLAIMER, position_event["human_message"])

    def test_buy_fill_emits_buy_filled_paper(self) -> None:
        fill = {
            "fill_id": "crypto-paper-fill-20260503T170000-0001",
            "order_id": "crypto-paper-order-20260503T170000-0001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 0.0003,
            "fill_price": 76026.5,
            "gross_notional": 25.0,
            "fee": 0.025,
            "filled_at": "2026-05-03T17:00:00",
            "metadata": {"stop_loss": 74468.7, "take_profit": 76748.4},
        }
        self._write("crypto_paper_fills.json", [fill])

        result = self._build()
        events = [e for e in result["events"] if e["event_type"] == "BUY_FILLED_PAPER"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "ACTION")
        self.assertEqual(events[0]["symbol"], "BTCUSDT")
        self.assertIn("Paper BUY filled", events[0]["human_title"])
        self.assertIn("BUY_FILLED_PAPER", ALERTABLE_EVENT_TYPES)

    def test_take_profit_exit_emits_take_profit_event(self) -> None:
        exit_event = {
            "exit_id": "crypto-exit-BTCUSDT-20260503T174500-0001",
            "symbol": "BTCUSDT",
            "exit_reason": "TAKE_PROFIT",
            "exit_quantity": 0.001,
            "trigger_price": 77131.478,
            "fill_price": 77092.91,
            "realized_pnl": 0.717,
            "fee": 0.075,
            "exited_at": "2026-05-03T17:45:00",
            "source": "stop_take_quote_fallback",
            "metadata": {"stop_loss": 74840.0, "take_profit": 77131.478},
        }
        self._write("crypto_paper_exit_events.json", [exit_event])

        result = self._build()
        events = [e for e in result["events"] if e["event_type"] == "TAKE_PROFIT"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "ACTION")
        self.assertEqual(events[0]["symbol"], "BTCUSDT")
        self.assertEqual(events[0]["metadata"]["realized_pnl"], 0.717)

    def test_stop_loss_exit_emits_stop_loss_event(self) -> None:
        exit_event = {
            "exit_id": "crypto-exit-BTCUSDT-20260503T174500-0001",
            "symbol": "BTCUSDT",
            "exit_reason": "STOP_LOSS",
            "exit_quantity": 0.001,
            "trigger_price": 74840.444,
            "fill_price": 74800.0,
            "realized_pnl": -1.5,
            "fee": 0.075,
            "exited_at": "2026-05-03T17:45:00",
            "source": "stop_take_quote_fallback",
            "metadata": {"stop_loss": 74840.444, "take_profit": 77131.478},
        }
        self._write("crypto_paper_exit_events.json", [exit_event])

        result = self._build()
        events = [e for e in result["events"] if e["event_type"] == "STOP_LOSS"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "ACTION")

    def test_rejected_order_emits_order_rejected(self) -> None:
        order = {
            "order_id": "crypto-paper-order-20260430T230009-0001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "status": "REJECTED",
            "reason": "risk:cash_insufficient",
            "reference_price": 76323.24,
            "requested_notional": 25.0,
            "created_at": "2026-04-30T23:00:09",
            "metadata": {"stop_loss": 74796.7, "take_profit": 77086.4},
        }
        self._write("crypto_paper_orders.json", [order])

        result = self._build()
        events = [e for e in result["events"] if e["event_type"] == "ORDER_REJECTED"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "WARNING")
        self.assertIn("risk:cash_insufficient", events[0]["human_message"])

    def test_metric_warnings_propagate_to_summary(self) -> None:
        self._write(
            "evaluation/crypto_paper_strategy_metrics.json",
            {
                "closed_trades_count": 3,
                "win_rate": 1.0,
                "warnings": ["Small sample size: fewer than 30 closed trades."],
            },
        )
        result = self._build()
        joined = " ".join(result["summary"]["warnings"])
        self.assertIn("Small sample size", joined)
        self.assertIn("small_sample_size:closed_trades=3_below_min_30", " ".join(result["summary"]["warnings"]))
        self.assertIn("WARNING", self._types(result["events"]))

    def test_small_future_quote_skew_stays_warning(self) -> None:
        self._write(
            "paper_forward/crypto_paper_forward_result.json",
            {
                "status": "SUCCESS",
                "warnings": ["quote_invalid:timestamp_in_future:-4.696s:BTCUSDT"],
            },
        )
        result = self._build()
        event = next(
            e for e in result["events"]
            if e.get("failure_reason") == "quote_invalid:timestamp_in_future:-4.696s:BTCUSDT"
        )
        self.assertEqual(event["severity"], "WARNING")
        self.assertEqual(result["summary"]["operational_status"], "DEGRADED")
        self.assertEqual(result["summary"]["events_count_by_severity"]["ERROR"], 0)

    def test_large_future_quote_skew_remains_error(self) -> None:
        self._write(
            "paper_forward/crypto_paper_forward_result.json",
            {
                "status": "SUCCESS",
                "warnings": ["quote_invalid:timestamp_in_future:-30.000s:BTCUSDT"],
            },
        )
        result = self._build()
        event = next(
            e for e in result["events"]
            if e.get("failure_reason") == "quote_invalid:timestamp_in_future:-30.000s:BTCUSDT"
        )
        self.assertEqual(event["severity"], "ERROR")
        self.assertEqual(result["summary"]["operational_status"], "ERROR")
        self.assertEqual(result["summary"]["events_count_by_severity"]["ERROR"], 1)

    def test_summary_is_json_serializable(self) -> None:
        position = {
            "symbol": "BTCUSDT",
            "quantity": 0.001,
            "avg_entry_price": 100.0,
            "last_price": 110.0,
            "unrealized_pnl": 0.01,
            "updated_at": "2026-05-03T17:00:00",
            "metadata": {"stop_loss": 95.0, "take_profit": 115.0},
        }
        self._write("crypto_paper_positions.json", [position])
        self._write("crypto_paper_snapshot.json", {"equity": 100.0, "positions": [position]})
        self._write("history/crypto_paper_equity_curve.json", [{"equity": 100.0}])

        result = self._build()
        encoded = json.dumps(result["summary"])
        decoded = json.loads(encoded)
        self.assertEqual(decoded["paper_only"], True)
        self.assertEqual(decoded["live_trading"], False)

    def test_latest_action_markdown_is_generated_and_written(self) -> None:
        position = {
            "symbol": "BTCUSDT",
            "quantity": 0.001,
            "avg_entry_price": 100.0,
            "last_price": 110.0,
            "unrealized_pnl": 0.01,
            "updated_at": "2026-05-03T17:00:00",
            "metadata": {"stop_loss": 95.0, "take_profit": 115.0},
        }
        self._write("crypto_paper_positions.json", [position])
        self._write("crypto_paper_snapshot.json", {"equity": 100.0, "positions": [position]})

        result = self._build()
        md = result["latest_action_md"]
        self.assertIn("# Crypto Paper Latest Action", md)
        self.assertIn(PAPER_DISCLAIMER, md)
        self.assertIn("## Snapshot", md)
        self.assertIn("## Performance", md)
        self.assertIn("## Latest event", md)

        latest_path = self.artifacts_dir / "semantic" / "crypto_latest_action.md"
        summary_path = self.artifacts_dir / "semantic" / "crypto_semantic_summary.json"
        events_path = self.artifacts_dir / "semantic" / "crypto_semantic_events.json"
        self.assertTrue(latest_path.exists())
        self.assertTrue(summary_path.exists())
        self.assertTrue(events_path.exists())
        events_payload = json.loads(events_path.read_text(encoding="utf-8"))
        self.assertIsInstance(events_payload, list)

    def test_no_action_emitted_only_when_nothing_actionable(self) -> None:
        result = self._build()
        no_action_events = [e for e in result["events"] if e["event_type"] == "NO_ACTION"]
        self.assertEqual(len(no_action_events), 1)
        self.assertNotIn("NO_ACTION", ALERTABLE_EVENT_TYPES)

        # When a position exists, NO_ACTION must not be emitted.
        position = {
            "symbol": "BTCUSDT",
            "quantity": 0.001,
            "avg_entry_price": 100.0,
            "last_price": 110.0,
            "unrealized_pnl": 0.01,
            "updated_at": "2026-05-03T17:00:00",
            "metadata": {},
        }
        self._write("crypto_paper_positions.json", [position])
        result = self._build()
        no_action_events = [e for e in result["events"] if e["event_type"] == "NO_ACTION"]
        self.assertEqual(no_action_events, [])

    def test_event_types_and_severities_constants(self) -> None:
        for needed in (
            "BUY_SIGNAL",
            "BUY_FILLED_PAPER",
            "TAKE_PROFIT",
            "STOP_LOSS",
            "POSITION_OPEN",
            "ORDER_REJECTED",
            "DAILY_SUMMARY",
            "WARNING",
            "ERROR",
            "NO_ACTION",
        ):
            self.assertIn(needed, SEMANTIC_EVENT_TYPES)
        for severity in ("INFO", "ACTION", "WARNING", "ERROR", "CRITICAL"):
            self.assertIn(severity, SEMANTIC_SEVERITIES)
        for severity in ("INFO", "WARNING", "ERROR", "CRITICAL"):
            self.assertIn(severity, OPERATIONAL_SEVERITIES)
        for category in (
            "DATA_STALE",
            "LEDGER_CORRUPT",
            "EXCHANGE_FILTER_REJECT",
            "TESTNET_KILL_SWITCH",
            "NO_ACTION",
        ):
            self.assertIn(category, OPERATIONAL_EVENT_CATEGORIES)

    def test_does_not_invent_pnl_when_no_artifacts_present(self) -> None:
        result = self._build()
        snapshot = result["summary"]["snapshot"]
        performance = result["summary"]["performance"]
        self.assertIsNone(snapshot["equity"])
        self.assertIsNone(snapshot["realized_pnl"])
        self.assertIsNone(performance["net_profit"])
        self.assertIsNone(performance["win_rate"])

    def test_summary_includes_operational_counts(self) -> None:
        self._write(
            "paper_forward/crypto_paper_forward_result.json",
            {
                "status": "SUCCESS",
                "warnings": ["quote_stale:BTCUSDT", "risk:cash_insufficient"],
            },
        )
        result = self._build()
        summary = result["summary"]
        self.assertIn("events_count_by_severity", summary)
        self.assertIn("events_count_by_category", summary)
        self.assertEqual(summary["stale_data_count"], 1)
        self.assertEqual(summary["risk_block_count"], 1)
        self.assertEqual(summary["operational_status"], "DEGRADED")

    def test_testnet_blocked_artifact_emits_semantic_error_event(self) -> None:
        testnet_dir = self.artifacts_dir.parent / "crypto_testnet"
        testnet_dir.mkdir(parents=True, exist_ok=True)
        (testnet_dir / "binance_testnet_execution_result.json").write_text(
            json.dumps(
                {
                    "ok": False,
                    "run_id": "testnet-20260505-233000",
                    "testnet": True,
                    "live_trading": False,
                    "environment": "binance_spot_testnet",
                    "severity": "CRITICAL",
                    "category": "TESTNET_KILL_SWITCH",
                    "reason": "kill switch enabled via env",
                    "failure_reason": "kill switch enabled via env",
                    "action_taken": "blocked",
                    "submit_attempted": False,
                }
            ),
            encoding="utf-8",
        )
        result = self._build()
        testnet_events = [
            event
            for event in result["events"]
            if event.get("category") == "TESTNET_KILL_SWITCH"
        ]
        self.assertEqual(len(testnet_events), 1)
        self.assertEqual(testnet_events[0]["event_type"], "ERROR")
        self.assertEqual(testnet_events[0]["mode"], "TESTNET")
        self.assertEqual(testnet_events[0]["run_id"], "testnet-20260505-233000")
        self.assertFalse(testnet_events[0]["paper_only"])
        self.assertEqual(
            result["summary"]["heartbeats"]["testnet_run_id"],
            "testnet-20260505-233000",
        )

    def test_historical_testnet_rejections_do_not_pollute_current_semantic_status(self) -> None:
        testnet_dir = self.artifacts_dir.parent / "crypto_testnet"
        testnet_dir.mkdir(parents=True, exist_ok=True)
        (testnet_dir / "binance_testnet_execution_result.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "run_id": "testnet-20260505-233000",
                    "testnet": True,
                    "live_trading": False,
                    "environment": "binance_spot_testnet",
                    "severity": "INFO",
                    "category": "NO_ACTION",
                    "action_taken": "notified",
                    "submit_attempted": False,
                    "heartbeat": {
                        "run_id": "testnet-20260505-233000",
                        "run_started_at": "2026-05-05T23:30:00+00:00",
                        "run_completed_at": "2026-05-05T23:30:01+00:00",
                        "last_updated_at": "2026-05-05T23:30:01+00:00",
                        "status": "SUCCESS",
                    },
                }
            ),
            encoding="utf-8",
        )
        (testnet_dir / "binance_testnet_orders.json").write_text(
            json.dumps(
                [
                    {
                        "client_order_id": "old-reject-1",
                        "symbol": "BTCUSDT",
                        "status": "REJECTED",
                        "reason": "notional_exceeds_max:25.00>10.00",
                        "created_at": "2026-05-05T20:00:00+00:00",
                        "metadata": {
                            "category": "EXCHANGE_FILTER_REJECT",
                            "severity": "ERROR",
                            "failure_reason": "notional_exceeds_max:25.00>10.00",
                            "action_taken": "testnet_submit_blocked",
                            "submit_attempted": False,
                            "environment": "binance_spot_testnet",
                        },
                    }
                ]
            ),
            encoding="utf-8",
        )
        result = self._build()
        self.assertEqual(result["summary"]["events_count_by_severity"]["ERROR"], 0)
        self.assertIsNone(result["summary"]["latest_critical_event"])
        reject_events = [
            event for event in result["events"]
            if event.get("category") == "EXCHANGE_FILTER_REJECT"
        ]
        self.assertEqual(reject_events, [])

    def test_notify_failure_artifact_emits_semantic_event_and_heartbeat(self) -> None:
        semantic_dir = self.artifacts_dir / "semantic"
        semantic_dir.mkdir(parents=True, exist_ok=True)
        (semantic_dir / "telegram_notify_result.json").write_text(
            json.dumps(
                {
                    "ok": False,
                    "run_id": "telegram-20260503-180000",
                    "paper_only": True,
                    "live_trading": False,
                    "category": "TELEGRAM_NOTIFY_FAILED",
                    "severity": "ERROR",
                    "failure_reason": "send_failed:non_ok_response",
                    "action_taken": "failed_closed",
                    "environment": "crypto_paper_telegram",
                    "last_attempt_at": "2026-05-03T18:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        result = self._build()
        notify_events = [
            event
            for event in result["events"]
            if event.get("category") == "TELEGRAM_NOTIFY_FAILED"
        ]
        self.assertEqual(len(notify_events), 1)
        self.assertEqual(notify_events[0]["run_id"], "telegram-20260503-180000")
        self.assertEqual(result["summary"]["telegram_status"], "ERROR")
        self.assertEqual(
            result["summary"]["heartbeats"]["telegram_last_attempt_at"],
            "2026-05-03T18:00:00+00:00",
        )
        self.assertEqual(
            result["summary"]["heartbeats"]["telegram_run_id"],
            "telegram-20260503-180000",
        )


class CryptoPaperSemanticsExitEnrichmentTests(unittest.TestCase):
    """Verify exit events expose entry_average_price, return_pct, quote_asset."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.now = datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, relative_path: str, payload) -> None:
        path = self.artifacts_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_take_profit_metadata_includes_entry_avg_and_return_pct(self) -> None:
        # Three BUY fills at different prices, then a TAKE_PROFIT exit. The
        # weighted-average entry is the qty-weighted mean of the three fills.
        self._write(
            "crypto_paper_fills.json",
            [
                {
                    "fill_id": "f1",
                    "order_id": "o1",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 1.0,
                    "fill_price": 76000.0,
                    "gross_notional": 76000.0,
                    "fee": 0.0,
                    "filled_at": "2026-05-01T10:00:00",
                    "metadata": {},
                },
                {
                    "fill_id": "f2",
                    "order_id": "o2",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 2.0,
                    "fill_price": 76600.0,
                    "gross_notional": 153200.0,
                    "fee": 0.0,
                    "filled_at": "2026-05-02T10:00:00",
                    "metadata": {},
                },
                # A future BUY fill that must be ignored when computing the
                # exit's entry average.
                {
                    "fill_id": "f3-future",
                    "order_id": "o3",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 1.0,
                    "fill_price": 90000.0,
                    "gross_notional": 90000.0,
                    "fee": 0.0,
                    "filled_at": "2026-05-04T10:00:00",
                    "metadata": {},
                },
            ],
        )
        self._write(
            "crypto_paper_exit_events.json",
            [
                {
                    "exit_id": "e1",
                    "symbol": "BTCUSDT",
                    "exit_reason": "TAKE_PROFIT",
                    "exit_quantity": 3.0,
                    "trigger_price": 77131.478,
                    "fill_price": 77092.91,
                    "realized_pnl": 1078.94,
                    "fee": 0.5,
                    "exited_at": "2026-05-03T17:45:00",
                    "metadata": {"stop_loss": 74840.0, "take_profit": 77131.478},
                }
            ],
        )
        result = build_semantic_layer(
            artifacts_dir=self.artifacts_dir,
            output_dir=self.artifacts_dir / "semantic",
            write=False,
            now=self.now,
        )
        events = [e for e in result["events"] if e["event_type"] == "TAKE_PROFIT"]
        self.assertEqual(len(events), 1)
        meta = events[0]["metadata"]
        # qty-weighted: (1*76000 + 2*76600) / 3 == 76400
        self.assertAlmostEqual(meta["entry_average_price"], 76400.0, places=2)
        self.assertAlmostEqual(
            meta["return_pct"], (77092.91 - 76400.0) / 76400.0, places=6
        )
        self.assertEqual(meta["quote_asset"], "USDT")

    def test_exit_without_prior_fills_keeps_entry_none(self) -> None:
        # No BUY fills before the exit -> entry_average_price must be None.
        self._write(
            "crypto_paper_fills.json",
            [
                {
                    "fill_id": "f1",
                    "order_id": "o1",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 1.0,
                    "fill_price": 76000.0,
                    "gross_notional": 76000.0,
                    "fee": 0.0,
                    "filled_at": "2026-05-04T10:00:00",
                    "metadata": {},
                },
            ],
        )
        self._write(
            "crypto_paper_exit_events.json",
            [
                {
                    "exit_id": "e1",
                    "symbol": "BTCUSDT",
                    "exit_reason": "STOP_LOSS",
                    "exit_quantity": 1.0,
                    "trigger_price": 70000.0,
                    "fill_price": 69500.0,
                    "realized_pnl": -1500.0,
                    "fee": 0.5,
                    "exited_at": "2026-05-03T17:45:00",
                    "metadata": {},
                }
            ],
        )
        result = build_semantic_layer(
            artifacts_dir=self.artifacts_dir,
            output_dir=self.artifacts_dir / "semantic",
            write=False,
            now=self.now,
        )
        events = [e for e in result["events"] if e["event_type"] == "STOP_LOSS"]
        self.assertEqual(len(events), 1)
        meta = events[0]["metadata"]
        self.assertIsNone(meta["entry_average_price"])
        self.assertIsNone(meta["return_pct"])

    def test_buy_filled_metadata_includes_quote_asset(self) -> None:
        self._write(
            "crypto_paper_fills.json",
            [
                {
                    "fill_id": "f1",
                    "order_id": "o1",
                    "symbol": "ETHUSDT",
                    "side": "BUY",
                    "quantity": 0.01,
                    "fill_price": 3000.0,
                    "gross_notional": 30.0,
                    "fee": 0.0,
                    "filled_at": "2026-05-01T10:00:00",
                    "metadata": {},
                }
            ],
        )
        result = build_semantic_layer(
            artifacts_dir=self.artifacts_dir,
            output_dir=self.artifacts_dir / "semantic",
            write=False,
            now=self.now,
        )
        events = [e for e in result["events"] if e["event_type"] == "BUY_FILLED_PAPER"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["metadata"]["quote_asset"], "USDT")


class CryptoPaperSemanticsSignalOnlyTests(unittest.TestCase):
    """SIGNAL_ONLY is emitted for BUY orders without a matching fill."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.now = datetime(2026, 5, 5, 18, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, relative: str, payload) -> None:
        path = self.artifacts_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _build(self):
        return build_semantic_layer(
            artifacts_dir=self.artifacts_dir,
            output_dir=self.artifacts_dir / "semantic",
            write=False,
            now=self.now,
        )

    def test_recommendations_count_one_with_fills_count_zero_emits_signal_only(self) -> None:
        # Mirror the bug report: a BUY order exists (recommendation reached
        # the order layer) but execution did not produce a fill.
        order = {
            "order_id": "crypto-paper-order-20260505T123007-0001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "status": "REJECTED",
            "reason": "risk:cash_insufficient",
            "reference_price": 81482.11,
            "requested_notional": 25.0,
            "created_at": "2026-05-05T12:30:07",
            "metadata": {"stop_loss": 79812.56, "take_profit": 82255.80},
        }
        self._write("crypto_paper_orders.json", [order])
        self._write(
            "paper_forward/crypto_paper_forward_result.json",
            {
                "recommendations_count": 1,
                "fills_count": 0,
                "exits_count": 0,
                "status": "SUCCESS",
            },
        )

        result = self._build()
        signals = [
            event for event in result["events"] if event["event_type"] == "SIGNAL_ONLY"
        ]
        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal["symbol"], "BTCUSDT")
        self.assertEqual(signal["action"], "REVIEW_SIGNAL")
        self.assertEqual(signal["severity"], "INFO")
        self.assertTrue(signal["paper_only"])
        self.assertTrue(signal["not_auto_executed"])
        self.assertEqual(signal["metadata"]["reference_price"], 81482.11)
        self.assertEqual(signal["metadata"]["requested_notional"], 25.0)
        self.assertEqual(signal["metadata"]["stop_loss"], 79812.56)
        self.assertEqual(signal["metadata"]["take_profit"], 82255.80)
        self.assertEqual(signal["metadata"]["rejection_reason"], "risk:cash_insufficient")
        self.assertEqual(signal["metadata"]["recommendations_count"], 1)
        self.assertEqual(signal["metadata"]["fills_count"], 0)
        # Stable, dedupe-friendly id derived from order_id + created_at.
        self.assertTrue(
            signal["event_id"].startswith(
                "signal_only:crypto-paper-order-20260505T123007-0001:"
            )
        )

    def test_buy_order_with_matching_fill_does_not_emit_signal_only(self) -> None:
        order = {
            "order_id": "o1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "status": "PENDING",
            "reason": None,
            "reference_price": 76000.0,
            "requested_notional": 25.0,
            "created_at": "2026-05-05T12:30:07",
            "metadata": {},
        }
        fill = {
            "fill_id": "f1",
            "order_id": "o1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 0.0003,
            "fill_price": 76000.0,
            "gross_notional": 25.0,
            "fee": 0.025,
            "filled_at": "2026-05-05T12:30:07",
            "metadata": {},
        }
        self._write("crypto_paper_orders.json", [order])
        self._write("crypto_paper_fills.json", [fill])

        result = self._build()
        signals = [
            event for event in result["events"] if event["event_type"] == "SIGNAL_ONLY"
        ]
        self.assertEqual(signals, [])
        # The BUY_FILLED_PAPER path is the one that surfaces the executed entry.
        self.assertTrue(
            any(e["event_type"] == "BUY_FILLED_PAPER" for e in result["events"])
        )

    def test_signal_only_is_in_event_types_constant(self) -> None:
        self.assertIn("SIGNAL_ONLY", SEMANTIC_EVENT_TYPES)

    def test_signal_only_is_not_in_default_alertable_set(self) -> None:
        # Off by default; the notifier opts in via --include-signal-only.
        self.assertNotIn("SIGNAL_ONLY", ALERTABLE_EVENT_TYPES)

    def test_summary_signal_only_count_reflects_emitted_events(self) -> None:
        rejected = {
            "order_id": "rej-1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "status": "REJECTED",
            "reason": "risk:cash_insufficient",
            "reference_price": 80000.0,
            "requested_notional": 25.0,
            "created_at": "2026-05-05T12:30:07",
            "metadata": {},
        }
        pending_no_fill = {
            "order_id": "pend-1",
            "symbol": "ETHUSDT",
            "side": "BUY",
            "status": "PENDING",
            "reason": None,
            "reference_price": 3000.0,
            "requested_notional": 25.0,
            "created_at": "2026-05-05T12:35:07",
            "metadata": {},
        }
        self._write("crypto_paper_orders.json", [rejected, pending_no_fill])
        result = self._build()
        self.assertEqual(result["summary"]["signal_only_count"], 2)


class CryptoPaperSemanticsLocalTzTests(unittest.TestCase):
    """Local timezone enrichment without changing UTC archive ids."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.now = datetime(2026, 5, 5, 23, 30, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, relative: str, payload) -> None:
        path = self.artifacts_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_local_display_for_iso_returns_argentina_time(self) -> None:
        from src.reports.crypto_paper_semantics import (
            DEFAULT_CRYPTO_LOCAL_TZ,
            local_display_for_iso,
            local_tz_label,
        )

        # 23:30 UTC -> 20:30 ART.
        local = local_display_for_iso(
            "2026-05-05T23:30:00+00:00", tz_name=DEFAULT_CRYPTO_LOCAL_TZ
        )
        self.assertIsNotNone(local)
        assert local is not None  # mypy / type-narrow.
        self.assertEqual(local["time_local"], "20:30")
        self.assertEqual(local["time_utc"], "23:30")
        self.assertEqual(local["tz_label"], "ART")
        self.assertEqual(local_tz_label(DEFAULT_CRYPTO_LOCAL_TZ), "ART")

    def test_summary_includes_local_tz_and_generated_at_local(self) -> None:
        result = build_semantic_layer(
            artifacts_dir=self.artifacts_dir,
            output_dir=self.artifacts_dir / "semantic",
            write=False,
            now=self.now,
        )
        summary = result["summary"]
        self.assertEqual(summary["local_tz"], "America/Argentina/Buenos_Aires")
        self.assertIsInstance(summary["generated_at_local"], dict)
        self.assertEqual(summary["generated_at_local"]["time_local"], "20:30")
        self.assertEqual(summary["generated_at_local"]["tz_label"], "ART")

    def test_archive_compatible_utc_iso_is_not_mutated(self) -> None:
        # The semantic layer writes ``created_at`` as UTC ISO. The local-tz
        # enrichment must NOT replace it (archive folders depend on UTC).
        result = build_semantic_layer(
            artifacts_dir=self.artifacts_dir,
            output_dir=self.artifacts_dir / "semantic",
            write=False,
            now=self.now,
        )
        for event in result["events"]:
            self.assertTrue(str(event["created_at"]).endswith("+00:00"))


if __name__ == "__main__":
    unittest.main()
