from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.execution.binance_live_cancel_open_orders import run_binance_live_cancel_open_orders
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare-only Binance live cancel-open-orders workflow. "
            "Default mode only reads open orders and writes a cancel plan. "
            "No cancel endpoint is called."
        )
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(Path("artifacts") / ARTIFACTS_SUBDIR),
        help="Directory that contains live artifacts and where the cancel plan will be written.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Explicitly request prepare-only mode. This is the default when --execute is omitted.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Future-use gated execute path. It remains fail-closed and should not be used casually.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_binance_live_cancel_open_orders(
        artifacts_dir=args.artifacts_dir,
        prepare_only=bool(args.prepare_only or not args.execute),
        execute=bool(args.execute),
    )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
