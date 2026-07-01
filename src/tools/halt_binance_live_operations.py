from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.execution.binance_live_operations_controller import halt_binance_live_operations
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Write a local HALTED live-operations state artifact. "
            "No broker calls, no order placement, and no order cancellation."
        )
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(Path("artifacts") / ARTIFACTS_SUBDIR),
        help="Directory where the live halt state artifact will be written.",
    )
    parser.add_argument(
        "--reason",
        default="manual_halt",
        help="Short operator reason recorded in the halt artifact.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = halt_binance_live_operations(artifacts_dir=args.artifacts_dir, reason=args.reason)
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
