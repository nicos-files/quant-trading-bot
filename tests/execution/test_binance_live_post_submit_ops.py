from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.binance_live_cancel_open_orders import run_binance_live_cancel_open_orders
from src.execution.binance_live_daily_close import generate_binance_live_daily_close
from src.execution.binance_live_incident_report import generate_binance_live_incident_report
from src.execution.binance_live_soak_status import evaluate_binance_live_soak_status
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


class _ReadonlyClient:
    def __init__(self, orders: list[dict[str, Any]]) -> None:
        self.orders = [dict(item) for item in orders]
        self.open_orders_calls = 0

    def open_orders(self) -> list[dict[str, Any]]:
        self.open_orders_calls += 1
        return [dict(item) for item in self.orders]


class BinanceLivePostSubmitOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / ARTIFACTS_SUBDIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, relative: str, payload: object) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _write_readonly(self, *, open_orders: list[dict[str, Any]] | None = None) -> None:
        self._write(
            "binance_mainnet_readonly_preflight.json",
            {
                "ok": True,
                "status": "SUCCESS",
                "base_url": "https://api.binance.com",
                "balances": {
                    "USDT": {"free": "1000.0", "locked": "0.0"},
                    "BTC": {"free": "0.10000000", "locked": "0.0"},
                },
                "open_orders": list(open_orders or []),
                "reconciliation_summary": {"count": 0, "blocking_count": 0, "highest_severity": "INFO"},
                "warnings": [],
                "heartbeat": {"last_updated_at": self.now.isoformat()},
            },
        )

    def _write_live_result(self, **overrides: Any) -> None:
        payload = {
            "status": "SUCCESS",
            "submit_attempted": True,
            "exchange_order_request_sent": True,
            "placed_count": 1,
            "rejected_count": 0,
            "requested_notional": 5.0,
            "daily_cap_consumed": True,
            "daily_cap_reason": "placed_count=1",
            "reconciliation_summary": {"count": 0, "blocking_count": 0, "highest_severity": "INFO"},
            "post_open_orders_count": 0,
            "warnings": [],
            "blocking_reasons": [],
            "heartbeat": {"last_updated_at": self.now.isoformat()},
        }
        payload.update(overrides)
        self._write("binance_live_micro_submit_result.json", payload)

    def test_cancel_prepare_only_lists_open_orders_without_mutation(self) -> None:
        client = _ReadonlyClient(
            [
                {"symbol": "BTCUSDT", "orderId": 123, "side": "SELL", "status": "NEW", "type": "LIMIT", "origQty": "0.001", "executedQty": "0.0"}
            ]
        )
        result = run_binance_live_cancel_open_orders(artifacts_dir=self.root, client=client, now=self.now)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "PREPARED")
        self.assertEqual(result["open_orders_count"], 1)
        self.assertEqual(len(result["cancel_candidates"]), 1)
        self.assertFalse(result["cancel_attempted"])
        self.assertEqual(client.open_orders_calls, 1)

    def test_cancel_execute_blocks_without_confirm(self) -> None:
        client = _ReadonlyClient([{"symbol": "BTCUSDT", "orderId": 123, "status": "NEW"}])
        result = run_binance_live_cancel_open_orders(
            artifacts_dir=self.root,
            client=client,
            env={"BINANCE_LIVE_KILL_SWITCH": "0", "BINANCE_LIVE_BASE_URL": "https://api.binance.com"},
            now=self.now,
            prepare_only=False,
            execute=True,
        )
        self.assertFalse(result["ok"])
        self.assertIn("live_cancel_confirm_yes_required", result["blocking_reasons"])

    def test_cancel_execute_blocks_ambiguous_orders(self) -> None:
        client = _ReadonlyClient([{"symbol": "BTCUSDT", "status": "NEW"}])
        result = run_binance_live_cancel_open_orders(
            artifacts_dir=self.root,
            client=client,
            env={
                "BINANCE_LIVE_CANCEL_CONFIRM": "YES",
                "BINANCE_LIVE_KILL_SWITCH": "0",
                "BINANCE_LIVE_BASE_URL": "https://api.binance.com",
            },
            now=self.now,
            prepare_only=False,
            execute=True,
        )
        self.assertFalse(result["ok"])
        self.assertIn("live_cancel_open_orders_ambiguous", result["blocking_reasons"])

    def test_incident_report_redacts_and_recommends_halted_on_error(self) -> None:
        self._write_readonly()
        self._write_live_result(
            status="ERROR",
            blocking_reasons=["live_submit_failed:boom"],
            warnings=["safe_warning"],
            api_key_masked="****abcd",
        )
        self._write("binance_live_readiness.json", {"blocking_reasons": [], "warnings": []})
        self._write("binance_live_operations_status.json", {"blocking_reasons": [], "warnings": []})
        result = generate_binance_live_incident_report(artifacts_dir=self.root, now=self.now)
        self.assertEqual(result["severity"], "CRITICAL")
        self.assertIn("HALTED", result["recommended_action"])
        serialized = json.dumps(result)
        self.assertNotIn("secret", serialized.lower())
        self.assertTrue((self.root / "binance_live_incident_report.md").exists())

    def test_daily_close_pass_with_clean_reconciliation(self) -> None:
        self._write_readonly(open_orders=[])
        self._write("binance_live_operations_status.json", {"live_mode": "SINGLE_SHOT"})
        self._write_live_result()
        result = generate_binance_live_daily_close(artifacts_dir=self.root, now=self.now)
        self.assertEqual(result["soak_day_status"], "PASS")
        self.assertEqual(result["next_recommended_mode"], "OFF")

    def test_daily_close_fail_with_reconciliation_mismatch(self) -> None:
        self._write_readonly(open_orders=[])
        self._write("binance_live_operations_status.json", {"live_mode": "SINGLE_SHOT"})
        self._write_live_result(reconciliation_summary={"count": 1, "blocking_count": 1, "highest_severity": "ERROR"})
        result = generate_binance_live_daily_close(artifacts_dir=self.root, now=self.now)
        self.assertEqual(result["soak_day_status"], "FAIL")
        self.assertIn("reconciliation_not_clean", result["soak_blockers"])

    def test_soak_incomplete_without_enough_days(self) -> None:
        self._write(
            "daily_close/binance_live_daily_close_20260702.json",
            {"date_utc": "20260702", "soak_day_status": "PASS"},
        )
        result = evaluate_binance_live_soak_status(artifacts_dir=self.root, now=self.now)
        self.assertEqual(result["soak_status"], "INCOMPLETE")
        self.assertIn("insufficient_soak_days:1<3", result["blockers"])

    def test_soak_pass_with_three_clean_days(self) -> None:
        for offset in range(3):
            date = (self.now - timedelta(days=offset)).strftime("%Y%m%d")
            self._write(
                f"daily_close/binance_live_daily_close_{date}.json",
                {"date_utc": date, "soak_day_status": "PASS"},
            )
        result = evaluate_binance_live_soak_status(artifacts_dir=self.root, now=self.now)
        self.assertEqual(result["soak_status"], "PASSED")
        self.assertEqual(result["days_passed"], 3)

    def test_soak_fail_when_one_day_failed(self) -> None:
        self._write("daily_close/binance_live_daily_close_20260702.json", {"date_utc": "20260702", "soak_day_status": "FAIL"})
        self._write("daily_close/binance_live_daily_close_20260701.json", {"date_utc": "20260701", "soak_day_status": "PASS"})
        self._write("daily_close/binance_live_daily_close_20260630.json", {"date_utc": "20260630", "soak_day_status": "PASS"})
        result = evaluate_binance_live_soak_status(artifacts_dir=self.root, now=self.now)
        self.assertEqual(result["soak_status"], "FAILED")
        self.assertIn("soak_day_failed:20260702", result["blockers"])
