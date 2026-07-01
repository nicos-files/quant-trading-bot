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

from src.execution.binance_live_manual_review import acknowledge_binance_live_error_review
from src.execution.binance_live_operations_controller import evaluate_binance_live_operations
from src.execution.binance_live_micro_submit import run_binance_live_micro_submit
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


class _Client:
    def __init__(self) -> None:
        self.exchange_info_calls = 0
        self.server_time_calls = 0
        self.account_calls = 0
        self.open_orders_calls = 0
        self.place_order_calls: list[dict] = []

    def exchange_info(self, symbols=None):  # noqa: ANN001
        self.exchange_info_calls += 1
        return {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {"filterType": "LOT_SIZE", "stepSize": "0.000001", "minQty": "0.000001", "maxQty": "1000"},
                        {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.000001", "minQty": "0.000001", "maxQty": "1000"},
                        {"filterType": "MIN_NOTIONAL", "minNotional": "5.0"},
                    ],
                }
            ]
        }

    def server_time(self):
        self.server_time_calls += 1
        return {"serverTime": int(datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)}

    def account(self):
        self.account_calls += 1
        return {"balances": [{"asset": "BTC", "free": "1.0", "locked": "0.0"}, {"asset": "USDT", "free": "100.0", "locked": "0.0"}]}

    def open_orders(self, *, symbol=None):  # noqa: ANN001
        self.open_orders_calls += 1
        return []

    def place_order(self, *, params):  # noqa: ANN001
        self.place_order_calls.append(dict(params))
        return {
            "status": "FILLED",
            "fills": [{"price": "62000.0", "qty": "0.00008", "commission": "0.0", "commissionAsset": "BTC"}],
        }


class BinanceLiveManualReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / ARTIFACTS_SUBDIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
        self._write(
            "binance_mainnet_readonly_preflight.json",
            {
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
                "balances": {"USDT": {"free": "9.39084819", "locked": "0.0"}},
                "reconciliation_summary": {"count": 0, "blocking_count": 0, "highest_severity": "INFO"},
                "blocking_reasons": [],
                "warnings": [],
                "heartbeat": {"last_updated_at": self.now.isoformat()},
            },
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, relative: str, payload: object) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _env(self, **overrides: str) -> dict[str, str]:
        base = {
            "BINANCE_LIVE_MODE": "SINGLE_SHOT",
            "BINANCE_LIVE_TRADING_ENABLED": "1",
            "BINANCE_LIVE_CONFIRM_SUBMIT": "YES",
            "BINANCE_LIVE_KILL_SWITCH": "0",
            "BINANCE_LIVE_ALLOWED_SYMBOLS": "BTCUSDT",
            "BINANCE_LIVE_MAX_NOTIONAL": "5",
            "BINANCE_LIVE_MAX_DAILY_NOTIONAL": "5",
            "BINANCE_LIVE_MAX_DAILY_ORDERS": "1",
            "BINANCE_LIVE_MAX_OPEN_ORDERS": "1",
            "BINANCE_LIVE_BASE_URL": "https://api.binance.com",
            "BINANCE_LIVE_ARM_TOKEN": "ARMED",
            "BINANCE_LIVE_API_KEY": "live-key",
            "BINANCE_LIVE_API_SECRET": "live-secret",
            "BINANCE_MAINNET_API_KEY": "readonly-key",
            "BINANCE_MAINNET_API_SECRET": "readonly-secret",
        }
        base.update(overrides)
        return base

    def test_previous_live_error_without_review_blocks_operations(self) -> None:
        self._write(
            "binance_live_micro_submit_result.json",
            {
                "run_id": "live-micro-1",
                "status": "ERROR",
                "exchange_order_request_sent": True,
                "daily_cap_consumed": True,
                "daily_cap_reason": "prior_exchange_order_request_sent",
                "requested_notional": 5.0,
                "heartbeat": {"last_updated_at": self.now.isoformat()},
            },
        )
        result = evaluate_binance_live_operations(artifacts_dir=self.root, env=self._env(), now=self.now)
        self.assertIn("previous_live_error_requires_manual_review", result["blocking_reasons"])

    def test_manual_review_clears_previous_error_block_but_not_daily_cap(self) -> None:
        self._write(
            "binance_live_micro_submit_result.json",
            {
                "run_id": "live-micro-1",
                "status": "ERROR",
                "exchange_order_request_sent": True,
                "daily_cap_consumed": True,
                "daily_cap_reason": "prior_exchange_order_request_sent",
                "requested_notional": 5.0,
                "blocking_reasons": ['live_submit_failed:HTTP 400 {"code":-2010}'],
                "failure_stage": "broker_submit_exception",
                "heartbeat": {"last_updated_at": self.now.isoformat()},
            },
        )
        ack = acknowledge_binance_live_error_review(artifacts_dir=self.root, reason="reviewed", now=self.now)
        self.assertTrue(ack["ok"])
        result = evaluate_binance_live_operations(artifacts_dir=self.root, env=self._env(), now=self.now)
        self.assertNotIn("previous_live_error_requires_manual_review", result["blocking_reasons"])
        self.assertIn("live_max_daily_orders_reached", result["blocking_reasons"])

    def test_acknowledge_records_insufficient_balance_without_same_day_retry(self) -> None:
        self._write(
            "binance_live_micro_submit_result.json",
            {
                "run_id": "live-micro-2",
                "status": "ERROR",
                "exchange_order_request_sent": True,
                "placed_count": 0,
                "rejected_count": 0,
                "requested_notional": 5.0,
                "failure_stage": "broker_submit_exception",
                "blocking_reasons": ['live_submit_failed:HTTP 400 calling /api/v3/order: {"code":-2010,"msg":"Account has insufficient balance for requested action."}'],
                "heartbeat": {"last_updated_at": self.now.isoformat()},
            },
        )
        ack = acknowledge_binance_live_error_review(artifacts_dir=self.root, reason="insufficient balance reviewed", now=self.now)
        self.assertFalse(ack["allow_retry_same_utc_day"])
        self.assertFalse(ack["retry_same_day_enabled"])

    def test_execute_reports_quote_balance_consistently_when_blocked_by_daily_cap(self) -> None:
        self._write(
            "binance_live_micro_submit_result.json",
            {
                "run_id": "live-micro-3",
                "status": "ERROR",
                "exchange_order_request_sent": True,
                "daily_cap_consumed": True,
                "daily_cap_reason": "prior_exchange_order_request_sent",
                "requested_notional": 5.0,
                "heartbeat": {"last_updated_at": self.now.isoformat()},
            },
        )
        result = run_binance_live_micro_submit(artifacts_dir=self.root, env=self._env(), client=_Client(), now=self.now, execute=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_stage"], "daily_cap_gate")
        self.assertEqual(result["quote_free_balance"], 9.39084819)
        self.assertNotIn("live_insufficient_quote_balance_precheck", result["blocking_reasons"])
