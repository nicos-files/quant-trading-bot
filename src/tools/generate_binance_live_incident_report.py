from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.execution.binance_live_incident_report import generate_binance_live_incident_report
from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an offline Binance live incident report from existing local artifacts only."
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(Path("artifacts") / ARTIFACTS_SUBDIR),
        help="Directory that contains live artifacts and where the incident report will be written.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = generate_binance_live_incident_report(artifacts_dir=args.artifacts_dir)
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
