from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools import run_binance_mainnet_readonly_preflight as cli


class BinanceMainnetReadonlyPreflightCLITests(unittest.TestCase):
    def test_parser_defaults_artifacts_dir(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args([])
        self.assertIn('artifacts/crypto_mainnet', args.artifacts_dir)

    def test_cli_emits_redacted_audit_and_exit_zero(self) -> None:
        payload = {
            'run_id': 'mainnet-readonly-20260623-230000',
            'ok': True,
            'status': 'SUCCESS',
            'mainnet': True,
            'testnet': False,
            'live_trading_enabled': False,
            'live_readiness_status': 'NOT_READY',
            'live_submit_allowed': False,
            'submit_attempted': False,
            'base_url': 'https://api.binance.com',
            'server_time_available': True,
            'exchange_filters_available': True,
            'account_checked': True,
            'balances_checked': True,
            'open_orders_checked': True,
            'reconciliation_summary': {'count': 0, 'highest_severity': 'INFO'},
            'blocking_reasons': [],
            'warnings': [],
            'api_key_masked': '****abcd',
            'heartbeat': {'status': 'SUCCESS'},
            'artifacts': {'binance_mainnet_readonly_preflight.json': '/tmp/result.json'},
        }
        buf = io.StringIO()
        with mock.patch.object(cli, 'run_binance_mainnet_readonly_preflight', return_value=payload), redirect_stdout(buf):
            code = cli.main([])
        self.assertEqual(code, 0)
        audit = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertTrue(audit['ok'])
        self.assertFalse(audit['live_trading_enabled'])
        self.assertFalse(audit['submit_attempted'])
        serialized = json.dumps(audit)
        self.assertNotIn('topsecret', serialized.lower())
        self.assertEqual(audit['api_key_masked'], '****abcd')
        self.assertIn('ENABLE_BINANCE_MAINNET_READONLY', audit['env_flags'])

    def test_cli_exit_one_on_blocked(self) -> None:
        payload = {
            'run_id': 'mainnet-readonly-20260623-230000',
            'ok': False,
            'status': 'BLOCKED',
            'mainnet': True,
            'testnet': False,
            'live_trading_enabled': False,
            'live_readiness_status': 'NOT_READY',
            'live_submit_allowed': False,
            'submit_attempted': False,
            'base_url': 'https://api.binance.com',
            'server_time_available': False,
            'exchange_filters_available': False,
            'account_checked': False,
            'balances_checked': False,
            'open_orders_checked': False,
            'reconciliation_summary': {'count': 0, 'highest_severity': 'INFO'},
            'blocking_reasons': ['ENABLE_BINANCE_MAINNET_READONLY is not \'1\'. Mainnet readonly preflight disabled.'],
            'warnings': [],
            'api_key_masked': None,
            'heartbeat': {'status': 'BLOCKED'},
            'artifacts': {'binance_mainnet_readonly_preflight.json': '/tmp/result.json'},
        }
        buf = io.StringIO()
        with mock.patch.object(cli, 'run_binance_mainnet_readonly_preflight', return_value=payload), redirect_stdout(buf):
            code = cli.main([])
        self.assertEqual(code, 1)