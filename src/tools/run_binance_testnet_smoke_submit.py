"""CLI wrapper around :func:`src.execution.binance_testnet_smoke_submit.run_binance_testnet_smoke_submit`."""

from __future__ import annotations

import argparse
import json
import sys

from src.execution.binance_testnet_executor import (
    ALLOWED_SYMBOLS_ENV,
    BASE_URL_ENV,
    CONFIRM_SUBMIT_ENV,
    ENABLE_FLAG,
    KILL_SWITCH_ENV,
    KILL_SWITCH_PATH_ENV,
    MAX_NOTIONAL_ENV,
    MAX_OPEN_ORDERS_ENV,
    ORDER_TEST_ONLY_FLAG,
)
from src.execution.binance_testnet_smoke_submit import run_binance_testnet_smoke_submit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute one explicit Binance Spot Testnet smoke submit without "
            "using strategy or semantic events. Requires ORDER_TEST_ONLY=0, "
            "BINANCE_TESTNET_CONFIRM_SUBMIT=YES, readiness READY, and "
            "operational TESTNET_SUBMIT_ALLOWED."
        )
    )
    parser.add_argument(
        "--paper-artifacts-dir",
        required=True,
        help="Crypto paper-forward artifacts root (used only for readiness/ops gates).",
    )
    parser.add_argument(
        "--testnet-artifacts-dir",
        default=None,
        help=(
            "Override target directory for testnet artifacts. "
            "Defaults to <paper_artifacts_dir>/../crypto_testnet."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_binance_testnet_smoke_submit(
        paper_artifacts_dir=args.paper_artifacts_dir,
        testnet_artifacts_dir=args.testnet_artifacts_dir,
    )
    audit = {
        "run_id": result.get("run_id"),
        "ok": result.get("ok"),
        "status": result.get("status"),
        "testnet": result.get("testnet"),
        "live_trading": result.get("live_trading"),
        "order_test_only": result.get("order_test_only"),
        "confirm_submit": result.get("confirm_submit"),
        "base_url": result.get("base_url"),
        "symbol": result.get("symbol"),
        "requested_notional": result.get("requested_notional"),
        "placed_count": result.get("placed_count"),
        "rejected_count": result.get("rejected_count"),
        "submit_attempted": result.get("submit_attempted"),
        "severity": result.get("severity"),
        "category": result.get("category"),
        "failure_reason": result.get("failure_reason"),
        "action_taken": result.get("action_taken"),
        "reconciliation_summary": result.get("reconciliation_summary"),
        "blocking_reasons": result.get("blocking_reasons"),
        "warnings": result.get("warnings"),
        "api_key_masked": result.get("api_key_masked"),
        "heartbeat": result.get("heartbeat"),
        "artifacts": result.get("artifacts"),
        "env_flags": {
            ENABLE_FLAG: "must be '1' to enable testnet execution",
            ORDER_TEST_ONLY_FLAG: "must be '0' for the smoke submit command",
            CONFIRM_SUBMIT_ENV: "required exact value YES",
            BASE_URL_ENV: "must be a testnet host",
            MAX_NOTIONAL_ENV: "must be <= 25 for smoke submit",
            ALLOWED_SYMBOLS_ENV: "must be BTCUSDT",
            MAX_OPEN_ORDERS_ENV: "must be exactly 1",
            KILL_SWITCH_ENV: "set '1' to hard-stop testnet execution",
            KILL_SWITCH_PATH_ENV: "optional JSON file with {\"enabled\": true}",
        },
    }
    sys.stdout.write(json.dumps(audit, sort_keys=True) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
