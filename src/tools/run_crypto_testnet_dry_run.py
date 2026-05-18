from __future__ import annotations

import argparse
import json
import sys

from src.execution.crypto_testnet_dry_run import run_crypto_testnet_dry_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a controlled Binance Spot Testnet dry-run preparation flow. "
            "This command never submits real testnet orders, never touches "
            "live trading, and never enables mainnet."
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
        "--rebuild-semantic",
        action="store_true",
        help="Force rebuild of the semantic layer before the preview run.",
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
    result = run_crypto_testnet_dry_run(
        paper_artifacts_dir=args.paper_artifacts_dir,
        testnet_artifacts_dir=args.testnet_artifacts_dir,
        ops_artifacts_dir=args.ops_artifacts_dir,
        rebuild_semantic=bool(args.rebuild_semantic),
        max_heartbeat_age_minutes=args.max_heartbeat_age_minutes,
    )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
