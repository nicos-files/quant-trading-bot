from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.execution.binance_live_soak_status import evaluate_binance_live_soak_status
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate Binance live soak status from existing daily close artifacts only."
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(Path("artifacts") / ARTIFACTS_SUBDIR),
        help="Directory that contains live daily close artifacts.",
    )
    parser.add_argument(
        "--days-required",
        type=int,
        default=3,
        help="Required soak days. Default 3, capped at 5.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate_binance_live_soak_status(
        artifacts_dir=args.artifacts_dir,
        days_required=args.days_required,
    )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if str(result.get("soak_status") or "") == "PASSED" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
