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

from src.execution.crypto_operational_status import (
    evaluate_crypto_operational_status,
)


class CryptoOperationalStatusTests(unittest.TestCase):
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
        self.now = datetime(2026, 5, 17, 18, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _seed_base(
        self,
        *,
        semantic_status: str = "OK",
        dashboard_status: str = "OK",
        readiness_status: str = "READY",
        dry_run_ready: bool = True,
        submit_ready: bool = False,
        next_allowed_mode: str = "order_test_only_or_dry_run",
        readiness_recent: str | None = None,
        dashboard_recent: str | None = None,
        paper_recent: str | None = None,
        telegram_severity: str = "INFO",
    ) -> None:
        recent = (self.now - timedelta(minutes=5)).isoformat()
        readiness_stamp = readiness_recent or recent
        dashboard_stamp = dashboard_recent or recent
        paper_stamp = paper_recent or recent
        self._write(
            self.paper_dir / "paper_forward" / "crypto_paper_forward_result.json",
            {
                "status": "SUCCESS",
                "warnings": [],
                "heartbeat": {"last_updated_at": paper_stamp},
            },
        )
        self._write(
            self.paper_dir / "semantic" / "crypto_semantic_summary.json",
            {
                "operational_status": semantic_status,
                "warnings": [],
                "heartbeats": {"semantic_generated_at": recent},
            },
        )
        self._write(
            self.paper_dir / "dashboard" / "dashboard_data.json",
            {
                "generated_at": dashboard_stamp,
                "operational_status": dashboard_status,
                "warnings": [],
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
            self.testnet_dir / "crypto_testnet_readiness.json",
            {
                "generated_at": readiness_stamp,
                "status": readiness_status,
                "dry_run_ready": dry_run_ready,
                "submit_ready": submit_ready,
                "next_allowed_mode": next_allowed_mode,
                "max_heartbeat_age_minutes": 30,
                "warnings": [] if readiness_status == "READY" else ["not ready"],
            },
        )
        self._write(
            self.testnet_dir / "binance_testnet_execution_result.json",
            {
                "ok": True,
                "severity": "INFO",
                "warnings": [],
            },
        )

    def test_missing_artifacts_produce_unknown_do_not_run(self) -> None:
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertEqual(result["overall_status"], "UNKNOWN")
        self.assertEqual(result["final_decision"], "DO_NOT_RUN")
        self.assertTrue(any("missing_artifact" in reason for reason in result["blocking_reasons"]))

    def test_readiness_not_ready_allows_paper_only_but_not_testnet(self) -> None:
        self._seed_base(
            readiness_status="NOT_READY",
            dry_run_ready=False,
            submit_ready=False,
            next_allowed_mode="blocked",
        )
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertEqual(result["overall_status"], "DEGRADED")
        self.assertEqual(result["final_decision"], "PAPER_ONLY")

    def test_dry_run_ready_only_allows_testnet_dry_run(self) -> None:
        self._seed_base(
            readiness_status="NOT_READY",
            dry_run_ready=True,
            submit_ready=False,
            next_allowed_mode="order_test_only_or_dry_run",
        )
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertEqual(result["overall_status"], "DEGRADED")
        self.assertEqual(result["final_decision"], "TESTNET_DRY_RUN_ALLOWED")

    def test_submit_ready_allows_controlled_submit(self) -> None:
        self._seed_base(
            readiness_status="READY",
            dry_run_ready=True,
            submit_ready=True,
            next_allowed_mode="controlled_submit",
        )
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertEqual(result["overall_status"], "OK")
        self.assertEqual(result["final_decision"], "TESTNET_SUBMIT_ALLOWED")

    def test_stale_heartbeat_blocks_testnet(self) -> None:
        stale = (self.now - timedelta(hours=2)).isoformat()
        self._seed_base(readiness_recent=stale)
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertEqual(result["overall_status"], "STALE")
        self.assertEqual(result["final_decision"], "DO_NOT_RUN")

    def test_failed_semantic_status_blocks_testnet(self) -> None:
        self._seed_base(semantic_status="ERROR")
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertEqual(result["overall_status"], "BLOCKED")
        self.assertEqual(result["final_decision"], "DO_NOT_RUN")

    def test_output_contains_no_secrets(self) -> None:
        self._seed_base()
        self._write(
            self.testnet_dir / "binance_testnet_execution_result.json",
            {
                "ok": True,
                "severity": "INFO",
                "warnings": [],
                "api_key": "secret-should-not-appear",
            },
        )
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        serialized = json.dumps(result)
        self.assertNotIn("secret-should-not-appear", serialized)
        self.assertNotIn("\"api_key\"", serialized)

    def test_markdown_summary_includes_final_decision(self) -> None:
        self._seed_base(
            readiness_status="NOT_READY",
            dry_run_ready=True,
            submit_ready=False,
            next_allowed_mode="order_test_only_or_dry_run",
        )
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        md = (self.ops_dir / "crypto_operational_status.md").read_text(encoding="utf-8")
        self.assertIn("Final decision: TESTNET_DRY_RUN_ALLOWED", md)
        self.assertEqual(
            result["artifacts"]["crypto_operational_status.md"],
            str(self.ops_dir / "crypto_operational_status.md"),
        )


if __name__ == "__main__":
    unittest.main()
