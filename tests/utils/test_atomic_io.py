import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils.atomic_io import FileLockActiveError, advisory_file_lock, atomic_write_json


class AtomicIoTests(unittest.TestCase):
    def test_atomic_write_json_persists_payload_without_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "payload.json"
            atomic_write_json(path, {"ok": True, "value": 1})
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(encoding="utf-8"), '{"ok":true,"value":1}')
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_advisory_file_lock_creates_and_removes_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "test.lock"
            with advisory_file_lock(lock_path):
                self.assertTrue(lock_path.exists())
            self.assertFalse(lock_path.exists())

    def test_advisory_file_lock_rejects_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "test.lock"
            with advisory_file_lock(lock_path):
                with self.assertRaises(FileLockActiveError):
                    with advisory_file_lock(lock_path):
                        pass


if __name__ == "__main__":
    unittest.main()
