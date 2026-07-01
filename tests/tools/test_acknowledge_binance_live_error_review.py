from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools import acknowledge_binance_live_error_review as cli


class AcknowledgeBinanceLiveErrorReviewCLITests(unittest.TestCase):
    def test_help_mentions_no_same_day_retry(self) -> None:
        help_text = cli.build_parser().format_help()
        self.assertIn("same-day retry", help_text)
        self.assertNotIn("API_SECRET=", help_text)

    def test_cli_emits_json(self) -> None:
        payload = {"ok": True, "status": "ACKNOWLEDGED", "allow_retry_same_utc_day": False}
        buf = io.StringIO()
        with mock.patch.object(cli, "acknowledge_binance_live_error_review", return_value=payload), redirect_stdout(buf):
            code = cli.main(["--reason", "reviewed"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue().strip())
        self.assertEqual(data["status"], "ACKNOWLEDGED")
