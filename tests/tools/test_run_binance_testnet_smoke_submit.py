from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools import run_binance_testnet_smoke_submit as cli


class BinanceTestnetSmokeSubmitCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.paper_dir = Path(self._tmp.name) / 'crypto_paper'
        self.paper_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_parser_requires_paper_artifacts_dir(self) -> None:
        parser = cli.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_cli_emits_redacted_audit_and_exit_zero_on_success(self) -> None:
        payload = {
            'run_id': 'testnet-smoke-20260623-171000',
            'ok': True,
            'status': 'SUCCESS',
            'testnet': True,
            'live_trading': False,
            'order_test_only': False,
            'confirm_submit': True,
            'base_url': 'https://testnet.binance.vision',
            'symbol': 'BTCUSDT',
            'requested_notional': 10.0,
            'placed_count': 1,
            'rejected_count': 0,
            'submit_attempted': True,
            'severity': 'INFO',
            'category': None,
            'failure_reason': None,
            'action_taken': 'testnet_submit_attempted',
            'reconciliation_summary': {'count': 0, 'highest_severity': 'INFO'},
            'blocking_reasons': [],
            'warnings': [],
            'api_key_masked': '****abcd',
            'heartbeat': {'status': 'SUCCESS'},
            'artifacts': {'binance_testnet_smoke_submit_result.json': '/tmp/result.json'},
        }
        buf = io.StringIO()
        with mock.patch.object(cli, 'run_binance_testnet_smoke_submit', return_value=payload) as patched, redirect_stdout(buf):
            code = cli.main(['--paper-artifacts-dir', str(self.paper_dir)])
        self.assertEqual(code, 0)
        self.assertEqual(patched.call_count, 1)
        audit = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertTrue(audit['ok'])
        self.assertEqual(audit['api_key_masked'], '****abcd')
        self.assertIn('BINANCE_TESTNET_CONFIRM_SUBMIT', audit['env_flags'])

    def test_cli_exit_one_on_blocked(self) -> None:
        payload = {
            'run_id': 'testnet-smoke-20260623-171000',
            'ok': False,
            'status': 'BLOCKED',
            'testnet': True,
            'live_trading': False,
            'order_test_only': False,
            'confirm_submit': False,
            'base_url': 'https://testnet.binance.vision',
            'symbol': 'BTCUSDT',
            'requested_notional': None,
            'placed_count': 0,
            'rejected_count': 0,
            'submit_attempted': False,
            'severity': 'CRITICAL',
            'category': 'TESTNET_SUBMIT_FAILED',
            'failure_reason': 'missing_binance_testnet_confirm_submit:require_exact_value_YES',
            'action_taken': 'testnet_submit_blocked',
            'reconciliation_summary': None,
            'blocking_reasons': ['missing_binance_testnet_confirm_submit:require_exact_value_YES'],
            'warnings': [],
            'api_key_masked': None,
            'heartbeat': {'status': 'BLOCKED'},
            'artifacts': {'binance_testnet_smoke_submit_result.json': '/tmp/result.json'},
        }
        buf = io.StringIO()
        with mock.patch.object(cli, 'run_binance_testnet_smoke_submit', return_value=payload), redirect_stdout(buf):
            code = cli.main(['--paper-artifacts-dir', str(self.paper_dir)])
        self.assertEqual(code, 1)
        audit = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertFalse(audit['ok'])
        self.assertNotIn('secret', json.dumps(audit).lower())


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
