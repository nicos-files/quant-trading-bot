from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_testnet_readiness import (
    evaluate_crypto_testnet_readiness,
)


class CryptoTestnetReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.paper_dir = self.root / "crypto_paper"
        self.testnet_dir = self.root / "crypto_testnet"
        self.paper_dir.mkdir(parents=True, exist_ok=True)
        self.testnet_dir.mkdir(parents=True, exist_ok=True)
        (self.paper_dir / "paper_forward").mkdir(exist_ok=True)
        (self.paper_dir / "semantic").mkdir(exist_ok=True)
        (self.paper_dir / "dashboard").mkdir(exist_ok=True)
        self.now = datetime(2026, 5, 17, 15, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _seed_healthy(self) -> None:
        recent = (self.now - timedelta(minutes=5)).isoformat()
        self._write(
            self.paper_dir / "paper_forward" / "crypto_paper_forward_result.json",
            {
                "run_id": "20260517-1455",
                "status": "SUCCESS",
                "heartbeat": {
                    "run_id": "20260517-1455",
                    "last_updated_at": recent,
                    "run_started_at": recent,
                    "run_completed_at": recent,
                },
            },
        )
        self._write(
            self.paper_dir / "semantic" / "crypto_semantic_summary.json",
            {
                "operational_status": "OK",
                "events_count_by_severity": {"INFO": 1, "WARNING": 0, "ERROR": 0, "CRITICAL": 0},
                "stale_data_count": 0,
            },
        )
        self._write(
            self.paper_dir / "dashboard" / "dashboard_data.json",
            {
                "generated_at": recent,
                "operational_status": "OK",
            },
        )
        self._write(
            self.paper_dir / "semantic" / "telegram_notify_result.json",
            {
                "run_id": "telegram-20260517-145500",
                "ok": True,
                "severity": "INFO",
                "last_attempt_at": recent,
                "last_success_at": recent,
            },
        )
        self._write(
            self.testnet_dir / "binance_testnet_execution_result.json",
            {
                "run_id": "testnet-20260517-145500",
                "ok": True,
                "severity": "INFO",
                "category": "NO_ACTION",
                "base_url": "https://testnet.binance.vision",
                "api_key_masked": "****abcd",
                "order_test_only": True,
                "time_sync": {"checked": True, "skew_ms": 0, "warnings": []},
                "heartbeat": {
                    "run_id": "testnet-20260517-145500",
                    "last_updated_at": recent,
                    "status": "SUCCESS",
                },
            },
        )
        self._write(
            self.testnet_dir / "binance_testnet_exchange_state.json",
            {
                "checked_at": recent,
                "account_checked": True,
                "open_orders_checked": True,
                "mismatches": [],
                "mismatch_details": [],
                "reconciliation_summary": {
                    "count": 0,
                    "blocking_count": 0,
                    "highest_severity": "INFO",
                    "counts_by_severity": {"INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0},
                    "counts_by_level": {
                        "tolerable_drift": 0,
                        "warning": 0,
                        "error": 0,
                        "critical_hard_stop": 0,
                    },
                },
            },
        )
        self._write(self.testnet_dir / "binance_testnet_reconciliation.json", [])

    def test_not_ready_when_heartbeat_and_reconciliation_artifacts_missing(self) -> None:
        self._seed_healthy()
        (self.testnet_dir / "binance_testnet_exchange_state.json").unlink()
        result = evaluate_crypto_testnet_readiness(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            now=self.now,
        )
        self.assertEqual(result["status"], "NOT_READY")
        self.assertFalse(result["dry_run_ready"])
        self.assertFalse(result["submit_ready"])
        failed = {item["check_id"] for item in result["checks"] if not item["ok"]}
        self.assertIn("exchange_state_present", failed)
        self.assertIn("reconciliation_clean", failed)

    def test_not_ready_on_stale_testnet_status(self) -> None:
        self._seed_healthy()
        stale = (self.now - timedelta(hours=2)).isoformat()
        self._write(
            self.testnet_dir / "binance_testnet_execution_result.json",
            {
                "run_id": "testnet-20260517-130000",
                "ok": True,
                "severity": "INFO",
                "category": "NO_ACTION",
                "base_url": "https://testnet.binance.vision",
                "order_test_only": True,
                "heartbeat": {
                    "run_id": "testnet-20260517-130000",
                    "last_updated_at": stale,
                    "status": "SUCCESS",
                },
            },
        )
        result = evaluate_crypto_testnet_readiness(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            now=self.now,
        )
        self.assertEqual(result["status"], "NOT_READY")
        failed = {item["check_id"] for item in result["checks"] if not item["ok"]}
        self.assertIn("testnet_heartbeat_fresh", failed)

    def test_not_ready_on_reconciliation_mismatch(self) -> None:
        self._seed_healthy()
        self._write(
            self.testnet_dir / "binance_testnet_exchange_state.json",
            {
                "checked_at": (self.now - timedelta(minutes=5)).isoformat(),
                "mismatches": ["filled_order_still_open:tnbuy-abc"],
                "mismatch_details": [
                    {
                        "message": "filled_order_still_open:tnbuy-abc",
                        "severity": "CRITICAL",
                        "level": "critical_hard_stop",
                        "blocking": True,
                    }
                ],
                "reconciliation_summary": {
                    "count": 1,
                    "blocking_count": 1,
                    "highest_severity": "CRITICAL",
                    "counts_by_severity": {"INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 1},
                    "counts_by_level": {
                        "tolerable_drift": 0,
                        "warning": 0,
                        "error": 0,
                        "critical_hard_stop": 1,
                    },
                },
            },
        )
        result = evaluate_crypto_testnet_readiness(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            now=self.now,
        )
        self.assertEqual(result["status"], "NOT_READY")
        self.assertFalse(result["submit_ready"])
        failed = {item["check_id"] for item in result["checks"] if not item["ok"]}
        self.assertIn("reconciliation_clean", failed)

    def test_ready_only_when_required_operational_artifacts_are_healthy(self) -> None:
        self._seed_healthy()
        result = evaluate_crypto_testnet_readiness(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            now=self.now,
        )
        self.assertEqual(result["status"], "READY")
        self.assertTrue(result["dry_run_ready"])
        self.assertTrue(result["submit_ready"])
        self.assertEqual(result["next_allowed_mode"], "controlled_submit")
        self.assertTrue((self.testnet_dir / "crypto_testnet_readiness.json").exists())

    def test_local_dry_run_no_client_allows_dry_run_but_not_submit(self) -> None:
        self._seed_healthy()
        recent = (self.now - timedelta(minutes=5)).isoformat()
        self._write(
            self.testnet_dir / "binance_testnet_execution_result.json",
            {
                "run_id": "testnet-20260517-145500",
                "ok": True,
                "severity": "INFO",
                "category": "NO_ACTION",
                "base_url": "https://testnet.binance.vision",
                "order_test_only": True,
                "dry_run": True,
                "submit_attempted": False,
                "warnings": [
                    "server_time_unavailable:no_client",
                    "exchange_filters_unavailable:no_client",
                    "exchange_reconciliation_unavailable:no_client",
                ],
                "time_sync": {"checked": False, "warnings": ["server_time_unavailable:no_client"]},
                "heartbeat": {
                    "run_id": "testnet-20260517-145500",
                    "last_updated_at": recent,
                    "status": "SUCCESS",
                },
            },
        )
        self._write(
            self.testnet_dir / "binance_testnet_exchange_state.json",
            {
                "checked_at": recent,
                "reason": "no_client",
                "account_checked": False,
                "open_orders_checked": False,
                "mismatches": [],
                "mismatch_details": [],
                "reconciliation_summary": {
                    "count": 0,
                    "blocking_count": 0,
                    "highest_severity": "INFO",
                    "counts_by_severity": {"INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0},
                    "counts_by_level": {
                        "tolerable_drift": 0,
                        "warning": 0,
                        "error": 0,
                        "critical_hard_stop": 0,
                    },
                },
            },
        )
        result = evaluate_crypto_testnet_readiness(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            now=self.now,
        )
        self.assertEqual(result["status"], "READY")
        self.assertTrue(result["dry_run_ready"])
        self.assertFalse(result["submit_ready"])
        self.assertEqual(result["next_allowed_mode"], "order_test_only_or_dry_run")
        failed = {item["check_id"] for item in result["checks"] if not item["ok"]}
        self.assertIn("submit_requires_connected_client", failed)
        self.assertIn("submit_requires_server_time_validation", failed)
        self.assertIn("submit_requires_exchange_filters", failed)
        self.assertIn("submit_requires_exchange_reconciliation", failed)

    def test_connected_mode_without_client_blocks_readiness(self) -> None:
        self._seed_healthy()
        recent = (self.now - timedelta(minutes=5)).isoformat()
        self._write(
            self.testnet_dir / "binance_testnet_execution_result.json",
            {
                "run_id": "testnet-20260517-145500",
                "ok": True,
                "severity": "INFO",
                "category": "NO_ACTION",
                "base_url": "https://testnet.binance.vision",
                "order_test_only": True,
                "dry_run": False,
                "submit_attempted": False,
                "warnings": [
                    "server_time_unavailable:no_client",
                    "exchange_filters_unavailable:no_client",
                    "exchange_reconciliation_unavailable:no_client",
                ],
                "time_sync": {"checked": False, "warnings": ["server_time_unavailable:no_client"]},
                "heartbeat": {
                    "run_id": "testnet-20260517-145500",
                    "last_updated_at": recent,
                    "status": "SUCCESS",
                },
            },
        )
        self._write(
            self.testnet_dir / "binance_testnet_exchange_state.json",
            {
                "checked_at": recent,
                "reason": "no_client",
                "account_checked": False,
                "open_orders_checked": False,
                "mismatches": [],
                "mismatch_details": [],
                "reconciliation_summary": {
                    "count": 0,
                    "blocking_count": 0,
                    "highest_severity": "INFO",
                    "counts_by_severity": {"INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0},
                    "counts_by_level": {
                        "tolerable_drift": 0,
                        "warning": 0,
                        "error": 0,
                        "critical_hard_stop": 0,
                    },
                },
            },
        )
        result = evaluate_crypto_testnet_readiness(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            now=self.now,
        )
        self.assertEqual(result["status"], "NOT_READY")
        self.assertFalse(result["dry_run_ready"])
        self.assertFalse(result["submit_ready"])
        failed = {item["check_id"] for item in result["checks"] if not item["ok"]}
        self.assertIn("testnet_client_context_valid", failed)

    def test_readiness_output_does_not_include_secrets(self) -> None:
        self._seed_healthy()
        self._write(
            self.testnet_dir / "binance_testnet_execution_result.json",
            {
                "run_id": "testnet-20260517-145500",
                "ok": True,
                "severity": "INFO",
                "category": "NO_ACTION",
                "base_url": "https://testnet.binance.vision",
                "api_key_masked": "****abcd",
                "api_key": "should-not-leak",
                "heartbeat": {
                    "run_id": "testnet-20260517-145500",
                    "last_updated_at": (self.now - timedelta(minutes=5)).isoformat(),
                    "status": "SUCCESS",
                },
            },
        )
        result = evaluate_crypto_testnet_readiness(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            now=self.now,
        )
        serialized = json.dumps(result)
        self.assertNotIn("should-not-leak", serialized)
        self.assertNotIn("\"api_key\"", serialized)


if __name__ == "__main__":
    unittest.main()
