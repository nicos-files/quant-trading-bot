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

from src.execution.binance_live_operations_controller import (
    MODE_ARMED_MANUAL,
    MODE_HALTED,
    MODE_OFF,
    MODE_READ_ONLY,
    MODE_SCHEDULED_WINDOW,
    MODE_SINGLE_SHOT,
    evaluate_binance_live_operations,
    halt_binance_live_operations,
)
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


class BinanceLiveOperationsControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / ARTIFACTS_SUBDIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
        self._write_readonly()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding='utf-8')

    def _write_readonly(self, *, heartbeat_offset_minutes: int = 0, quote_free: str = '10000.0') -> None:
        stamp = (self.now - timedelta(minutes=heartbeat_offset_minutes)).isoformat()
        self._write(
            self.root / 'binance_mainnet_readonly_preflight.json',
            {
                'ok': True,
                'status': 'SUCCESS',
                'base_url': 'https://api.binance.com',
                'live_trading_enabled': False,
                'live_kill_switch_active': True,
                'server_time_available': True,
                'exchange_filters_available': True,
                'account_checked': True,
                'balances_checked': True,
                'open_orders_checked': True,
                'balances': {
                    'USDT': {'free': quote_free, 'locked': '0.0'},
                    'BTC': {'free': '0.0', 'locked': '0.0'},
                },
                'reconciliation_summary': {
                    'count': 0,
                    'blocking_count': 0,
                    'highest_severity': 'INFO',
                    'counts_by_severity': {'INFO': 0, 'WARNING': 0, 'ERROR': 0, 'CRITICAL': 0},
                    'counts_by_level': {'tolerable_drift': 0, 'warning': 0, 'error': 0, 'critical_hard_stop': 0},
                },
                'blocking_reasons': [],
                'warnings': [],
                'heartbeat': {'last_updated_at': stamp},
            },
        )

    def _seed_soak_pass(self) -> None:
        daily_root = self.root / 'daily_close'
        daily_root.mkdir(parents=True, exist_ok=True)
        for offset in range(3):
            date = (self.now - timedelta(days=offset)).strftime('%Y%m%d')
            self._write(
                daily_root / f'binance_live_daily_close_{date}.json',
                {
                    'date_utc': date,
                    'soak_day_status': 'PASS',
                },
            )

    def _env(self, **overrides: str) -> dict[str, str]:
        base = {
            'BINANCE_LIVE_MODE': MODE_SINGLE_SHOT,
            'BINANCE_LIVE_TRADING_ENABLED': '1',
            'BINANCE_LIVE_CONFIRM_SUBMIT': 'YES',
            'BINANCE_LIVE_KILL_SWITCH': '0',
            'BINANCE_LIVE_ALLOWED_SYMBOLS': 'BTCUSDT',
            'BINANCE_LIVE_MAX_NOTIONAL': '5',
            'BINANCE_LIVE_MAX_DAILY_NOTIONAL': '5',
            'BINANCE_LIVE_MAX_DAILY_ORDERS': '1',
            'BINANCE_LIVE_MAX_OPEN_ORDERS': '1',
            'BINANCE_LIVE_BASE_URL': 'https://api.binance.com',
            'BINANCE_LIVE_ARM_TOKEN': 'ARMED',
        }
        base.update(overrides)
        return base

    def test_off_mode_blocks(self) -> None:
        result = evaluate_binance_live_operations(artifacts_dir=self.root, env=self._env(BINANCE_LIVE_MODE=MODE_OFF), now=self.now)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], MODE_OFF)
        self.assertFalse(result['can_prepare'])
        self.assertIn('live_mode_off', result['blocking_reasons'])

    def test_read_only_mode_disables_submit(self) -> None:
        result = evaluate_binance_live_operations(artifacts_dir=self.root, env=self._env(BINANCE_LIVE_MODE=MODE_READ_ONLY), now=self.now)
        self.assertEqual(result['status'], MODE_READ_ONLY)
        self.assertFalse(result['can_single_shot'])
        self.assertFalse(result['can_scheduled_trade'])

    def test_armed_manual_allows_prepare_only(self) -> None:
        result = evaluate_binance_live_operations(
            artifacts_dir=self.root,
            env=self._env(BINANCE_LIVE_MODE=MODE_ARMED_MANUAL, BINANCE_LIVE_TRADING_ENABLED='0', BINANCE_LIVE_CONFIRM_SUBMIT='NO'),
            now=self.now,
        )
        self.assertTrue(result['can_prepare'])
        self.assertFalse(result['can_single_shot'])

    def test_single_shot_allows_execute_when_all_gates_pass(self) -> None:
        result = evaluate_binance_live_operations(artifacts_dir=self.root, env=self._env(BINANCE_LIVE_MODE=MODE_SINGLE_SHOT), now=self.now)
        self.assertTrue(result['ok'])
        self.assertTrue(result['can_single_shot'])
        self.assertEqual(result['effective_order_budget'], 5.0)

    def test_scheduled_window_blocks_outside_window(self) -> None:
        self._seed_soak_pass()
        result = evaluate_binance_live_operations(
            artifacts_dir=self.root,
            env=self._env(
                BINANCE_LIVE_MODE=MODE_SCHEDULED_WINDOW,
                BINANCE_LIVE_START_TIME_UTC='13:00',
                BINANCE_LIVE_END_TIME_UTC='14:00',
                BINANCE_LIVE_SCHEDULED_WINDOW_ENABLED='1',
            ),
            now=self.now,
        )
        self.assertFalse(result['can_scheduled_trade'])
        self.assertIn('scheduled_window_closed', result['warnings'])

    def test_scheduled_window_allows_inside_window(self) -> None:
        self._seed_soak_pass()
        result = evaluate_binance_live_operations(
            artifacts_dir=self.root,
            env=self._env(
                BINANCE_LIVE_MODE=MODE_SCHEDULED_WINDOW,
                BINANCE_LIVE_START_TIME_UTC='11:00',
                BINANCE_LIVE_END_TIME_UTC='13:00',
                BINANCE_LIVE_SCHEDULED_WINDOW_ENABLED='1',
            ),
            now=self.now,
        )
        self.assertTrue(result['ok'])
        self.assertTrue(result['can_scheduled_trade'])

    def test_scheduled_window_blocks_without_soak_pass(self) -> None:
        result = evaluate_binance_live_operations(
            artifacts_dir=self.root,
            env=self._env(
                BINANCE_LIVE_MODE=MODE_SCHEDULED_WINDOW,
                BINANCE_LIVE_START_TIME_UTC='11:00',
                BINANCE_LIVE_END_TIME_UTC='13:00',
                BINANCE_LIVE_SCHEDULED_WINDOW_ENABLED='1',
            ),
            now=self.now,
        )
        self.assertFalse(result['can_scheduled_trade'])
        self.assertIn('live_scheduled_window_requires_soak_passed', result['blocking_reasons'])

    def test_scheduled_window_blocks_without_enable_flag(self) -> None:
        self._seed_soak_pass()
        result = evaluate_binance_live_operations(
            artifacts_dir=self.root,
            env=self._env(
                BINANCE_LIVE_MODE=MODE_SCHEDULED_WINDOW,
                BINANCE_LIVE_START_TIME_UTC='11:00',
                BINANCE_LIVE_END_TIME_UTC='13:00',
            ),
            now=self.now,
        )
        self.assertFalse(result['can_scheduled_trade'])
        self.assertIn('live_scheduled_window_not_enabled', result['blocking_reasons'])
        self.assertTrue(result['can_prepare'])

    def test_halted_blocks_everything(self) -> None:
        halt_binance_live_operations(artifacts_dir=self.root, reason='ops')
        result = evaluate_binance_live_operations(artifacts_dir=self.root, env=self._env(BINANCE_LIVE_MODE=MODE_ARMED_MANUAL), now=self.now)
        self.assertFalse(result['ok'])
        self.assertIn('live_halt_state_active', result['blocking_reasons'])

    def test_daily_order_cap_blocks(self) -> None:
        self._write(
            self.root / 'binance_live_micro_submit_result.json',
            {
                'daily_cap_consumed': True,
                'daily_cap_reason': 'placed_count=1',
                'requested_notional': 5.0,
                'heartbeat': {'last_updated_at': self.now.isoformat()},
            },
        )
        result = evaluate_binance_live_operations(artifacts_dir=self.root, env=self._env(), now=self.now)
        self.assertIn('live_max_daily_orders_reached', result['blocking_reasons'])

    def test_daily_notional_cap_blocks(self) -> None:
        self._write(
            self.root / 'binance_live_micro_submit_result.json',
            {
                'daily_cap_consumed': True,
                'daily_cap_reason': 'placed_count=1',
                'requested_notional': 5.0,
                'heartbeat': {'last_updated_at': self.now.isoformat()},
            },
        )
        result = evaluate_binance_live_operations(
            artifacts_dir=self.root,
            env=self._env(BINANCE_LIVE_MAX_DAILY_NOTIONAL='5'),
            now=self.now,
        )
        self.assertIn('live_max_daily_notional_reached', result['blocking_reasons'])
        self.assertEqual(result['remaining_daily_notional'], 0.0)

    def test_insufficient_balance_blocks_and_budget_uses_min(self) -> None:
        self._write_readonly(quote_free='4.0')
        result = evaluate_binance_live_operations(artifacts_dir=self.root, env=self._env(), now=self.now)
        self.assertIn('live_insufficient_quote_balance_precheck', result['blocking_reasons'])
        self.assertEqual(result['effective_order_budget'], 3.96)

    def test_previous_error_requires_manual_review(self) -> None:
        self._write(
            self.root / 'binance_live_micro_submit_result.json',
            {
                'status': 'ERROR',
                'exchange_order_request_sent': True,
                'daily_cap_consumed': True,
                'daily_cap_reason': 'exchange_order_request_sent',
                'requested_notional': 5.0,
                'heartbeat': {'last_updated_at': self.now.isoformat()},
            },
        )
        result = evaluate_binance_live_operations(artifacts_dir=self.root, env=self._env(), now=self.now)
        self.assertIn('previous_live_error_requires_manual_review', result['blocking_reasons'])

    def test_ambiguous_artifact_blocks(self) -> None:
        self._write(
            self.root / 'binance_live_micro_submit_result.json',
            {
                'daily_cap_consumed': True,
                'heartbeat': {'last_updated_at': self.now.isoformat()},
            },
        )
        result = evaluate_binance_live_operations(artifacts_dir=self.root, env=self._env(), now=self.now)
        self.assertIn('live_daily_usage_ambiguous', result['blocking_reasons'])
