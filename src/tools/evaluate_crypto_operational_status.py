from __future__ import annotations

import argparse
import json
import sys

from src.execution.crypto_operational_status import (
    evaluate_crypto_operational_status,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate crypto paper/testnet operational state into one "
            "decision artifact. Read-only. No live trading. No mainnet."
        )
    )
    parser.add_argument(
        "--paper-artifacts-dir",
        required=True,
        help="Crypto paper artifacts root.",
    )
    parser.add_argument(
        "--testnet-artifacts-dir",
        default=None,
        help="Optional crypto_testnet artifacts root override.",
    )
    parser.add_argument(
        "--ops-artifacts-dir",
        default=None,
        help="Optional crypto_ops artifacts root override.",
    )
    parser.add_argument(
        "--max-heartbeat-age-minutes",
        type=int,
        default=None,
        help="Optional heartbeat freshness threshold override.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate_crypto_operational_status(
        paper_artifacts_dir=args.paper_artifacts_dir,
        testnet_artifacts_dir=args.testnet_artifacts_dir,
        ops_artifacts_dir=args.ops_artifacts_dir,
        max_heartbeat_age_minutes=args.max_heartbeat_age_minutes,
    )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result.get("final_decision") in {"TESTNET_DRY_RUN_ALLOWED", "TESTNET_SUBMIT_ALLOWED", "PAPER_ONLY"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
