from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.binance_live_micro_submit import run_binance_live_micro_submit_prepare_only
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


class BinanceLiveMicroSubmitPrepareOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / ARTIFACTS_SUBDIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_readiness(self, **overrides: object) -> None:
        payload = {
            'ok': True,
            'status': 'READY_FOR_PREPARE_ONLY',
            'live_readiness_status': 'READY_FOR_PREPARE_ONLY',
            'live_submit_allowed': False,
            'blocking_reasons': [],
            'base_url': 'https://api.binance.com',
        }
        payload.update(overrides)
        (self.root / 'binance_live_readiness.json').write_text(json.dumps(payload), encoding='utf-8')

    def _valid_env(self, **overrides: str) -> dict[str, str]:
        base = {
            'BINANCE_LIVE_TRADING_ENABLED': '1',
            'BINANCE_LIVE_CONFIRM_SUBMIT': 'YES',
            'BINANCE_LIVE_KILL_SWITCH': '0',
            'BINANCE_LIVE_BASE_URL': 'https://api.binance.com',
            'BINANCE_LIVE_ALLOWED_SYMBOLS': 'BTCUSDT',
            'BINANCE_LIVE_MAX_NOTIONAL': '5',
            'BINANCE_LIVE_MAX_DAILY_ORDERS': '1',
            'BINANCE_LIVE_MAX_OPEN_ORDERS': '1',
            'BINANCE_LIVE_API_KEY': 'live-key',
            'BINANCE_LIVE_API_SECRET': 'live-secret',
            'BINANCE_MAINNET_API_KEY': 'readonly-key',
            'BINANCE_MAINNET_API_SECRET': 'readonly-secret',
        }
        base.update(overrides)
        return base

    def test_prepare_only_no_submit_attempted(self) -> None:
        self._write_readiness()
        result = run_binance_live_micro_submit_prepare_only(
            artifacts_dir=self.root,
            env=self._valid_env(),
            now=self.now,
            prepare_only=True,
            execute=False,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'PREPARED')
        self.assertTrue(result['prepare_only'])
        self.assertFalse(result['submit_attempted'])
        self.assertIn('prepare_only_no_live_order_executed', result['warnings'])

    def test_blocks_without_readiness_artifact(self) -> None:
        result = run_binance_live_micro_submit_prepare_only(
            artifacts_dir=self.root,
            env=self._valid_env(),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('live_readiness_artifact_missing_or_unreadable', result['blocking_reasons'])

    def test_blocks_if_readiness_not_valid(self) -> None:
        self._write_readiness(status='NOT_READY', live_readiness_status='NOT_READY')
        result = run_binance_live_micro_submit_prepare_only(
            artifacts_dir=self.root,
            env=self._valid_env(),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('live_readiness_not_ready_for_prepare_only', result['blocking_reasons'])

    def test_blocks_if_max_notional_gt_5(self) -> None:
        self._write_readiness()
        result = run_binance_live_micro_submit_prepare_only(
            artifacts_dir=self.root,
            env=self._valid_env(BINANCE_LIVE_MAX_NOTIONAL='6'),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('live_max_notional_must_be_between_0_and_5', result['blocking_reasons'])

    def test_blocks_if_allowed_symbols_not_btcusdt(self) -> None:
        self._write_readiness()
        result = run_binance_live_micro_submit_prepare_only(
            artifacts_dir=self.root,
            env=self._valid_env(BINANCE_LIVE_ALLOWED_SYMBOLS='BTCUSDT,ETHUSDT'),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('live_allowed_symbols_must_be_btcusdt_only', result['blocking_reasons'])

    def test_blocks_if_max_daily_orders_not_one(self) -> None:
        self._write_readiness()
        result = run_binance_live_micro_submit_prepare_only(
            artifacts_dir=self.root,
            env=self._valid_env(BINANCE_LIVE_MAX_DAILY_ORDERS='2'),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('live_max_daily_orders_must_equal_1', result['blocking_reasons'])

    def test_blocks_if_max_open_orders_not_one(self) -> None:
        self._write_readiness()
        result = run_binance_live_micro_submit_prepare_only(
            artifacts_dir=self.root,
            env=self._valid_env(BINANCE_LIVE_MAX_OPEN_ORDERS='2'),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('live_max_open_orders_must_equal_1', result['blocking_reasons'])

    def test_blocks_if_live_key_reuses_readonly_key(self) -> None:
        self._write_readiness()
        result = run_binance_live_micro_submit_prepare_only(
            artifacts_dir=self.root,
            env=self._valid_env(BINANCE_LIVE_API_KEY='readonly-key'),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('live_api_key_must_not_reuse_mainnet_readonly_key', result['blocking_reasons'])

    def test_blocks_if_live_secret_reuses_readonly_secret(self) -> None:
        self._write_readiness()
        result = run_binance_live_micro_submit_prepare_only(
            artifacts_dir=self.root,
            env=self._valid_env(BINANCE_LIVE_API_SECRET='readonly-secret'),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('live_api_secret_must_not_reuse_mainnet_readonly_secret', result['blocking_reasons'])

    def test_blocks_if_live_trading_flag_missing(self) -> None:
        self._write_readiness()
        env = self._valid_env()
        env.pop('BINANCE_LIVE_TRADING_ENABLED')
        result = run_binance_live_micro_submit_prepare_only(artifacts_dir=self.root, env=env, now=self.now)
        self.assertFalse(result['ok'])
        self.assertIn('live_trading_enabled_flag_required', result['blocking_reasons'])

    def test_blocks_if_confirm_submit_missing(self) -> None:
        self._write_readiness()
        env = self._valid_env(BINANCE_LIVE_CONFIRM_SUBMIT='NO')
        result = run_binance_live_micro_submit_prepare_only(artifacts_dir=self.root, env=env, now=self.now)
        self.assertFalse(result['ok'])
        self.assertIn('live_confirm_submit_yes_required', result['blocking_reasons'])

    def test_blocks_if_kill_switch_not_zero(self) -> None:
        self._write_readiness()
        env = self._valid_env(BINANCE_LIVE_KILL_SWITCH='1')
        result = run_binance_live_micro_submit_prepare_only(artifacts_dir=self.root, env=env, now=self.now)
        self.assertFalse(result['ok'])
        self.assertIn('live_kill_switch_must_be_zero_for_future_submit', result['blocking_reasons'])

    def test_execute_flag_fails_closed(self) -> None:
        self._write_readiness()
        result = run_binance_live_micro_submit_prepare_only(
            artifacts_dir=self.root,
            env=self._valid_env(),
            now=self.now,
            prepare_only=False,
            execute=True,
        )
        self.assertFalse(result['ok'])
        self.assertFalse(result['submit_attempted'])
        self.assertIn('live_execute_not_implemented', result['blocking_reasons'])