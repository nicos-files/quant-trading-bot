from __future__ import annotations

import argparse
import json
import sys

from src.execution.crypto_testnet_readiness import (
    evaluate_crypto_testnet_readiness,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate whether existing crypto paper/testnet artifacts support "
            "a controlled Binance Spot Testnet exploratory run. Read-only. "
            "No live trading, no mainnet, no network required."
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
        "--output-path",
        default=None,
        help="Optional readiness summary artifact path override.",
    )
    parser.add_argument(
        "--max-heartbeat-age-minutes",
        type=int,
        default=30,
        help="Heartbeat freshness threshold in minutes (default: 30).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate_crypto_testnet_readiness(
        paper_artifacts_dir=args.paper_artifacts_dir,
        testnet_artifacts_dir=args.testnet_artifacts_dir,
        output_path=args.output_path,
        max_heartbeat_age_minutes=int(args.max_heartbeat_age_minutes),
    )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result.get("status") == "READY" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
