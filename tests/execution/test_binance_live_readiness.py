from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.binance_live_readiness import evaluate_binance_live_readiness
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


class BinanceLiveReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / ARTIFACTS_SUBDIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_readonly(self, **overrides: object) -> None:
        payload = {
            "ok": True,
            "status": "SUCCESS",
            "base_url": "https://api.binance.com",
            "live_trading_enabled": False,
            "live_kill_switch_active": True,
            "server_time_available": True,
            "exchange_filters_available": True,
            "account_checked": True,
            "balances_checked": True,
            "open_orders_checked": True,
            "reconciliation_summary": {
                "count": 0,
                "blocking_count": 0,
                "highest_severity": "INFO",
                "counts_by_severity": {"INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0},
                "counts_by_level": {"tolerable_drift": 0, "warning": 0, "error": 0, "critical_hard_stop": 0},
            },
            "blocking_reasons": [],
            "heartbeat": {"last_updated_at": self.now.isoformat()},
            "warnings": ["live_kill_switch_active_default_on"],
        }
        payload.update(overrides)
        (self.root / 'binance_mainnet_readonly_preflight.json').write_text(json.dumps(payload), encoding='utf-8')

    def test_live_readiness_ok_with_clean_readonly_artifact(self) -> None:
        self._write_readonly()
        result = evaluate_binance_live_readiness(artifacts_dir=self.root, now=self.now)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'READY_FOR_PREPARE_ONLY')
        self.assertEqual(result['live_readiness_status'], 'READY_FOR_PREPARE_ONLY')
        self.assertFalse(result['live_submit_allowed'])
        self.assertEqual(result['next_allowed_mode'], 'prepare_only')

    def test_blocks_if_artifact_missing(self) -> None:
        result = evaluate_binance_live_readiness(artifacts_dir=self.root, now=self.now)
        self.assertFalse(result['ok'])
        self.assertIn('mainnet_readonly_artifact_missing_or_unreadable', result['blocking_reasons'])

    def test_blocks_if_artifact_stale(self) -> None:
        self._write_readonly(heartbeat={"last_updated_at": (self.now - timedelta(minutes=31)).isoformat()})
        result = evaluate_binance_live_readiness(artifacts_dir=self.root, now=self.now)
        self.assertFalse(result['ok'])
        self.assertIn('mainnet_readonly_artifact_stale', result['blocking_reasons'])

    def test_blocks_if_base_url_invalid(self) -> None:
        self._write_readonly(base_url='https://testnet.binance.vision')
        result = evaluate_binance_live_readiness(artifacts_dir=self.root, now=self.now)
        self.assertFalse(result['ok'])
        self.assertIn('mainnet_base_url_invalid', result['blocking_reasons'])

    def test_blocks_if_readonly_not_ok(self) -> None:
        self._write_readonly(ok=False)
        result = evaluate_binance_live_readiness(artifacts_dir=self.root, now=self.now)
        self.assertFalse(result['ok'])
        self.assertIn('mainnet_readonly_not_ok', result['blocking_reasons'])

    def test_blocks_if_reconciliation_has_blocking_count(self) -> None:
        self._write_readonly(reconciliation_summary={
            "count": 1,
            "blocking_count": 1,
            "highest_severity": "ERROR",
            "counts_by_severity": {"INFO": 0, "WARNING": 0, "ERROR": 1, "CRITICAL": 0},
            "counts_by_level": {"tolerable_drift": 0, "warning": 0, "error": 1, "critical_hard_stop": 0},
        })
        result = evaluate_binance_live_readiness(artifacts_dir=self.root, now=self.now)
        self.assertFalse(result['ok'])
        self.assertIn('readonly_reconciliation_blocking', result['blocking_reasons'])

    def test_blocks_if_open_orders_not_checked(self) -> None:
        self._write_readonly(open_orders_checked=False)
        result = evaluate_binance_live_readiness(artifacts_dir=self.root, now=self.now)
        self.assertFalse(result['ok'])
        self.assertIn('open_orders_check_missing', result['blocking_reasons'])

    def test_live_submit_allowed_stays_false(self) -> None:
        self._write_readonly()
        result = evaluate_binance_live_readiness(artifacts_dir=self.root, now=self.now)
        self.assertFalse(result['live_submit_allowed'])