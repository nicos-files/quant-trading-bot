from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.execution.binance_live_readiness import evaluate_binance_live_readiness
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate Binance live readiness from the mainnet readonly preflight artifact. "
            "Read-only only and never places any order."
        )
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(Path("artifacts") / ARTIFACTS_SUBDIR),
        help="Directory that contains mainnet readonly and live readiness artifacts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate_binance_live_readiness(artifacts_dir=args.artifacts_dir)
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))