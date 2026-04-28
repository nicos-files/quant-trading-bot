"""Daily crypto paper-forward wrapper that archives a timestamped copy of artifacts.

Paper-only / manual-review only. This wrapper:

- Sets the environment flags required by the existing crypto paper-forward tool
  (``ENABLE_CRYPTO_PAPER_FORWARD=1`` and ``ENABLE_CRYPTO_MARKET_DATA=1``).
- Invokes the unmodified ``src.tools.run_crypto_paper_forward`` module via
  subprocess using ``sys.executable``.
- After the tool finishes, copies the canonical output directories and
  root-level ``crypto_paper_*.json`` artifacts into a timestamped archive
  directory under ``artifacts/crypto_paper/archive/<UTC-stamp>/``.
- Writes ``run_metadata.json`` and ``run.log`` into the same archive directory.
- Returns the same exit code as the underlying tool.

The wrapper does not modify the canonical paths and does not mutate any
production configuration. It does not enable live trading, does not introduce
broker integrations, does not handle API keys, and does not auto-promote any
strategy parameters.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CANONICAL_SUBDIRS: tuple[str, ...] = ("paper_forward", "daily_close", "history", "evaluation")
CANONICAL_ROOT_FILE_PREFIX: str = "crypto_paper_"
CANONICAL_ROOT_FILE_SUFFIX: str = ".json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the crypto paper-forward tool and copy its canonical artifacts into a "
            "timestamped archive directory. Paper-only / manual-review only."
        )
    )
    parser.add_argument("--candidate-config", required=True)
    parser.add_argument("--artifacts-dir", default="artifacts/crypto_paper")
    parser.add_argument("--archive-root", default="artifacts/crypto_paper/archive")
    parser.add_argument("--stamp", default=None)
    return parser


def generate_stamp() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.strftime('%Y-%m-%d')}/{now.strftime('%H%M%S')}"


def archive_run(*, artifacts_dir: Path, archive_dir: Path) -> list[str]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    if artifacts_dir.is_dir():
        for name in CANONICAL_SUBDIRS:
            source = artifacts_dir / name
            if source.is_dir():
                destination = archive_dir / name
                shutil.copytree(source, destination, dirs_exist_ok=True)
                copied.append(name)
        for entry in sorted(artifacts_dir.iterdir()):
            if not entry.is_file():
                continue
            if not entry.name.startswith(CANONICAL_ROOT_FILE_PREFIX):
                continue
            if not entry.name.endswith(CANONICAL_ROOT_FILE_SUFFIX):
                continue
            shutil.copy2(entry, archive_dir / entry.name)
            copied.append(entry.name)
    return copied


def get_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    commit = (result.stdout or "").strip()
    return commit or None


def build_run_command(*, candidate_config: str, artifacts_dir: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "src.tools.run_crypto_paper_forward",
        "--candidate-config",
        candidate_config,
        "--artifacts-dir",
        artifacts_dir,
    ]


def run_paper_forward_subprocess(
    *,
    candidate_config: str,
    artifacts_dir: str,
    env: dict[str, str],
) -> subprocess.CompletedProcess:
    cmd = build_run_command(candidate_config=candidate_config, artifacts_dir=artifacts_dir)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def write_run_log(*, archive_dir: Path, completed: subprocess.CompletedProcess) -> Path:
    log_path = archive_dir / "run.log"
    parts = [
        "# stdout",
        completed.stdout or "",
        "# stderr",
        completed.stderr or "",
    ]
    log_path.write_text("\n".join(parts), encoding="utf-8")
    return log_path


def write_run_metadata(
    *,
    archive_dir: Path,
    metadata: dict[str, Any],
) -> Path:
    metadata_path = archive_dir / "run_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return metadata_path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifacts_dir = Path(args.artifacts_dir)
    archive_root = Path(args.archive_root)
    stamp = args.stamp or generate_stamp()
    archive_dir = archive_root / stamp

    env = os.environ.copy()
    env["ENABLE_CRYPTO_PAPER_FORWARD"] = "1"
    env["ENABLE_CRYPTO_MARKET_DATA"] = "1"
    env.setdefault("PYTHONPATH", ".")

    started_at = datetime.now(timezone.utc).isoformat()
    completed = run_paper_forward_subprocess(
        candidate_config=str(args.candidate_config),
        artifacts_dir=str(artifacts_dir),
        env=env,
    )
    finished_at = datetime.now(timezone.utc).isoformat()

    archive_dir.mkdir(parents=True, exist_ok=True)
    copied = archive_run(artifacts_dir=artifacts_dir, archive_dir=archive_dir)

    log_path = write_run_log(archive_dir=archive_dir, completed=completed)
    metadata = {
        "run_id": stamp,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": int(completed.returncode),
        "candidate_config": str(args.candidate_config),
        "artifacts_dir": str(artifacts_dir),
        "archive_dir": str(archive_dir),
        "archive_root": str(archive_root),
        "copied": copied,
        "git_commit": get_git_commit(),
        "paper_only": True,
        "live_trading": False,
    }
    metadata_path = write_run_metadata(archive_dir=archive_dir, metadata=metadata)

    sys.stdout.write(completed.stdout or "")
    sys.stderr.write(completed.stderr or "")
    sys.stdout.write(f"[ARCHIVE] {archive_dir}\n")
    sys.stdout.write(f"[ARCHIVE-METADATA] {metadata_path}\n")
    sys.stdout.write(f"[ARCHIVE-LOG] {log_path}\n")
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
