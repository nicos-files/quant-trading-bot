from __future__ import annotations

import sys
import unittest
from pathlib import Path

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

    def test_place_order_hits_mainnet_order_endpoint(self) -> None:
        client = self._client()
        captured: dict[str, object] = {}

        def fake_signed_json(method, path, params=None):  # noqa: ANN001
            captured['method'] = method
            captured['path'] = path
            captured['params'] = dict(params or {})
            return {'orderId': 1, 'status': 'FILLED', 'fills': []}

        client._signed_json = fake_signed_json  # type: ignore[method-assign]
        client.place_order(params={'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'MARKET', 'quoteOrderQty': '5'})
        self.assertEqual(captured['method'], 'POST')
        self.assertEqual(captured['path'], '/api/v3/order')
        self.assertFalse(hasattr(client, 'order_test'))