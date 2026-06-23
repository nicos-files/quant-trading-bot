from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.binance_testnet_executor import (
    ALLOWED_SYMBOLS_ENV,
    BASE_URL_ENV,
    CONFIRM_SUBMIT_ENV,
    ENABLE_FLAG,
    MAX_NOTIONAL_ENV,
    MAX_OPEN_ORDERS_ENV,
    ORDER_TEST_ONLY_FLAG,
)
from src.execution.binance_testnet_smoke_submit import run_binance_testnet_smoke_submit


class _FakeClient:
    def __init__(
        self,
        *,
        exchange_info_response: dict[str, Any] | None = None,
        server_time_response: dict[str, Any] | None = None,
        account_response: dict[str, Any] | None = None,
        account_sequence: list[dict[str, Any]] | None = None,
        open_orders_response: list[dict[str, Any]] | None = None,
        open_orders_sequence: list[list[dict[str, Any]]] | None = None,
        place_order_response: dict[str, Any] | None = None,
        exchange_info_raises: BaseException | None = None,
        server_time_raises: BaseException | None = None,
        account_raises: BaseException | None = None,
        open_orders_raises: BaseException | None = None,
        place_order_raises: BaseException | None = None,
        api_key_masked: str = '****abcd',
    ) -> None:
        self.exchange_info_calls: list[tuple[str, ...] | None] = []
        self.server_time_calls = 0
        self.account_calls = 0
        self.open_orders_calls = 0
        self.place_order_calls: list[Mapping[str, Any]] = []
        self._exchange_info_response = exchange_info_response or {
            'symbols': [
                {
                    'symbol': 'BTCUSDT',
                    'filters': [
                        {'filterType': 'PRICE_FILTER', 'minPrice': '0.01', 'maxPrice': '1000000', 'tickSize': '0.01'},
                        {'filterType': 'LOT_SIZE', 'minQty': '0.000001', 'maxQty': '1000', 'stepSize': '0.000001'},
                        {'filterType': 'MARKET_LOT_SIZE', 'minQty': '0.000001', 'maxQty': '1000', 'stepSize': '0.000001'},
                        {'filterType': 'MIN_NOTIONAL', 'minNotional': '5.0'},
                    ],
                }
            ]
        }
        self._server_time_response = server_time_response or {
            'serverTime': int(datetime(2026, 6, 23, 17, 10, tzinfo=timezone.utc).timestamp() * 1000),
        }
        self._account_response = account_response or {
            'balances': [
                {'asset': 'BTC', 'free': '1.0', 'locked': '0.0'},
                {'asset': 'USDT', 'free': '10000.0', 'locked': '0.0'},
            ]
        }
        self._account_sequence = [dict(item) for item in account_sequence] if account_sequence is not None else None
        self._open_orders_response = open_orders_response or []
        self._open_orders_sequence = [list(item) for item in open_orders_sequence] if open_orders_sequence is not None else None
        self._place_order_response = place_order_response or {
            'orderId': 8339739,
            'clientOrderId': 'tnsmk-from-broker',
            'status': 'FILLED',
            'transactTime': int(datetime(2026, 6, 23, 18, 9, tzinfo=timezone.utc).timestamp() * 1000),
            'executedQty': '0.00008',
            'cummulativeQuoteQty': '4.98416',
            'fills': [
                {
                    'price': '62302.0',
                    'qty': '0.00008',
                    'commission': '0.0',
                    'commissionAsset': 'BTC',
                }
            ],
        }
        self._exchange_info_raises = exchange_info_raises
        self._server_time_raises = server_time_raises
        self._account_raises = account_raises
        self._open_orders_raises = open_orders_raises
        self._place_order_raises = place_order_raises
        self.api_key_masked = api_key_masked

    def exchange_info(self, symbols: list[str] | None = None) -> dict[str, Any]:
        if self._exchange_info_raises is not None:
            raise self._exchange_info_raises
        self.exchange_info_calls.append(tuple(symbols) if symbols is not None else None)
        return dict(self._exchange_info_response)

    def server_time(self) -> dict[str, Any]:
        if self._server_time_raises is not None:
            raise self._server_time_raises
        self.server_time_calls += 1
        return dict(self._server_time_response)

    def account(self) -> dict[str, Any]:
        if self._account_raises is not None:
            raise self._account_raises
        self.account_calls += 1
        if self._account_sequence is not None and self._account_sequence:
            if len(self._account_sequence) > 1:
                return dict(self._account_sequence.pop(0))
            return dict(self._account_sequence[0])
        return dict(self._account_response)

    def open_orders(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
        if self._open_orders_raises is not None:
            raise self._open_orders_raises
        self.open_orders_calls += 1
        if self._open_orders_sequence is not None and self._open_orders_sequence:
            if len(self._open_orders_sequence) > 1:
                payload = self._open_orders_sequence.pop(0)
            else:
                payload = self._open_orders_sequence[0]
        else:
            payload = self._open_orders_response
        if symbol is None:
            return [dict(item) for item in payload]
        return [dict(item) for item in payload if str(item.get('symbol') or '').upper() == str(symbol).upper()]

    def place_order(self, *, params: Mapping[str, Any]) -> dict[str, Any]:
        if self._place_order_raises is not None:
            raise self._place_order_raises
        self.place_order_calls.append(dict(params))
        return dict(self._place_order_response)


def _smoke_env(**overrides: str) -> dict[str, str]:
    base = {
        ENABLE_FLAG: '1',
        ORDER_TEST_ONLY_FLAG: '0',
        CONFIRM_SUBMIT_ENV: 'YES',
        BASE_URL_ENV: 'https://testnet.binance.vision',
        ALLOWED_SYMBOLS_ENV: 'BTCUSDT',
        MAX_OPEN_ORDERS_ENV: '1',
        MAX_NOTIONAL_ENV: '25',
    }
    base.update(overrides)
    return base


class BinanceTestnetSmokeSubmitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.paper_dir = self.root / 'crypto_paper'
        self.testnet_dir = self.root / 'crypto_testnet'
        self.ops_dir = self.root / 'crypto_ops'
        self.paper_dir.mkdir(parents=True, exist_ok=True)
        self.testnet_dir.mkdir(parents=True, exist_ok=True)
        self.ops_dir.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 6, 23, 17, 10, tzinfo=timezone.utc)
        self._seed_ready_state()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding='utf-8')

    def _seed_ready_state(self, *, readiness_status: str = 'READY', final_decision: str = 'TESTNET_SUBMIT_ALLOWED', blocking_reasons: list[str] | None = None) -> None:
        self._write(
            self.testnet_dir / 'crypto_testnet_readiness.json',
            {
                'status': readiness_status,
                'dry_run_ready': readiness_status == 'READY',
                'submit_ready': readiness_status == 'READY',
                'warnings': [] if readiness_status == 'READY' else ['not ready'],
            },
        )
        self._write(
            self.ops_dir / 'crypto_operational_status.json',
            {
                'final_decision': final_decision,
                'blocking_reasons': list(blocking_reasons or []),
                'dry_run_ready': True,
                'submit_ready': final_decision == 'TESTNET_SUBMIT_ALLOWED' and not blocking_reasons,
            },
        )
        self._write(
            self.testnet_dir / 'binance_testnet_exchange_state.json',
            {
                'mismatches': [],
                'mismatch_details': [],
                'reconciliation_summary': {
                    'count': 0,
                    'blocking_count': 0,
                    'highest_severity': 'INFO',
                    'counts_by_severity': {'INFO': 0, 'WARNING': 0, 'ERROR': 0, 'CRITICAL': 0},
                    'counts_by_level': {'tolerable_drift': 0, 'warning': 0, 'error': 0, 'critical_hard_stop': 0},
                },
            },
        )

    def _baseline_account_sequence(self) -> list[dict[str, Any]]:
        return [
            {
                'balances': [
                    {'asset': 'BTC', 'free': '1.0', 'locked': '0.0'},
                    {'asset': 'USDT', 'free': '10000.0', 'locked': '0.0'},
                ]
            },
            {
                'balances': [
                    {'asset': 'BTC', 'free': '1.00008', 'locked': '0.0'},
                    {'asset': 'USDT', 'free': '9995.01584', 'locked': '0.0'},
                ]
            },
        ]

    def test_blocks_without_confirm_yes(self) -> None:
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(**{CONFIRM_SUBMIT_ENV: 'NO'}),
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('missing_binance_testnet_confirm_submit', result['reason'])

    def test_blocks_when_order_test_only_is_one(self) -> None:
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(**{ORDER_TEST_ONLY_FLAG: '1'}),
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'smoke_submit_requires_order_test_only_zero')

    def test_blocks_on_wrong_base_url(self) -> None:
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(**{BASE_URL_ENV: 'https://api.binance.com'}),
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('non-testnet', result['reason'])

    def test_blocks_when_readiness_not_ready(self) -> None:
        self._seed_ready_state(readiness_status='NOT_READY')
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(),
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('submit_readiness_not_ready', result['reason'])

    def test_blocks_when_operational_decision_not_allowed(self) -> None:
        self._seed_ready_state(final_decision='DO_NOT_RUN')
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(),
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('submit_operational_decision_blocked', result['reason'])

    def test_blocks_when_operational_blocking_reasons_present(self) -> None:
        self._seed_ready_state(blocking_reasons=['semantic_status:ERROR'])
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(),
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('submit_operational_blocking_reasons_present', result['reason'])

    def test_respects_max_notional_cap(self) -> None:
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(**{MAX_NOTIONAL_ENV: '30'}),
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('smoke_submit_max_notional_out_of_bounds', result['reason'])

    def test_respects_allowed_symbol_restriction(self) -> None:
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(**{ALLOWED_SYMBOLS_ENV: 'BTCUSDT,ETHUSDT'}),
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'smoke_submit_requires_allowed_symbols_btcusdt_only')

    def test_respects_max_open_orders_requirement(self) -> None:
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(**{MAX_OPEN_ORDERS_ENV: '2'}),
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'smoke_submit_requires_max_open_orders_equals_1')

    def test_preexisting_btc_balance_uses_delta_reconciliation_not_absolute_balance(self) -> None:
        client = _FakeClient(
            account_sequence=self._baseline_account_sequence(),
            open_orders_sequence=[[], [], []],
        )
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(),
            client=client,
            now=self.now,
        )
        self.assertTrue(result['ok'])
        self.assertTrue(result['preexisting_balance_detected'])
        self.assertEqual(result['delta_reconciliation_summary']['count'], 0)
        self.assertEqual(result['reconciliation_summary']['count'], 0)
        self.assertEqual(result['blocking_reasons'], [])
        self.assertAlmostEqual(result['expected_delta']['base_qty'], 0.00008, places=12)
        self.assertAlmostEqual(result['observed_delta']['base_qty'], 0.00008, places=12)
        self.assertIn('baseline_external_balance_detected:BTC:1.000000000000', result['warnings'])

    def test_delta_mismatch_is_critical(self) -> None:
        client = _FakeClient(
            account_sequence=[
                self._baseline_account_sequence()[0],
                {
                    'balances': [
                        {'asset': 'BTC', 'free': '1.00009', 'locked': '0.0'},
                        {'asset': 'USDT', 'free': '9995.01584', 'locked': '0.0'},
                    ]
                },
            ],
            open_orders_sequence=[[], [], []],
        )
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(),
            client=client,
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('post_submit_reconciliation_mismatch', result['reason'])
        self.assertEqual(result['severity'], 'CRITICAL')
        self.assertTrue(any(item['code'] == 'base_delta_mismatch' for item in result['delta_reconciliation_mismatch_details']))

    def test_open_order_unexpected_after_submit_is_critical(self) -> None:
        client = _FakeClient(
            account_sequence=self._baseline_account_sequence(),
            open_orders_sequence=[
                [],
                [],
                [{'symbol': 'BTCUSDT', 'clientOrderId': 'tnsmk-x', 'status': 'NEW', 'side': 'BUY', 'type': 'MARKET', 'origQty': '0.00008', 'executedQty': '0.0'}],
            ],
        )
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(),
            client=client,
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertIn('unexpected_open_orders_after_submit', result['reason'])

    def test_rejected_order_is_critical(self) -> None:
        client = _FakeClient(
            account_sequence=self._baseline_account_sequence(),
            open_orders_sequence=[[], [], []],
            place_order_response={
                'orderId': 8339739,
                'clientOrderId': 'tnsmk-from-broker',
                'status': 'REJECTED',
                'fills': [],
            },
        )
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(),
            client=client,
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'smoke_submit_missing_fill')
        self.assertEqual(result['severity'], 'CRITICAL')

    def test_missing_fill_is_critical(self) -> None:
        client = _FakeClient(
            account_sequence=self._baseline_account_sequence(),
            open_orders_sequence=[[], [], []],
            place_order_response={
                'orderId': 8339739,
                'clientOrderId': 'tnsmk-from-broker',
                'status': 'FILLED',
                'cummulativeQuoteQty': '4.98416',
                'fills': [],
            },
        )
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(),
            client=client,
            now=self.now,
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'smoke_submit_missing_fill')
        self.assertEqual(result['severity'], 'CRITICAL')

    def test_successful_smoke_submit_writes_redacted_artifact(self) -> None:
        client = _FakeClient(
            account_sequence=self._baseline_account_sequence(),
            open_orders_sequence=[[], [], []],
        )
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(),
            client=client,
            now=self.now,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(result['placed_count'], 1)
        self.assertEqual(result['rejected_count'], 0)
        self.assertTrue(result['submit_attempted'])
        self.assertEqual(len(client.place_order_calls), 1)
        self.assertEqual(client.place_order_calls[0]['symbol'], 'BTCUSDT')
        self.assertEqual(client.place_order_calls[0]['side'], 'BUY')
        self.assertIn('quoteOrderQty', client.place_order_calls[0])
        self.assertEqual(client.exchange_info_calls, [('BTCUSDT',)])
        persisted = json.loads((self.testnet_dir / 'binance_testnet_smoke_submit_result.json').read_text(encoding='utf-8'))
        self.assertTrue(persisted['ok'])
        self.assertNotIn('secret', json.dumps(persisted).lower())
        self.assertIn('pre_submit_exchange_state', persisted)
        self.assertIn('post_submit_exchange_state', persisted)
        self.assertIn('baseline_balances', persisted)
        self.assertIn('expected_delta', persisted)
        self.assertIn('observed_delta', persisted)
        self.assertIn('delta_reconciliation_summary', persisted)

    def test_smoke_submit_does_not_depend_on_semantic_events(self) -> None:
        semantic_dir = self.paper_dir / 'semantic'
        semantic_dir.mkdir(parents=True, exist_ok=True)
        (semantic_dir / 'crypto_semantic_events.json').write_text('[{"event_type":"BUY_FILLED_PAPER"}]', encoding='utf-8')
        (semantic_dir / 'crypto_semantic_summary.json').write_text('{"operational_status":"ERROR"}', encoding='utf-8')
        client = _FakeClient(
            account_sequence=self._baseline_account_sequence(),
            open_orders_sequence=[[], [], []],
        )
        result = run_binance_testnet_smoke_submit(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_smoke_env(),
            client=client,
            now=self.now,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(len(client.place_order_calls), 1)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
