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

    def test_help_mentions_execute_gate_and_no_global_confirm(self) -> None:
        parser = cli.build_parser()
        help_text = parser.format_help()
        self.assertIn('Prepare-only is the default', help_text)
        self.assertIn('must never', help_text)
        self.assertIn('exported globally', help_text)
        self.assertNotIn('API_SECRET=', help_text)
        self.assertNotIn('order/test', help_text)

    def test_cli_defaults_to_prepare_only_behavior(self) -> None:
        payload = {'ok': True, 'status': 'PREPARED', 'prepare_only': True, 'execute': False, 'submit_attempted': False}
        buf = io.StringIO()
        with mock.patch.object(cli, 'run_binance_live_micro_submit', return_value=payload) as patched, redirect_stdout(buf):
            code = cli.main([])
        self.assertEqual(code, 0)
        self.assertEqual(patched.call_args.kwargs['prepare_only'], False)
        self.assertEqual(patched.call_args.kwargs['execute'], False)
        data = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertTrue(data['prepare_only'])
        self.assertFalse(data['submit_attempted'])

    def test_cli_passes_execute_flag_through(self) -> None:
        payload = {'ok': False, 'status': 'BLOCKED', 'prepare_only': False, 'execute': True, 'submit_attempted': False, 'blocking_reasons': ['gate']}
        buf = io.StringIO()
        with mock.patch.object(cli, 'run_binance_live_micro_submit', return_value=payload) as patched, redirect_stdout(buf):
            code = cli.main(['--execute'])
        self.assertEqual(code, 1)
        self.assertEqual(patched.call_args.kwargs['execute'], True)
        data = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertTrue(data['execute'])
        self.assertIn('gate', data['blocking_reasons'])