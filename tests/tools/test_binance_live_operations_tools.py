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

from src.tools import evaluate_binance_live_operations as eval_cli
from src.tools import halt_binance_live_operations as halt_cli


class EvaluateBinanceLiveOperationsCLITests(unittest.TestCase):
    def test_help_is_readonly_and_mentions_no_order(self) -> None:
        help_text = eval_cli.build_parser().format_help()
        self.assertIn('never places any order', help_text)
        self.assertNotIn('API_SECRET=', help_text)

    def test_cli_emits_json(self) -> None:
        payload = {'ok': True, 'status': 'READY_FOR_SINGLE_SHOT', 'live_mode': 'SINGLE_SHOT'}
        buf = io.StringIO()
        with mock.patch.object(eval_cli, 'evaluate_binance_live_operations', return_value=payload), redirect_stdout(buf):
            code = eval_cli.main([])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue().strip())
        self.assertEqual(data['live_mode'], 'SINGLE_SHOT')


class HaltBinanceLiveOperationsCLITests(unittest.TestCase):
    def test_help_mentions_no_broker_calls(self) -> None:
        help_text = halt_cli.build_parser().format_help()
        self.assertIn('No broker calls', help_text)
        self.assertNotIn('API_SECRET=', help_text)

    def test_cli_emits_halted_json(self) -> None:
        payload = {'ok': True, 'status': 'HALTED', 'enabled': True}
        buf = io.StringIO()
        with mock.patch.object(halt_cli, 'halt_binance_live_operations', return_value=payload), redirect_stdout(buf):
            code = halt_cli.main(['--reason', 'ops'])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue().strip())
        self.assertTrue(data['enabled'])
        self.assertEqual(data['status'], 'HALTED')
