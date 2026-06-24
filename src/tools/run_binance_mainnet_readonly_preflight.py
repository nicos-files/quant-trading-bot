from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.execution.binance_mainnet_readonly_preflight import (
    ARTIFACTS_SUBDIR,
    ENABLE_READONLY_ENV,
    LIVE_ALLOWED_SYMBOLS_ENV,
    LIVE_CONFIRM_SUBMIT_ENV,
    LIVE_KILL_SWITCH_ENV,
    LIVE_MAX_DAILY_ORDERS_ENV,
    LIVE_MAX_NOTIONAL_ENV,
    LIVE_MAX_OPEN_ORDERS_ENV,
    LIVE_TRADING_ENABLED_ENV,
    MAINNET_API_KEY_ENV,
    MAINNET_API_SECRET_ENV,
    MAINNET_BASE_URL_ENV,
    run_binance_mainnet_readonly_preflight,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run Binance mainnet readonly preflight. Read-only only: validates "
            "server time, exchange filters, account, balances, open orders, "
            "and readonly reconciliation. Never places, tests, or submits an order."
        )
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(Path("artifacts") / ARTIFACTS_SUBDIR),
        help="Target directory for readonly mainnet artifacts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_binance_mainnet_readonly_preflight(artifacts_dir=args.artifacts_dir)
    audit = {
        "run_id": result.get("run_id"),
        "ok": result.get("ok"),
        "status": result.get("status"),
        "mainnet": result.get("mainnet"),
        "testnet": result.get("testnet"),
        "live_trading_enabled": result.get("live_trading_enabled"),
        "live_readiness_status": result.get("live_readiness_status"),
        "live_submit_allowed": result.get("live_submit_allowed"),
        "submit_attempted": result.get("submit_attempted"),
        "base_url": result.get("base_url"),
        "server_time_available": result.get("server_time_available"),
        "exchange_filters_available": result.get("exchange_filters_available"),
        "account_checked": result.get("account_checked"),
        "balances_checked": result.get("balances_checked"),
        "open_orders_checked": result.get("open_orders_checked"),
        "reconciliation_summary": result.get("reconciliation_summary"),
        "blocking_reasons": result.get("blocking_reasons"),
        "warnings": result.get("warnings"),
        "api_key_masked": result.get("api_key_masked"),
        "heartbeat": result.get("heartbeat"),
        "artifacts": result.get("artifacts"),
        "env_flags": {
            ENABLE_READONLY_ENV: "must be '1' to enable mainnet readonly preflight",
            MAINNET_BASE_URL_ENV: "must be exactly https://api.binance.com",
            MAINNET_API_KEY_ENV: "required for readonly account endpoints",
            MAINNET_API_SECRET_ENV: "required for readonly account endpoints",
            LIVE_TRADING_ENABLED_ENV: "must remain '0' for readonly preflight",
            LIVE_CONFIRM_SUBMIT_ENV: "future-use only; not used by readonly preflight",
            LIVE_MAX_NOTIONAL_ENV: "future live cap; reported but not used for submit here",
            LIVE_MAX_DAILY_ORDERS_ENV: "future live cap; reported but not used for submit here",
            LIVE_MAX_OPEN_ORDERS_ENV: "readonly reconciliation cap for open orders",
            LIVE_ALLOWED_SYMBOLS_ENV: "readonly allowlist; defaults to BTCUSDT",
            LIVE_KILL_SWITCH_ENV: "defaults to '1' for future live submit paths; readonly preflight does not submit",
        },
    }
    sys.stdout.write(json.dumps(audit, sort_keys=True) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))