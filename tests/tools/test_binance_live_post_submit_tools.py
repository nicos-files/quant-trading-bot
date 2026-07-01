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

from src.tools import evaluate_binance_live_soak_status as soak_cli
from src.tools import generate_binance_live_daily_close as close_cli
from src.tools import generate_binance_live_incident_report as incident_cli
from src.tools import run_binance_live_cancel_open_orders as cancel_cli


class BinanceLivePostSubmitToolTests(unittest.TestCase):
    def test_cancel_help_mentions_no_cancel_endpoint(self) -> None:
        help_text = cancel_cli.build_parser().format_help()
        self.assertIn("No cancel endpoint is called", help_text)
        self.assertNotIn("API_SECRET=", help_text)

    def test_cancel_cli_emits_json(self) -> None:
        payload = {"ok": True, "status": "PREPARED", "open_orders_count": 0}
        buf = io.StringIO()
        with mock.patch.object(cancel_cli, "run_binance_live_cancel_open_orders", return_value=payload), redirect_stdout(buf):
            code = cancel_cli.main(["--prepare-only"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue().strip())
        self.assertEqual(data["status"], "PREPARED")

    def test_incident_cli_emits_json(self) -> None:
        payload = {"severity": "CRITICAL", "recommended_action": "Set HALTED"}
        buf = io.StringIO()
        with mock.patch.object(incident_cli, "generate_binance_live_incident_report", return_value=payload), redirect_stdout(buf):
            code = incident_cli.main([])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue().strip())
        self.assertEqual(data["severity"], "CRITICAL")

    def test_daily_close_cli_emits_json(self) -> None:
        payload = {"soak_day_status": "PASS", "date_utc": "20260702"}
        buf = io.StringIO()
        with mock.patch.object(close_cli, "generate_binance_live_daily_close", return_value=payload), redirect_stdout(buf):
            code = close_cli.main([])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue().strip())
        self.assertEqual(data["soak_day_status"], "PASS")

    def test_soak_cli_exit_code_depends_on_status(self) -> None:
        buf = io.StringIO()
        with mock.patch.object(soak_cli, "evaluate_binance_live_soak_status", return_value={"soak_status": "PASSED"}), redirect_stdout(buf):
            code = soak_cli.main([])
        self.assertEqual(code, 0)
        buf = io.StringIO()
        with mock.patch.object(soak_cli, "evaluate_binance_live_soak_status", return_value={"soak_status": "INCOMPLETE"}), redirect_stdout(buf):
            code = soak_cli.main([])
        self.assertEqual(code, 1)
