from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.binance_testnet_executor import ENABLE_FLAG, KILL_SWITCH_ENV, ORDER_TEST_ONLY_FLAG
from src.execution.crypto_testnet_dry_run import run_crypto_testnet_dry_run


class CryptoTestnetDryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.paper_dir = self.root / "crypto_paper"
        self.testnet_dir = self.root / "crypto_testnet"
        self.ops_dir = self.root / "crypto_ops"
        for path in (
            self.paper_dir / "paper_forward",
            self.paper_dir / "semantic",
            self.paper_dir / "dashboard",
            self.testnet_dir,
            self.ops_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 5, 17, 19, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _seed_common_artifacts(
        self,
        *,
        paper_status: str = "SUCCESS",
        semantic_status: str = "OK",
        semantic_stale_data_count: int = 0,
        dashboard_status: str = "OK",
        stale_minutes: int = 5,
        readiness_status: str = "READY",
        dry_run_ready: bool = True,
        submit_ready: bool = True,
        telegram_severity: str = "INFO",
    ) -> None:
        recent = (self.now - timedelta(minutes=stale_minutes)).isoformat()
        self._write(
            self.paper_dir / "paper_forward" / "crypto_paper_forward_result.json",
            {
                "status": paper_status,
                "heartbeat": {"last_updated_at": recent},
            },
        )
        self._write(
            self.paper_dir / "semantic" / "crypto_semantic_summary.json",
            {
                "operational_status": semantic_status,
                "events_count_by_severity": {"INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0},
                "stale_data_count": semantic_stale_data_count,
                "heartbeats": {"semantic_generated_at": recent},
            },
        )
        self._write(
            self.paper_dir / "semantic" / "crypto_semantic_events.json",
            [],
        )
        self._write(
            self.paper_dir / "dashboard" / "dashboard_data.json",
            {
                "generated_at": recent,
                "operational_status": dashboard_status,
            },
        )
        self._write(
            self.paper_dir / "semantic" / "telegram_notify_result.json",
            {
                "ok": telegram_severity == "INFO",
                "severity": telegram_severity,
                "last_attempt_at": recent,
            },
        )
        self._write(
            self.testnet_dir / "binance_testnet_execution_result.json",
            {
                "ok": True,
                "severity": "INFO",
                "category": "NO_ACTION",
                "base_url": "https://testnet.binance.vision",
                "api_key_masked": "****abcd",
                "order_test_only": True,
                "time_sync": {"checked": True, "skew_ms": 0, "warnings": []},
                "heartbeat": {"last_updated_at": recent, "status": "SUCCESS"},
            },
        )
        self._write(
            self.testnet_dir / "binance_testnet_exchange_state.json",
            {
                "account_checked": True,
                "open_orders_checked": True,
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
                "mismatches": [],
                "mismatch_details": [],
            },
        )
        self._write(self.testnet_dir / "binance_testnet_reconciliation.json", [])
        self._write(
            self.testnet_dir / "crypto_testnet_readiness.json",
            {
                "generated_at": recent,
                "status": readiness_status,
                "dry_run_ready": dry_run_ready,
                "submit_ready": submit_ready,
                "next_allowed_mode": (
                    "controlled_submit" if submit_ready else ("order_test_only_or_dry_run" if dry_run_ready else "blocked")
                ),
                "max_heartbeat_age_minutes": 30,
                "warnings": [] if readiness_status == "READY" else ["not ready"],
            },
        )

    def test_refuses_dry_run_when_operational_status_do_not_run(self) -> None:
        result = run_crypto_testnet_dry_run(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["operational_final_decision"], "DO_NOT_RUN")

    def test_refuses_dry_run_when_operational_status_paper_only(self) -> None:
        self._seed_common_artifacts()
        with mock.patch(
            "src.execution.crypto_testnet_dry_run.evaluate_crypto_testnet_readiness",
            return_value={
                "status": "NOT_READY",
                "dry_run_ready": False,
                "submit_ready": False,
                "next_allowed_mode": "blocked",
                "warnings": ["paper only"],
            },
        ), mock.patch(
            "src.execution.crypto_testnet_dry_run.evaluate_crypto_operational_status",
            return_value={
                "overall_status": "DEGRADED",
                "final_decision": "PAPER_ONLY",
                "next_allowed_mode": "blocked",
                "blocking_reasons": [],
                "warnings": ["paper only"],
            },
        ):
            result = run_crypto_testnet_dry_run(
                paper_artifacts_dir=self.paper_dir,
                testnet_artifacts_dir=self.testnet_dir,
                ops_artifacts_dir=self.ops_dir,
                now=self.now,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["operational_final_decision"], "PAPER_ONLY")
        self.assertIn("operational_status_blocked:PAPER_ONLY", result["reason"])

    def test_stale_market_data_blocks_dry_run(self) -> None:
        self._seed_common_artifacts(
            semantic_stale_data_count=1,
        )
        result = run_crypto_testnet_dry_run(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["operational_final_decision"], "DO_NOT_RUN")
        self.assertIn("operational_status_blocked:DO_NOT_RUN", result["reason"])

    def test_allows_dry_run_when_testnet_dry_run_allowed(self) -> None:
        self._seed_common_artifacts()
        captured: dict[str, Any] = {}

        def _fake_executor(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "ok": True,
                "run_id": "testnet-20260517-190000",
                "severity": "INFO",
                "category": "NO_ACTION",
                "action_taken": "notified",
                "submit_attempted": False,
                "warnings": [],
            }

        with mock.patch(
            "src.execution.crypto_testnet_dry_run.evaluate_crypto_testnet_readiness",
            return_value={
                "status": "READY",
                "dry_run_ready": True,
                "submit_ready": False,
                "next_allowed_mode": "order_test_only_or_dry_run",
                "warnings": [],
            },
        ), mock.patch(
            "src.execution.crypto_testnet_dry_run.evaluate_crypto_operational_status",
            return_value={
                "overall_status": "DEGRADED",
                "final_decision": "TESTNET_DRY_RUN_ALLOWED",
                "next_allowed_mode": "order_test_only_or_dry_run",
                "blocking_reasons": [],
                "warnings": ["Crypto strategy produced no trade candidates."],
            },
        ), mock.patch(
            "src.execution.crypto_testnet_dry_run.run_binance_testnet_execution",
            side_effect=_fake_executor,
        ):
            result = run_crypto_testnet_dry_run(
                paper_artifacts_dir=self.paper_dir,
                testnet_artifacts_dir=self.testnet_dir,
                ops_artifacts_dir=self.ops_dir,
                env={ENABLE_FLAG: "1", ORDER_TEST_ONLY_FLAG: "0"},
                now=self.now,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["operational_final_decision"], "TESTNET_DRY_RUN_ALLOWED")
        self.assertTrue(captured["dry_run"])
        self.assertEqual(captured["env"][ORDER_TEST_ONLY_FLAG], "1")

    def test_allows_when_submit_ready_but_still_does_not_submit(self) -> None:
        self._seed_common_artifacts(
            readiness_status="READY",
            dry_run_ready=True,
            submit_ready=True,
        )
        captured: dict[str, Any] = {}

        def _fake_executor(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "ok": True,
                "run_id": "testnet-20260517-190000",
                "severity": "INFO",
                "category": "NO_ACTION",
                "action_taken": "notified",
                "submit_attempted": False,
                "warnings": [],
            }

        with mock.patch(
            "src.execution.crypto_testnet_dry_run.run_binance_testnet_execution",
            side_effect=_fake_executor,
        ):
            result = run_crypto_testnet_dry_run(
                paper_artifacts_dir=self.paper_dir,
                testnet_artifacts_dir=self.testnet_dir,
                ops_artifacts_dir=self.ops_dir,
                env={ENABLE_FLAG: "1", ORDER_TEST_ONLY_FLAG: "0"},
                now=self.now,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["operational_final_decision"], "TESTNET_SUBMIT_ALLOWED")
        self.assertFalse(result["submit_attempted"])
        self.assertTrue(captured["dry_run"])
        self.assertEqual(captured["env"][ORDER_TEST_ONLY_FLAG], "1")

    def test_kill_switch_blocks_dry_run(self) -> None:
        self._seed_common_artifacts(
            readiness_status="READY",
            dry_run_ready=True,
            submit_ready=True,
        )
        result = run_crypto_testnet_dry_run(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            env={ENABLE_FLAG: "1", KILL_SWITCH_ENV: "1"},
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["executor_category"], "TESTNET_KILL_SWITCH")

    def test_missing_readiness_blocks_dry_run(self) -> None:
        self._seed_common_artifacts()
        (self.testnet_dir / "binance_testnet_execution_result.json").unlink()
        (self.testnet_dir / "binance_testnet_exchange_state.json").unlink()
        (self.testnet_dir / "binance_testnet_reconciliation.json").unlink()
        result = run_crypto_testnet_dry_run(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertIn(result["operational_final_decision"], {"DO_NOT_RUN", "PAPER_ONLY"})

    def test_output_contains_no_secrets(self) -> None:
        self._seed_common_artifacts(
            readiness_status="NOT_READY",
            dry_run_ready=True,
            submit_ready=False,
        )
        with mock.patch(
            "src.execution.crypto_testnet_dry_run.run_binance_testnet_execution",
            return_value={
                "ok": True,
                "run_id": "testnet-20260517-190000",
                "severity": "INFO",
                "category": "NO_ACTION",
                "action_taken": "notified",
                "submit_attempted": False,
                "warnings": [],
                "api_key": "secret-should-not-appear",
            },
        ):
            result = run_crypto_testnet_dry_run(
                paper_artifacts_dir=self.paper_dir,
                testnet_artifacts_dir=self.testnet_dir,
                ops_artifacts_dir=self.ops_dir,
                env={ENABLE_FLAG: "1"},
                now=self.now,
            )
        serialized = json.dumps(result)
        self.assertNotIn("secret-should-not-appear", serialized)
        self.assertNotIn("\"api_key\"", serialized)


if __name__ == "__main__":
    unittest.main()
