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

from src.tools import evaluate_binance_live_readiness as cli


class EvaluateBinanceLiveReadinessCLITests(unittest.TestCase):
    def test_parser_defaults_artifacts_dir(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args([])
        self.assertIn('artifacts/crypto_mainnet', args.artifacts_dir)

    def test_help_is_readonly_only_and_has_no_secret_values(self) -> None:
        parser = cli.build_parser()
        help_text = parser.format_help()
        self.assertIn('Read-only only', help_text)
        self.assertNotIn('API_SECRET=', help_text)
        self.assertNotIn('api secret', help_text.lower())

    def test_cli_emits_json_and_exit_zero(self) -> None:
        payload = {
            'ok': True,
            'status': 'READY_FOR_PREPARE_ONLY',
            'live_readiness_status': 'READY_FOR_PREPARE_ONLY',
            'live_submit_allowed': False,
        }
        buf = io.StringIO()
        with mock.patch.object(cli, 'evaluate_binance_live_readiness', return_value=payload), redirect_stdout(buf):
            code = cli.main([])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertTrue(data['ok'])
        self.assertFalse(data['live_submit_allowed'])