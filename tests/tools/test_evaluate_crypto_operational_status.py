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

from src.tools.evaluate_crypto_operational_status import main


class EvaluateCryptoOperationalStatusToolTests(unittest.TestCase):
    def test_cli_writes_operational_status_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            root = Path(tmp)
            paper_dir = root / "crypto_paper"
            testnet_dir = root / "crypto_testnet"
            ops_dir = root / "crypto_ops"
            (paper_dir / "paper_forward").mkdir(parents=True, exist_ok=True)
            (paper_dir / "semantic").mkdir(parents=True, exist_ok=True)
            (paper_dir / "dashboard").mkdir(parents=True, exist_ok=True)
            testnet_dir.mkdir(parents=True, exist_ok=True)
            (paper_dir / "paper_forward" / "crypto_paper_forward_result.json").write_text(
                json.dumps({"status": "SUCCESS", "heartbeat": {"last_updated_at": recent}}),
                encoding="utf-8",
            )
            (paper_dir / "semantic" / "crypto_semantic_summary.json").write_text(
                json.dumps({"operational_status": "OK", "heartbeats": {"semantic_generated_at": recent}}),
                encoding="utf-8",
            )
            (paper_dir / "dashboard" / "dashboard_data.json").write_text(
                json.dumps({"generated_at": recent, "operational_status": "OK"}),
                encoding="utf-8",
            )
            (testnet_dir / "crypto_testnet_readiness.json").write_text(
                json.dumps({
                    "generated_at": recent,
                    "status": "READY",
                    "dry_run_ready": True,
                    "submit_ready": True,
                    "next_allowed_mode": "controlled_submit",
                }),
                encoding="utf-8",
            )
            (testnet_dir / "binance_testnet_execution_result.json").write_text(
                json.dumps({"ok": True, "severity": "INFO"}),
                encoding="utf-8",
            )
            rc = main(
                [
                    "--paper-artifacts-dir",
                    str(paper_dir),
                    "--testnet-artifacts-dir",
                    str(testnet_dir),
                    "--ops-artifacts-dir",
                    str(ops_dir),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue((ops_dir / "crypto_operational_status.json").exists())
            self.assertTrue((ops_dir / "crypto_operational_status.md").exists())


if __name__ == "__main__":
    unittest.main()
