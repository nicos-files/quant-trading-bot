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
        forward_warnings: list[str] | None = None,
        semantic_warnings: list[str] | None = None,
        dashboard_warnings: list[str] | None = None,
        readiness_warnings: list[str] | None = None,
        testnet_result: dict[str, object] | None = None,
    ) -> None:
        recent = (self.now - timedelta(minutes=5)).isoformat()
        readiness_stamp = readiness_recent or recent
        dashboard_stamp = dashboard_recent or recent
        paper_stamp = paper_recent or recent
        self._write(
            self.paper_dir / "paper_forward" / "crypto_paper_forward_result.json",
            {
                "status": "SUCCESS",
                "warnings": list(forward_warnings or []),
                "heartbeat": {"last_updated_at": paper_stamp},
            },
        )
        self._write(
            self.paper_dir / "semantic" / "crypto_semantic_summary.json",
            {
                "operational_status": semantic_status,
                "warnings": list(semantic_warnings or []),
                "heartbeats": {"semantic_generated_at": recent},
            },
        )
        self._write(
            self.paper_dir / "dashboard" / "dashboard_data.json",
            {
                "generated_at": dashboard_stamp,
                "operational_status": dashboard_status,
                "warnings": list(dashboard_warnings or []),
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
                "warnings": list(readiness_warnings or ([] if readiness_status == "READY" else ["not ready"])),
            },
        )
        self._write(
            self.testnet_dir / "binance_testnet_execution_result.json",
            testnet_result
            or {
                "ok": True,
                "severity": "INFO",
                "warnings": [],
                "base_url": "https://testnet.binance.vision",
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
        self.assertEqual(result["blocking_reasons"], [])
        self.assertIn("testnet_not_ready_paper_only", result["degraded_reasons"])

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
        self.assertEqual(result["blocking_reasons"], [])

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

    def test_benign_paper_warnings_do_not_block_ready_testnet(self) -> None:
        self._seed_base(
            semantic_status="DEGRADED",
            dashboard_status="DEGRADED",
            readiness_status="READY",
            dry_run_ready=True,
            submit_ready=True,
            next_allowed_mode="controlled_submit",
            forward_warnings=[
                "Risk rejected BTCUSDT: symbol_position_exists",
                "Crypto strategy produced no trade candidates.",
            ],
            semantic_warnings=["Limited symbol attribution: no realized per-symbol exit data available."],
        )
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertEqual(result["overall_status"], "DEGRADED")
        self.assertEqual(result["final_decision"], "TESTNET_SUBMIT_ALLOWED")
        self.assertEqual(result["blocking_reasons"], [])
        self.assertIn("semantic_degraded", result["degraded_reasons"])
        self.assertIn("dashboard_degraded", result["degraded_reasons"])
        self.assertIn("Risk rejected BTCUSDT: symbol_position_exists", result["warnings"])
        self.assertIn("Crypto strategy produced no trade candidates.", result["warnings"])
        self.assertIn("Limited symbol attribution: no realized per-symbol exit data available.", result["warnings"])

    def test_analytic_paper_warnings_remain_visible_but_do_not_block_ready_testnet(self) -> None:
        self._seed_base(
            semantic_status="DEGRADED",
            dashboard_status="DEGRADED",
            readiness_status="READY",
            dry_run_ready=True,
            submit_ready=False,
            next_allowed_mode="order_test_only_or_dry_run",
            forward_warnings=[
                "Risk rejected BTCUSDT: symbol_position_exists",
                "Crypto strategy produced no trade candidates.",
                "Small sample size: fewer than 30 closed trades.",
                "Paper-only results; no real execution occurred.",
                "Fees and slippage are simulated.",
            ],
            semantic_warnings=[
                "Limited symbol attribution: no realized per-symbol exit data available.",
                "No closed trades available; strategy metrics are limited.",
                "Open trades are excluded from closed-trade expectancy.",
            ],
        )
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertEqual(result["overall_status"], "DEGRADED")
        self.assertEqual(result["final_decision"], "TESTNET_DRY_RUN_ALLOWED")
        self.assertEqual(result["blocking_reasons"], [])
        self.assertIn("semantic_degraded", result["degraded_reasons"])
        self.assertIn("dashboard_degraded", result["degraded_reasons"])
        self.assertIn("Small sample size: fewer than 30 closed trades.", result["warnings"])
        self.assertIn("Paper-only results; no real execution occurred.", result["warnings"])
        self.assertIn("Fees and slippage are simulated.", result["warnings"])

    def test_active_id_collision_blocks_testnet(self) -> None:
        self._seed_base(
            readiness_status="READY",
            dry_run_ready=True,
            submit_ready=True,
            forward_warnings=["id_collision_with_diff_content:order_id=crypto-paper-order-0001"],
        )
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertEqual(result["overall_status"], "BLOCKED")
        self.assertEqual(result["final_decision"], "DO_NOT_RUN")
        self.assertTrue(any(reason.startswith("hard_warning:") for reason in result["blocking_reasons"]))

    def test_wrong_testnet_base_url_blocks(self) -> None:
        self._seed_base(
            readiness_status="READY",
            dry_run_ready=True,
            submit_ready=True,
            testnet_result={
                "ok": True,
                "severity": "INFO",
                "base_url": "https://api.binance.com",
                "warnings": [],
            },
        )
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertEqual(result["overall_status"], "BLOCKED")
        self.assertEqual(result["final_decision"], "DO_NOT_RUN")
        self.assertIn("testnet_result_base_url_not_testnet", result["blocking_reasons"])

    def test_local_dry_run_no_client_warnings_do_not_block(self) -> None:
        recent = (self.now - timedelta(minutes=5)).isoformat()
        self._seed_base(
            semantic_status="DEGRADED",
            dashboard_status="DEGRADED",
            readiness_status="READY",
            dry_run_ready=True,
            submit_ready=False,
            next_allowed_mode="order_test_only_or_dry_run",
            readiness_warnings=[
                "Controlled submit requires a connected Binance Spot Testnet client.",
                "Controlled submit requires real server time validation.",
                "Controlled submit requires real exchange filters validation.",
                "Controlled submit requires real exchange reconciliation.",
            ],
            testnet_result={
                "ok": True,
                "severity": "INFO",
                "base_url": "https://testnet.binance.vision",
                "dry_run": True,
                "submit_attempted": False,
                "warnings": [
                    "server_time_unavailable:no_client",
                    "exchange_filters_unavailable:no_client",
                    "exchange_reconciliation_unavailable:no_client",
                ],
                "time_sync": {"checked": False, "warnings": ["server_time_unavailable:no_client"]},
                "heartbeat": {"last_updated_at": recent, "status": "SUCCESS"},
            },
        )
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertEqual(result["overall_status"], "DEGRADED")
        self.assertEqual(result["final_decision"], "TESTNET_DRY_RUN_ALLOWED")
        self.assertEqual(result["blocking_reasons"], [])
        self.assertIn("server_time_unavailable:no_client", result["warnings"])
        self.assertIn("exchange_filters_unavailable:no_client", result["warnings"])
        self.assertIn("exchange_reconciliation_unavailable:no_client", result["warnings"])

    def test_connected_mode_no_client_warnings_block(self) -> None:
        recent = (self.now - timedelta(minutes=5)).isoformat()
        self._seed_base(
            readiness_status="NOT_READY",
            dry_run_ready=False,
            submit_ready=False,
            next_allowed_mode="blocked",
            testnet_result={
                "ok": True,
                "severity": "INFO",
                "base_url": "https://testnet.binance.vision",
                "dry_run": False,
                "submit_attempted": False,
                "warnings": [
                    "server_time_unavailable:no_client",
                    "exchange_filters_unavailable:no_client",
                    "exchange_reconciliation_unavailable:no_client",
                ],
                "time_sync": {"checked": False, "warnings": ["server_time_unavailable:no_client"]},
                "heartbeat": {"last_updated_at": recent, "status": "SUCCESS"},
            },
        )
        result = evaluate_crypto_operational_status(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            ops_artifacts_dir=self.ops_dir,
            now=self.now,
        )
        self.assertEqual(result["overall_status"], "BLOCKED")
        self.assertEqual(result["final_decision"], "DO_NOT_RUN")
        self.assertTrue(any(reason.startswith("hard_warning:exchange_filters_unavailable:no_client") for reason in result["blocking_reasons"]))

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
        self.assertNotIn('"api_key"', serialized)

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
        self.assertIn("## Degraded Reasons", md)
        self.assertEqual(
            result["artifacts"]["crypto_operational_status.md"],
            str(self.ops_dir / "crypto_operational_status.md"),
        )


if __name__ == "__main__":
    unittest.main()

