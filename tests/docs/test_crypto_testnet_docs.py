from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class CryptoTestnetDocsTests(unittest.TestCase):
    def test_readiness_checklist_exists_and_rejects_live_mainnet(self) -> None:
        path = REPO_ROOT / "docs" / "crypto_testnet_readiness_checklist.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8").lower()
        self.assertIn("no live trading", text)
        self.assertIn("no mainnet", text)
        self.assertIn("forbidden modes", text)
        self.assertNotIn("api.binance.com", text)

    def test_runbook_exists_and_demands_stop_on_ambiguity(self) -> None:
        path = REPO_ROOT / "docs" / "crypto_testnet_runbook.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8").lower()
        self.assertIn("do not continue if state is ambiguous", text)
        self.assertIn("kill switch", text)
        self.assertIn("reconciliation mismatch", text)
        self.assertIn("no live trading", text)

    def test_dry_run_procedure_exists_and_forbids_live_mainnet(self) -> None:
        path = REPO_ROOT / "docs" / "crypto_testnet_dry_run_procedure.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8").lower()
        self.assertIn("no live trading", text)
        self.assertIn("no mainnet", text)
        self.assertIn("run_crypto_testnet_dry_run", text)
        self.assertNotIn("api.binance.com", text)


if __name__ == "__main__":
    unittest.main()
