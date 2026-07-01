from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.execution.binance_live_manual_review import acknowledge_binance_live_error_review
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Record a manual-review acknowledgment for the latest Binance live execution error. "
            "This does not place orders, does not clear daily caps, and does not enable same-day retry."
        )
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(Path("artifacts") / ARTIFACTS_SUBDIR),
        help="Directory that contains live artifacts and where the manual review artifact will be written.",
    )
    parser.add_argument("--reason", required=True, help="Short operator reason for acknowledging the previous live error.")
    parser.add_argument(
        "--operator-action",
        default="manual_review_recorded",
        help="Short operator action note recorded in the review artifact.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = acknowledge_binance_live_error_review(
        artifacts_dir=args.artifacts_dir,
        reason=args.reason,
        operator_action=args.operator_action,
    )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
