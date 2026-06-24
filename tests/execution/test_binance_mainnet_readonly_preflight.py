from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.binance_mainnet_readonly_preflight import (
    ARTIFACTS_SUBDIR,
    ENABLE_READONLY_ENV,
    LIVE_ALLOWED_SYMBOLS_ENV,
    LIVE_MAX_OPEN_ORDERS_ENV,
    LIVE_TRADING_ENABLED_ENV,
    MAINNET_BASE_URL_ENV,
    run_binance_mainnet_readonly_preflight,
)
from src.brokers.binance_spot_mainnet_readonly import BinanceMainnetReadonlyRequestError


class _FakeClient:
    def __init__(
        self,
        *,
        server_time_response: dict[str, Any] | None = None,
        exchange_info_response: dict[str, Any] | None = None,
        account_response: dict[str, Any] | None = None,
        open_orders_response: list[dict[str, Any]] | None = None,
        server_time_raises: BaseException | None = None,
        exchange_info_raises: BaseException | None = None,
        account_raises: BaseException | None = None,
        open_orders_raises: BaseException | None = None,
        api_key_masked: str = "****abcd",
    ) -> None:
        self.server_time_calls = 0
        self.exchange_info_calls: list[tuple[str, ...] | None] = []
        self.account_calls = 0
        self.open_orders_calls = 0
        self.place_order_calls = 0
        self.order_test_calls = 0
        self._server_time_response = server_time_response or {"serverTime": int(datetime(2026, 6, 23, 23, 0, tzinfo=timezone.utc).timestamp() * 1000)}
        self._exchange_info_response = exchange_info_response or {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {"filterType": "LOT_SIZE", "stepSize": "0.000001"},
                        {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                    ],
                }
            ]
        }
        self._account_response = account_response or {
            "canTrade": True,
            "makerCommission": 10,
            "takerCommission": 10,
            "balances": [
                {"asset": "BTC", "free": "1.0", "locked": "0.0"},
                {"asset": "USDT", "free": "1000.0", "locked": "0.0"},
            ],
        }
        self._open_orders_response = open_orders_response or []
        self._server_time_raises = server_time_raises
        self._exchange_info_raises = exchange_info_raises
        self._account_raises = account_raises
        self._open_orders_raises = open_orders_raises
        self.api_key_masked = api_key_masked

    def server_time(self) -> dict[str, Any]:
        if self._server_time_raises is not None:
            raise self._server_time_raises
        self.server_time_calls += 1
        return dict(self._server_time_response)

    def exchange_info(self, symbols: list[str] | None = None) -> dict[str, Any]:
        if self._exchange_info_raises is not None:
            raise self._exchange_info_raises
        self.exchange_info_calls.append(tuple(symbols) if symbols is not None else None)
        return dict(self._exchange_info_response)

    def account(self) -> dict[str, Any]:
        if self._account_raises is not None:
            raise self._account_raises
        self.account_calls += 1
        return dict(self._account_response)

    def open_orders(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
        if self._open_orders_raises is not None:
            raise self._open_orders_raises
        self.open_orders_calls += 1
        if symbol is None:
            return [dict(item) for item in self._open_orders_response]
        return [dict(item) for item in self._open_orders_response if str(item.get("symbol") or "").upper() == str(symbol).upper()]

    def place_order(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        self.place_order_calls += 1
        raise AssertionError("readonly preflight must never call place_order")

    def order_test(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        self.order_test_calls += 1
        raise AssertionError("readonly preflight must never call order_test")


def _mainnet_env(**overrides: str) -> dict[str, str]:
    base = {
        ENABLE_READONLY_ENV: "1",
        MAINNET_BASE_URL_ENV: "https://api.binance.com",
        LIVE_TRADING_ENABLED_ENV: "0",
        LIVE_ALLOWED_SYMBOLS_ENV: "BTCUSDT",
        LIVE_MAX_OPEN_ORDERS_ENV: "1",
    }
    base.update(overrides)
    return base


class BinanceMainnetReadonlyPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / ARTIFACTS_SUBDIR
        self.now = datetime(2026, 6, 23, 23, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_blocks_when_enable_flag_missing(self) -> None:
        result = run_binance_mainnet_readonly_preflight(
            artifacts_dir=self.root,
            env={MAINNET_BASE_URL_ENV: "https://api.binance.com"},
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertIn(ENABLE_READONLY_ENV, result["reason"])

    def test_blocks_on_wrong_base_url(self) -> None:
        client = _FakeClient()
        result = run_binance_mainnet_readonly_preflight(
            artifacts_dir=self.root,
            env=_mainnet_env(**{MAINNET_BASE_URL_ENV: "https://testnet.binance.vision"}),
            client=client,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertIn("non-mainnet readonly base url", result["reason"].lower())
        self.assertEqual(client.server_time_calls, 0)

    def test_live_trading_flag_must_remain_disabled(self) -> None:
        result = run_binance_mainnet_readonly_preflight(
            artifacts_dir=self.root,
            env=_mainnet_env(**{LIVE_TRADING_ENABLED_ENV: "1"}),
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["live_trading_enabled"], False)
        self.assertIn("live_trading_must_remain_disabled", result["reason"])

    def test_success_is_readonly_and_never_calls_order_endpoints(self) -> None:
        client = _FakeClient()
        result = run_binance_mainnet_readonly_preflight(
            artifacts_dir=self.root,
            env=_mainnet_env(),
            client=client,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "SUCCESS")
        self.assertFalse(result["live_trading_enabled"])
        self.assertFalse(result["submit_attempted"])
        self.assertEqual(result["live_readiness_status"], "NOT_READY")
        self.assertFalse(result["live_submit_allowed"])
        self.assertTrue(result["server_time_available"])
        self.assertTrue(result["exchange_filters_available"])
        self.assertTrue(result["account_checked"])
        self.assertTrue(result["balances_checked"])
        self.assertTrue(result["open_orders_checked"])
        self.assertEqual(result["reconciliation_summary"]["count"], 0)
        self.assertEqual(client.place_order_calls, 0)
        self.assertEqual(client.order_test_calls, 0)
        self.assertEqual(client.exchange_info_calls, [("BTCUSDT",)])
        self.assertTrue(result["live_kill_switch_active"])
        self.assertIn("live_kill_switch_active_default_on", result["warnings"])
        persisted = json.loads((self.root / "binance_mainnet_readonly_preflight.json").read_text(encoding="utf-8"))
        self.assertNotIn("secret", json.dumps(persisted).lower())

    def test_reconciliation_mismatch_blocks(self) -> None:
        client = _FakeClient(
            open_orders_response=[
                {"symbol": "ETHUSDT", "side": "BUY", "status": "NEW", "type": "LIMIT", "origQty": "0.1", "executedQty": "0.0"},
                {"symbol": "BTCUSDT", "side": "BUY", "status": "NEW", "type": "LIMIT", "origQty": "0.1", "executedQty": "0.0"},
            ]
        )
        result = run_binance_mainnet_readonly_preflight(
            artifacts_dir=self.root,
            env=_mainnet_env(),
            client=client,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "ERROR")
        self.assertGreater(result["reconciliation_summary"]["count"], 0)
        self.assertIn("readonly_reconciliation_mismatch", result["reason"])

    def test_server_time_failure_blocks(self) -> None:
        result = run_binance_mainnet_readonly_preflight(
            artifacts_dir=self.root,
            env=_mainnet_env(),
            client=_FakeClient(server_time_raises=BinanceMainnetReadonlyRequestError("boom")),
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("boom", result["reason"])