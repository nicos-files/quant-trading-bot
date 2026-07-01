from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.brokers.binance_spot_mainnet import (
    DEFAULT_MAINNET_BASE_URL,
    BinanceMainnetConfigError,
    BinanceSpotMainnetClient,
    LIVE_API_KEY_ENV,
    LIVE_API_SECRET_ENV,
    is_mainnet_base_url,
    resolve_credentials,
)
from src.brokers.binance_spot_mainnet_readonly import (
    BinanceMainnetReadonlyConfigError,
    BinanceSpotMainnetReadonlyClient,
)


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode('utf-8')

    def __enter__(self) -> '_FakeResponse':
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class BinanceSpotMainnetClientTests(unittest.TestCase):
    def _client(self):
        return BinanceSpotMainnetClient(
            api_key='live-key-123456',
            api_secret='live-secret-123456',
            base_url=DEFAULT_MAINNET_BASE_URL,
        )

    def test_resolve_credentials_reads_live_env_only(self) -> None:
        key, secret = resolve_credentials(env={LIVE_API_KEY_ENV: 'k', LIVE_API_SECRET_ENV: 's'})
        self.assertEqual((key, secret), ('k', 's'))
        with self.assertRaises(BinanceMainnetConfigError):
            resolve_credentials(env={'BINANCE_MAINNET_API_KEY': 'wrong', 'BINANCE_MAINNET_API_SECRET': 'wrong'})

    def test_mainnet_base_url_rejects_testnet(self) -> None:
        self.assertTrue(is_mainnet_base_url('https://api.binance.com'))
        self.assertFalse(is_mainnet_base_url('https://testnet.binance.vision'))

    def test_readonly_client_blocks_order_endpoint(self) -> None:
        client = BinanceSpotMainnetReadonlyClient(
            api_key='readonly-key-123456',
            api_secret='readonly-secret-123456',
            base_url=DEFAULT_MAINNET_BASE_URL,
        )
        with self.assertRaises(BinanceMainnetReadonlyConfigError):
            client._signed_json('POST', '/api/v3/order', params={'symbol': 'BTCUSDT'})

    def test_live_client_can_reach_order_endpoint_without_readonly_allowlist(self) -> None:
        client = self._client()
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout):  # noqa: ANN001
            captured['url'] = req.full_url
            captured['method'] = req.get_method()
            captured['headers'] = dict(req.header_items())
            captured['timeout'] = timeout
            return _FakeResponse({'orderId': 1, 'status': 'FILLED', 'fills': []})

        with mock.patch('src.brokers.binance_spot_mainnet.request.urlopen', side_effect=fake_urlopen):
            payload = client.place_order(params={'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'MARKET', 'quoteOrderQty': '5'})

        self.assertEqual(payload['orderId'], 1)
        self.assertEqual(captured['method'], 'POST')
        self.assertIn('/api/v3/order?', str(captured['url']))
        lowered_headers = {str(key).lower(): value for key, value in dict(captured['headers']).items()}
        self.assertIn('x-mbx-apikey', lowered_headers)
        self.assertFalse(hasattr(client, 'order_test'))

