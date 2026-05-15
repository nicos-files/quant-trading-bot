from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class FileLockActiveError(RuntimeError):
    """Raised when an advisory lock file already exists."""


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(
        f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    with temp_path.open("w", encoding=encoding) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, target)
    return target


def atomic_write_json(path: str | Path, payload: Any, *, encoding: str = "utf-8") -> Path:
    return atomic_write_text(
        path,
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding=encoding,
    )


@contextmanager
def advisory_file_lock(
    path: str | Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Path]:
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        payload["metadata"] = dict(metadata)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise FileLockActiveError(f"lock_active:{lock_path}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            )
            handle.flush()
            os.fsync(handle.fileno())
        yield lock_path
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
