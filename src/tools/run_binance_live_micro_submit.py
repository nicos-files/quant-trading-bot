from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.execution.binance_live_micro_submit import run_binance_live_micro_submit
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Gated Binance live micro-submit entrypoint. "
            "Prepare-only is the default. Live execution requires --execute and still stays fail-closed unless every gate is satisfied. "
            "BINANCE_LIVE_CONFIRM_SUBMIT=YES is future-use only and must never be exported globally."
        )
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(Path("artifacts") / ARTIFACTS_SUBDIR),
        help="Directory that contains live readiness artifacts and live micro-submit artifacts.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Explicitly request prepare-only mode. This remains the default when --execute is omitted.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Attempt the fully gated live execution path. Do not use without explicit human approval and inline BINANCE_LIVE_CONFIRM_SUBMIT=YES. "
            "This command must never be run against mainnet casually."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_binance_live_micro_submit(
        artifacts_dir=args.artifacts_dir,
        prepare_only=bool(args.prepare_only),
        execute=bool(args.execute),
    )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))