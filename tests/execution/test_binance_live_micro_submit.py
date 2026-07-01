from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.binance_live_micro_submit import run_binance_live_micro_submit
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


class _FakeClient:
    def __init__(
        self,
        *,
        exchange_info_response: dict[str, Any] | None = None,
        server_time_response: dict[str, Any] | None = None,
        account_sequence: list[dict[str, Any]] | None = None,
        open_orders_sequence: list[list[dict[str, Any]]] | None = None,
        place_order_response: dict[str, Any] | None = None,
        place_order_raises: BaseException | None = None,
        api_key_masked: str = '****live',
    ) -> None:
        self.exchange_info_calls: list[tuple[str, ...] | None] = []
        self.server_time_calls = 0
        self.account_calls = 0
        self.open_orders_calls = 0
        self.place_order_calls: list[dict[str, Any]] = []
        self._exchange_info_response = exchange_info_response or {
            'symbols': [
                {
                    'symbol': 'BTCUSDT',
                    'filters': [
                        {'filterType': 'PRICE_FILTER', 'tickSize': '0.01'},
                        {'filterType': 'LOT_SIZE', 'stepSize': '0.000001', 'minQty': '0.000001', 'maxQty': '1000'},
                        {'filterType': 'MARKET_LOT_SIZE', 'stepSize': '0.000001', 'minQty': '0.000001', 'maxQty': '1000'},
                        {'filterType': 'MIN_NOTIONAL', 'minNotional': '5.0'},
                    ],
                }
            ]
        }
        self._server_time_response = server_time_response or {
            'serverTime': int(datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
        }
        self._account_sequence = [dict(item) for item in (account_sequence or [
            {'balances': [{'asset': 'BTC', 'free': '1.0', 'locked': '0.0'}, {'asset': 'USDT', 'free': '10000.0', 'locked': '0.0'}]},
            {'balances': [{'asset': 'BTC', 'free': '1.00008', 'locked': '0.0'}, {'asset': 'USDT', 'free': '9995.01584', 'locked': '0.0'}]},
        ])]
        self._open_orders_sequence = [list(item) for item in (open_orders_sequence or [[], []])]
        self._place_order_response = place_order_response or {
            'orderId': 12345,
            'clientOrderId': 'live-broker-id',
            'status': 'FILLED',
            'executedQty': '0.00008',
            'cummulativeQuoteQty': '4.98416',
            'fills': [
                {'price': '62302.0', 'qty': '0.00008', 'commission': '0.0', 'commissionAsset': 'BTC'}
            ],
        }
        self._place_order_raises = place_order_raises
        self.api_key_masked = api_key_masked

    def exchange_info(self, symbols: list[str] | None = None) -> dict[str, Any]:
        self.exchange_info_calls.append(tuple(symbols) if symbols is not None else None)
        return dict(self._exchange_info_response)

    def server_time(self) -> dict[str, Any]:
        self.server_time_calls += 1
        return dict(self._server_time_response)

    def account(self) -> dict[str, Any]:
        self.account_calls += 1
        if len(self._account_sequence) > 1:
            return dict(self._account_sequence.pop(0))
        return dict(self._account_sequence[0])

    def open_orders(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
        self.open_orders_calls += 1
        if len(self._open_orders_sequence) > 1:
            payload = self._open_orders_sequence.pop(0)
        else:
            payload = self._open_orders_sequence[0]
        if symbol is None:
            return [dict(item) for item in payload]
        return [dict(item) for item in payload if str(item.get('symbol') or '').upper() == str(symbol).upper()]

    def place_order(self, *, params: dict[str, Any]) -> dict[str, Any]:
        if self._place_order_raises is not None:
            raise self._place_order_raises
        self.place_order_calls.append(dict(params))
        return dict(self._place_order_response)


def _live_env(**overrides: str) -> dict[str, str]:
    base = {
        'BINANCE_LIVE_TRADING_ENABLED': '1',
        'BINANCE_LIVE_CONFIRM_SUBMIT': 'YES',
        'BINANCE_LIVE_KILL_SWITCH': '0',
        'BINANCE_LIVE_BASE_URL': 'https://api.binance.com',
        'BINANCE_LIVE_ALLOWED_SYMBOLS': 'BTCUSDT',
        'BINANCE_LIVE_MAX_NOTIONAL': '5',
        'BINANCE_LIVE_MAX_DAILY_ORDERS': '1',
        'BINANCE_LIVE_MAX_OPEN_ORDERS': '1',
        'BINANCE_LIVE_MODE': 'SINGLE_SHOT',
        'BINANCE_LIVE_ARM_TOKEN': 'ARMED',
        'BINANCE_LIVE_API_KEY': 'live-key',
        'BINANCE_LIVE_API_SECRET': 'live-secret',
        'BINANCE_MAINNET_API_KEY': 'readonly-key',
        'BINANCE_MAINNET_API_SECRET': 'readonly-secret',
    }
    base.update(overrides)
    return base


class BinanceLiveMicroSubmitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / ARTIFACTS_SUBDIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
        self._write_readonly(ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding='utf-8')

    def _write_readonly(self, *, ok: bool = True, heartbeat_offset_minutes: int = 0, base_url: str = 'https://api.binance.com', reconciliation_blocking_count: int = 0) -> None:
        stamp = (self.now - timedelta(minutes=heartbeat_offset_minutes)).isoformat()
        self._write(
            self.root / 'binance_mainnet_readonly_preflight.json',
            {
                'ok': ok,
                'status': 'SUCCESS' if ok else 'ERROR',
                'base_url': base_url,
                'live_trading_enabled': False,
                'live_kill_switch_active': True,
                'server_time_available': True,
                'exchange_filters_available': True,
                'account_checked': True,
                'balances_checked': True,
                'open_orders_checked': True,
                'reconciliation_summary': {
                    'count': reconciliation_blocking_count,
                    'blocking_count': reconciliation_blocking_count,
                    'highest_severity': 'ERROR' if reconciliation_blocking_count else 'INFO',
                    'counts_by_severity': {'INFO': 0, 'WARNING': 0, 'ERROR': reconciliation_blocking_count, 'CRITICAL': 0},
                    'counts_by_level': {'tolerable_drift': 0, 'warning': 0, 'error': reconciliation_blocking_count, 'critical_hard_stop': 0},
                },
                'blocking_reasons': [] if ok and reconciliation_blocking_count == 0 else ['readonly_problem'],
                'heartbeat': {'last_updated_at': stamp},
                'warnings': ['live_kill_switch_active_default_on'],
            },
        )

    def test_default_without_execute_stays_prepare_only(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), now=self.now)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'PREPARED')
        self.assertTrue(result['prepare_only'])
        self.assertFalse(result['execute'])
        self.assertFalse(result['submit_attempted'])

    def test_prepare_only_flag_does_not_execute(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), now=self.now, prepare_only=True)
        self.assertTrue(result['ok'])
        self.assertFalse(result['submit_attempted'])
        self.assertIn('prepare_only_no_live_order_executed', result['warnings'])

    def test_prepare_only_and_execute_together_block(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), now=self.now, prepare_only=True, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('prepare_only_and_execute_mutually_exclusive', result['blocking_reasons'])

    def test_prepare_only_blocks_when_live_mode_is_off(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_MODE='OFF'), now=self.now, prepare_only=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_mode_off', result['blocking_reasons'])

    def test_prepare_only_blocks_when_live_mode_is_read_only(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_MODE='READ_ONLY'), now=self.now, prepare_only=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_operations_prepare_not_allowed:READ_ONLY', result['blocking_reasons'])

    def test_prepare_only_allowed_in_armed_manual_mode(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_MODE='ARMED_MANUAL', BINANCE_LIVE_TRADING_ENABLED='0', BINANCE_LIVE_CONFIRM_SUBMIT='NO'), now=self.now, prepare_only=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'PREPARED')

    def test_execute_blocks_in_armed_manual_mode(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_MODE='ARMED_MANUAL'), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_mode_armed_manual_execute_blocked', result['blocking_reasons'])

    def test_execute_blocks_in_scheduled_window_outside_window(self) -> None:
        result = run_binance_live_micro_submit(
            artifacts_dir=self.root,
            env=_live_env(BINANCE_LIVE_MODE='SCHEDULED_WINDOW', BINANCE_LIVE_START_TIME_UTC='13:00', BINANCE_LIVE_END_TIME_UTC='14:00'),
            now=self.now,
            execute=True,
        )
        self.assertFalse(result['ok'])
        self.assertIn('live_mode_scheduled_window_execute_blocked', result['blocking_reasons'])

    def test_execute_allows_scheduled_window_inside_window(self) -> None:
        client = _FakeClient()
        result = run_binance_live_micro_submit(
            artifacts_dir=self.root,
            env=_live_env(BINANCE_LIVE_MODE='SCHEDULED_WINDOW', BINANCE_LIVE_START_TIME_UTC='11:00', BINANCE_LIVE_END_TIME_UTC='13:00'),
            client=client,
            now=self.now,
            execute=True,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(len(client.place_order_calls), 1)

    def test_execute_blocks_when_live_mode_is_halted(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_MODE='HALTED'), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_mode_halted', result['blocking_reasons'])

    def test_execute_blocks_without_live_trading_enabled(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_TRADING_ENABLED='0'), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_trading_enabled_flag_required', result['blocking_reasons'])

    def test_execute_blocks_without_confirm_yes(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_CONFIRM_SUBMIT='NO'), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_confirm_submit_yes_required', result['blocking_reasons'])

    def test_execute_blocks_with_kill_switch_on(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_KILL_SWITCH='1'), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_kill_switch_must_be_zero_for_submit', result['blocking_reasons'])

    def test_execute_blocks_with_wrong_base_url(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_BASE_URL='https://testnet.binance.vision'), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_base_url_must_be_api_binance_com', result['blocking_reasons'])

    def test_execute_blocks_with_max_notional_over_five(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_MAX_NOTIONAL='6'), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_max_notional_must_be_between_0_and_5', result['blocking_reasons'])

    def test_execute_blocks_with_max_daily_orders_over_one(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_MAX_DAILY_ORDERS='2'), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_max_daily_orders_must_equal_1', result['blocking_reasons'])

    def test_execute_blocks_with_max_open_orders_over_one(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_MAX_OPEN_ORDERS='2'), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_max_open_orders_must_equal_1', result['blocking_reasons'])

    def test_execute_blocks_with_non_btc_symbol_allowlist(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_ALLOWED_SYMBOLS='ETHUSDT'), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_allowed_symbols_must_be_btcusdt_only', result['blocking_reasons'])

    def test_execute_blocks_when_live_credentials_missing(self) -> None:
        result = run_binance_live_micro_submit(
            artifacts_dir=self.root,
            env=_live_env(BINANCE_LIVE_API_KEY='', BINANCE_LIVE_API_SECRET=''),
            now=self.now,
            execute=True,
        )
        self.assertFalse(result['ok'])
        self.assertIn('missing_live_api_key', result['blocking_reasons'])
        self.assertIn('missing_live_api_secret', result['blocking_reasons'])

    def test_execute_blocks_when_reusing_readonly_key(self) -> None:
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(BINANCE_LIVE_API_KEY='readonly-key'), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_api_key_must_not_reuse_mainnet_readonly_key', result['blocking_reasons'])

    def test_execute_blocks_when_readonly_artifact_is_missing(self) -> None:
        (self.root / 'binance_mainnet_readonly_preflight.json').unlink()
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('mainnet_readonly_artifact_missing_or_unreadable', result['blocking_reasons'])

    def test_execute_blocks_when_readonly_artifact_is_stale(self) -> None:
        self._write_readonly(heartbeat_offset_minutes=31)
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('mainnet_readonly_artifact_stale', result['blocking_reasons'])

    def test_execute_blocks_when_quote_balance_is_insufficient_precheck(self) -> None:
        client = _FakeClient(
            account_sequence=[
                {'balances': [{'asset': 'BTC', 'free': '1.0', 'locked': '0.0'}, {'asset': 'USDT', 'free': '5.0', 'locked': '0.0'}]},
            ]
        )
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), client=client, now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['failure_stage'], 'pre_exchange_balance_validation')
        self.assertIn('live_insufficient_quote_balance_precheck', result['blocking_reasons'])
        self.assertFalse(result['submit_attempted'])
        self.assertFalse(result['broker_order_request_attempted'])
        self.assertFalse(result['exchange_order_request_sent'])
        self.assertFalse(result['daily_cap_consumed'])
        self.assertEqual(result['daily_cap_reason'], 'not_submitted')
        self.assertEqual(result['quote_asset'], 'USDT')
        self.assertEqual(result['quote_free_balance'], 5.0)
        self.assertEqual(result['required_quote_balance'], 5.05)
        self.assertFalse(result['balance_precheck_ok'])
        self.assertEqual(len(client.place_order_calls), 0)

    def test_execute_blocks_when_quote_balance_precheck_is_unavailable(self) -> None:
        client = _FakeClient(
            account_sequence=[
                {'balances': [{'asset': 'BTC', 'free': '1.0', 'locked': '0.0'}]},
            ]
        )
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), client=client, now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['failure_stage'], 'pre_exchange_balance_validation')
        self.assertIn('live_quote_balance_precheck_unavailable', result['blocking_reasons'])
        self.assertFalse(result['submit_attempted'])
        self.assertFalse(result['broker_order_request_attempted'])
        self.assertFalse(result['exchange_order_request_sent'])
        self.assertFalse(result['daily_cap_consumed'])
        self.assertEqual(len(client.place_order_calls), 0)

    def test_execute_blocks_when_prior_live_order_consumed_daily_cap(self) -> None:
        self._write(
            self.root / 'binance_live_micro_submit_result.json',
            {
                'submit_attempted': True,
                'exchange_order_request_sent': True,
                'placed_count': 1,
                'daily_cap_consumed': True,
                'daily_cap_reason': 'placed_count=1',
                'heartbeat': {'last_updated_at': self.now.isoformat()},
            },
        )
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_daily_order_cap_reached:1>=1', result['blocking_reasons'])
        self.assertTrue(result['daily_order_cap']['history_consumed_cap'])
        self.assertEqual(result['daily_order_cap']['history_consumed_reason'], 'placed_count=1')

    def test_execute_does_not_consume_daily_cap_for_prior_pre_exchange_allowlist_failure(self) -> None:
        self._write(
            self.root / 'binance_live_micro_submit_result.json',
            {
                'submit_attempted': True,
                'broker_order_request_attempted': True,
                'exchange_order_request_sent': False,
                'placed_count': 0,
                'rejected_count': 0,
                'failure_stage': 'pre_exchange_client_validation',
                'blocking_reasons': ["live_submit_failed:Endpoint not in readonly allowlist: '/api/v3/order'"],
                'heartbeat': {'last_updated_at': self.now.isoformat()},
            },
        )
        client = _FakeClient()
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), client=client, now=self.now, execute=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(len(client.place_order_calls), 1)
        self.assertIn('daily_cap_not_consumed_pre_exchange_failure', ' '.join(result['warnings']))
        self.assertFalse(result['daily_order_cap']['history_consumed_cap'])

    def test_execute_does_not_consume_daily_cap_for_prior_non_submit_artifact(self) -> None:
        self._write(
            self.root / 'binance_live_micro_submit_result.json',
            {
                'submit_attempted': False,
                'placed_count': 0,
                'rejected_count': 0,
                'heartbeat': {'last_updated_at': self.now.isoformat()},
            },
        )
        client = _FakeClient()
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), client=client, now=self.now, execute=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertFalse(result['daily_order_cap']['history_consumed_cap'])

    def test_execute_does_not_consume_daily_cap_for_prior_balance_precheck_failure(self) -> None:
        self._write(
            self.root / 'binance_live_micro_submit_result.json',
            {
                'submit_attempted': False,
                'broker_order_request_attempted': False,
                'exchange_order_request_sent': False,
                'placed_count': 0,
                'rejected_count': 0,
                'failure_stage': 'pre_exchange_balance_validation',
                'blocking_reasons': ['live_insufficient_quote_balance_precheck'],
                'heartbeat': {'last_updated_at': self.now.isoformat()},
            },
        )
        client = _FakeClient()
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), client=client, now=self.now, execute=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertFalse(result['daily_order_cap']['history_consumed_cap'])

    def test_execute_blocks_when_prior_exchange_reject_consumed_daily_cap(self) -> None:
        self._write(
            self.root / 'binance_live_micro_submit_result.json',
            {
                'submit_attempted': True,
                'broker_order_request_attempted': True,
                'exchange_order_request_sent': True,
                'placed_count': 0,
                'rejected_count': 1,
                'failure_stage': 'broker_submit_exception',
                'blocking_reasons': ['live_submit_failed:HTTP 400 calling /api/v3/order: {"code":-2010,"msg":"Account has insufficient balance for requested action."}'],
                'heartbeat': {'last_updated_at': self.now.isoformat()},
            },
        )
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_daily_order_cap_reached:1>=1', result['blocking_reasons'])
        self.assertTrue(result['daily_order_cap']['history_consumed_cap'])
        self.assertEqual(result['daily_order_cap']['history_consumed_reason'], 'prior_exchange_rejected_after_submit:1')

    def test_execute_blocks_when_prior_daily_cap_artifact_is_ambiguous(self) -> None:
        self._write(
            self.root / 'binance_live_micro_submit_result.json',
            {
                'submit_attempted': True,
                'placed_count': 0,
                'rejected_count': 0,
                'heartbeat': {'last_updated_at': self.now.isoformat()},
            },
        )
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_daily_order_history_ambiguous', result['blocking_reasons'])

    def test_execute_blocks_when_exchange_min_notional_exceeds_cap(self) -> None:
        client = _FakeClient(
            exchange_info_response={
                'symbols': [
                    {'symbol': 'BTCUSDT', 'filters': [{'filterType': 'MIN_NOTIONAL', 'minNotional': '10.0'}]}
                ]
            }
        )
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), client=client, now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('live_min_notional_exceeds_configured_cap:10.0>5.0', result['blocking_reasons'])

    def test_execute_constructs_live_trading_client_when_not_injected(self) -> None:
        fake_client = _FakeClient()
        with mock.patch('src.execution.binance_live_micro_submit.BinanceSpotMainnetClient', return_value=fake_client) as patched:
            result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), now=self.now, execute=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'SUCCESS')
        patched.assert_called_once()
        self.assertEqual(patched.call_args.kwargs['api_key'], 'live-key')
        self.assertEqual(patched.call_args.kwargs['api_secret'], 'live-secret')
        self.assertEqual(patched.call_args.kwargs['base_url'], 'https://api.binance.com')
        self.assertEqual(len(fake_client.place_order_calls), 1)

    def test_successful_mocked_execute_submits_once_and_reconciles_cleanly(self) -> None:
        client = _FakeClient()
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), client=client, now=self.now, execute=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertTrue(result['submit_attempted'])
        self.assertTrue(result['broker_order_request_attempted'])
        self.assertTrue(result['exchange_order_request_sent'])
        self.assertEqual(result['placed_count'], 1)
        self.assertEqual(result['rejected_count'], 0)
        self.assertEqual(result['quote_asset'], 'USDT')
        self.assertEqual(result['quote_free_balance'], 10000.0)
        self.assertEqual(result['required_quote_balance'], 5.05)
        self.assertTrue(result['balance_precheck_ok'])
        self.assertTrue(result['daily_cap_consumed'])
        self.assertEqual(result['daily_cap_reason'], 'placed_count=1')
        self.assertEqual(len(client.place_order_calls), 1)
        self.assertEqual(result['reconciliation_summary']['count'], 0)
        serialized = json.dumps(result).lower()
        self.assertNotIn('live-secret', serialized)
        self.assertNotIn('readonly-secret', serialized)

    def test_execute_blocks_when_fill_missing(self) -> None:
        client = _FakeClient(place_order_response={'orderId': 1, 'status': 'FILLED', 'cummulativeQuoteQty': '4.98', 'fills': []})
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), client=client, now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertTrue(result['exchange_order_request_sent'])
        self.assertTrue(result['daily_cap_consumed'])
        self.assertIn('live_submit_missing_fill', result['blocking_reasons'])

    def test_execute_blocks_when_post_submit_open_order_appears(self) -> None:
        client = _FakeClient(open_orders_sequence=[[], [{'symbol': 'BTCUSDT', 'status': 'NEW', 'type': 'LIMIT', 'side': 'BUY'}]])
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=_live_env(), client=client, now=self.now, execute=True)
        self.assertFalse(result['ok'])
        self.assertIn('unexpected_open_orders_after_submit:1', result['blocking_reasons'])
