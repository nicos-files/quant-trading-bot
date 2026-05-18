from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools import run_crypto_testnet_dry_run as cli


class RunCryptoTestnetDryRunCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.paper_dir = Path(self._tmp.name) / "crypto_paper"
        self.paper_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_exit_zero_when_dry_run_succeeds(self) -> None:
        buf = io.StringIO()
        with mock.patch.object(
            cli,
            "run_crypto_testnet_dry_run",
            return_value={"ok": True, "final_decision": "TESTNET_DRY_RUN_ALLOWED"},
        ) as patched, redirect_stdout(buf):
            code = cli.main(["--paper-artifacts-dir", str(self.paper_dir)])
        self.assertEqual(code, 0)
        self.assertEqual(patched.call_count, 1)
        payload = json.loads(buf.getvalue().strip())
        self.assertTrue(payload["ok"])

    def test_exit_one_when_dry_run_is_blocked(self) -> None:
        buf = io.StringIO()
        with mock.patch.object(
            cli,
            "run_crypto_testnet_dry_run",
            return_value={"ok": False, "final_decision": "DO_NOT_RUN"},
        ), redirect_stdout(buf):
            code = cli.main(["--paper-artifacts-dir", str(self.paper_dir)])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
