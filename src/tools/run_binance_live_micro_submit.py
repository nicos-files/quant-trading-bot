from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.execution.binance_live_micro_submit import run_binance_live_micro_submit_prepare_only
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare-only scaffold for a future Binance live micro-submit. "
            "Never places, tests, or submits an order in this package. "
            "BINANCE_LIVE_CONFIRM_SUBMIT=YES is future-use only and must never be exported globally."
        )
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(Path("artifacts") / ARTIFACTS_SUBDIR),
        help="Directory that contains live readiness artifacts and the prepare-only plan output.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Explicitly request prepare-only mode. If omitted, the command still stays in prepare-only mode.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Future-use only. This package fails closed and never executes live orders. "
            "Do not use BINANCE_LIVE_CONFIRM_SUBMIT=YES outside an inline future live-submit command."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    prepare_only = True if not args.execute else bool(args.prepare_only)
    result = run_binance_live_micro_submit_prepare_only(
        artifacts_dir=args.artifacts_dir,
        prepare_only=prepare_only,
        execute=bool(args.execute),
    )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
