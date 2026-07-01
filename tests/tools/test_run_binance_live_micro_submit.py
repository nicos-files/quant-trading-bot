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

from src.tools import run_binance_live_micro_submit as cli


class RunBinanceLiveMicroSubmitCLITests(unittest.TestCase):
    def test_parser_supports_prepare_only_and_execute(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(['--prepare-only'])
        self.assertTrue(args.prepare_only)
        self.assertFalse(args.execute)

    def test_help_mentions_prepare_only_and_inline_confirm_only(self) -> None:
        parser = cli.build_parser()
        help_text = parser.format_help()
        self.assertIn('Never places,', help_text)
        self.assertIn('tests, or submits an order', help_text)
        self.assertIn('must never be exported globally', help_text)
        self.assertNotIn('API_SECRET=', help_text)
        self.assertNotIn('place_order', help_text)

    def test_cli_defaults_to_prepare_only_behavior(self) -> None:
        payload = {
            'ok': True,
            'status': 'PREPARED',
            'prepare_only': True,
            'submit_attempted': False,
            'blocking_reasons': [],
            'warnings': ['prepare_only_no_live_order_executed'],
        }
        buf = io.StringIO()
        with mock.patch.object(cli, 'run_binance_live_micro_submit_prepare_only', return_value=payload) as patched, redirect_stdout(buf):
            code = cli.main([])
        self.assertEqual(code, 0)
        self.assertEqual(patched.call_args.kwargs['prepare_only'], True)
        self.assertEqual(patched.call_args.kwargs['execute'], False)
        data = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertTrue(data['prepare_only'])
        self.assertFalse(data['submit_attempted'])

    def test_cli_execute_flag_still_fails_closed(self) -> None:
        payload = {
            'ok': False,
            'status': 'BLOCKED',
            'prepare_only': False,
            'submit_attempted': False,
            'blocking_reasons': ['live_execute_not_implemented'],
            'warnings': ['prepare_only_no_live_order_executed'],
        }
        buf = io.StringIO()
        with mock.patch.object(cli, 'run_binance_live_micro_submit_prepare_only', return_value=payload), redirect_stdout(buf):
            code = cli.main(['--execute'])
        self.assertEqual(code, 1)
        data = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertIn('live_execute_not_implemented', data['blocking_reasons'])