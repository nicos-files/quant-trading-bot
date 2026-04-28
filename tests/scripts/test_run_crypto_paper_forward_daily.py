from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "run_crypto_paper_forward_daily.py"


def _load_wrapper_module():
    spec = importlib.util.spec_from_file_location(
        "run_crypto_paper_forward_daily_under_test",
        _SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load wrapper script for testing.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper = _load_wrapper_module()


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _seed_canonical_artifacts(artifacts_dir: Path) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("paper_forward", "daily_close", "history", "evaluation"):
        sub_dir = artifacts_dir / sub
        sub_dir.mkdir(parents=True, exist_ok=True)
        (sub_dir / f"{sub}_marker.json").write_text(
            json.dumps({"sub": sub}), encoding="utf-8"
        )
    (artifacts_dir / "crypto_paper_snapshot.json").write_text(
        json.dumps({"cash": 100.0}), encoding="utf-8"
    )
    (artifacts_dir / "crypto_paper_positions.json").write_text(
        json.dumps([]), encoding="utf-8"
    )
    (artifacts_dir / "unrelated.json").write_text(
        json.dumps({"unrelated": True}), encoding="utf-8"
    )


def _write_candidate(tmp: Path) -> Path:
    candidate = tmp / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "default_quote_currency": "USDT",
                "strategy": {"enabled": True, "fast_ma_window": 2, "slow_ma_window": 3},
                "symbols": [],
            }
        ),
        encoding="utf-8",
    )
    return candidate


class RunCryptoPaperForwardDailyWrapperTests(unittest.TestCase):
    def _invoke_wrapper(
        self,
        tmp: Path,
        *,
        returncode: int = 0,
        stdout: str = "TOOL-STDOUT",
        stderr: str = "TOOL-STDERR",
        stamp: str = "2026-01-02/030405",
    ):
        artifacts_dir = tmp / "artifacts" / "crypto_paper"
        archive_root = tmp / "artifacts" / "crypto_paper" / "archive"
        candidate = _write_candidate(tmp)
        _seed_canonical_artifacts(artifacts_dir)
        fake = _FakeCompleted(returncode=returncode, stdout=stdout, stderr=stderr)
        with patch.object(wrapper, "run_paper_forward_subprocess", return_value=fake) as mock_run:
            exit_code = wrapper.main(
                [
                    "--candidate-config",
                    str(candidate),
                    "--artifacts-dir",
                    str(artifacts_dir),
                    "--archive-root",
                    str(archive_root),
                    "--stamp",
                    stamp,
                ]
            )
        archive_dir = archive_root / stamp
        return exit_code, archive_dir, artifacts_dir, candidate, mock_run

    def test_creates_archive_directory(self):
        with TemporaryDirectory() as tmp:
            exit_code, archive_dir, _, _, _ = self._invoke_wrapper(Path(tmp))
            self.assertEqual(exit_code, 0)
            self.assertTrue(archive_dir.is_dir())

    def test_copies_canonical_subdirs_into_archive(self):
        with TemporaryDirectory() as tmp:
            _, archive_dir, _, _, _ = self._invoke_wrapper(Path(tmp))
            for sub in ("paper_forward", "daily_close", "history", "evaluation"):
                marker = archive_dir / sub / f"{sub}_marker.json"
                self.assertTrue(marker.is_file(), f"missing archived marker for {sub}")

    def test_copies_root_level_crypto_paper_json_files(self):
        with TemporaryDirectory() as tmp:
            _, archive_dir, _, _, _ = self._invoke_wrapper(Path(tmp))
            self.assertTrue((archive_dir / "crypto_paper_snapshot.json").is_file())
            self.assertTrue((archive_dir / "crypto_paper_positions.json").is_file())

    def test_does_not_copy_unrelated_root_level_files(self):
        with TemporaryDirectory() as tmp:
            _, archive_dir, _, _, _ = self._invoke_wrapper(Path(tmp))
            self.assertFalse((archive_dir / "unrelated.json").exists())

    def test_does_not_move_or_delete_canonical_outputs(self):
        with TemporaryDirectory() as tmp:
            _, _, artifacts_dir, _, _ = self._invoke_wrapper(Path(tmp))
            for sub in ("paper_forward", "daily_close", "history", "evaluation"):
                marker = artifacts_dir / sub / f"{sub}_marker.json"
                self.assertTrue(marker.is_file(), f"canonical marker for {sub} was removed")
            self.assertTrue((artifacts_dir / "crypto_paper_snapshot.json").is_file())
            self.assertTrue((artifacts_dir / "crypto_paper_positions.json").is_file())
            self.assertTrue((artifacts_dir / "unrelated.json").is_file())

    def test_writes_run_metadata(self):
        with TemporaryDirectory() as tmp:
            _, archive_dir, _, candidate, _ = self._invoke_wrapper(
                Path(tmp), stamp="2026-04-28/120000"
            )
            metadata_path = archive_dir / "run_metadata.json"
            self.assertTrue(metadata_path.is_file())
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["run_id"], "2026-04-28/120000")
            self.assertIn("started_at", payload)
            self.assertIn("finished_at", payload)
            self.assertEqual(payload["exit_code"], 0)
            self.assertEqual(payload["candidate_config"], str(candidate))
            self.assertTrue(payload["paper_only"])
            self.assertFalse(payload["live_trading"])
            self.assertIn("paper_forward", payload["copied"])
            self.assertIn("daily_close", payload["copied"])
            self.assertIn("history", payload["copied"])
            self.assertIn("evaluation", payload["copied"])
            self.assertIn("crypto_paper_snapshot.json", payload["copied"])
            self.assertIn("crypto_paper_positions.json", payload["copied"])

    def test_writes_run_log_with_stdout_and_stderr(self):
        with TemporaryDirectory() as tmp:
            _, archive_dir, _, _, _ = self._invoke_wrapper(
                Path(tmp), stdout="OUT-LINE", stderr="ERR-LINE"
            )
            log_path = archive_dir / "run.log"
            self.assertTrue(log_path.is_file())
            text = log_path.read_text(encoding="utf-8")
            self.assertIn("OUT-LINE", text)
            self.assertIn("ERR-LINE", text)

    def test_returns_underlying_exit_code(self):
        with TemporaryDirectory() as tmp:
            exit_code, _, _, _, _ = self._invoke_wrapper(Path(tmp), returncode=7)
            self.assertEqual(exit_code, 7)

    def test_propagates_required_env_flags_to_subprocess(self):
        with TemporaryDirectory() as tmp:
            _, _, _, _, mock_run = self._invoke_wrapper(Path(tmp))
            self.assertEqual(mock_run.call_count, 1)
            kwargs = mock_run.call_args.kwargs
            env = kwargs.get("env") or {}
            self.assertEqual(env.get("ENABLE_CRYPTO_PAPER_FORWARD"), "1")
            self.assertEqual(env.get("ENABLE_CRYPTO_MARKET_DATA"), "1")

    def test_does_not_touch_execution_plan(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            execution_plan = tmp_path / "execution.plan.json"
            execution_plan.write_text("ORIGINAL-PLAN", encoding="utf-8")
            self._invoke_wrapper(tmp_path)
            self.assertEqual(
                execution_plan.read_text(encoding="utf-8"), "ORIGINAL-PLAN"
            )

    def test_does_not_touch_final_decision(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            final_decision = tmp_path / "final_decision.json"
            final_decision.write_text("ORIGINAL-FINAL", encoding="utf-8")
            self._invoke_wrapper(tmp_path)
            self.assertEqual(
                final_decision.read_text(encoding="utf-8"), "ORIGINAL-FINAL"
            )

    def test_does_not_modify_market_universe_crypto_json(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_dir = tmp_path / "config" / "market_universe"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file = config_dir / "crypto.json"
            config_file.write_text("ORIGINAL-CONFIG", encoding="utf-8")
            self._invoke_wrapper(tmp_path)
            self.assertEqual(
                config_file.read_text(encoding="utf-8"), "ORIGINAL-CONFIG"
            )

    def test_generate_stamp_format(self):
        stamp = wrapper.generate_stamp()
        self.assertIn("/", stamp)
        date_part, time_part = stamp.split("/", 1)
        self.assertEqual(len(date_part), 10)
        self.assertEqual(date_part[4], "-")
        self.assertEqual(date_part[7], "-")
        self.assertEqual(len(time_part), 6)
        self.assertTrue(time_part.isdigit())

    def test_build_run_command_uses_sys_executable_and_module(self):
        cmd = wrapper.build_run_command(
            candidate_config="cfg.json", artifacts_dir="adir"
        )
        self.assertEqual(cmd[1], "-m")
        self.assertEqual(cmd[2], "src.tools.run_crypto_paper_forward")
        self.assertIn("--candidate-config", cmd)
        self.assertIn("cfg.json", cmd)
        self.assertIn("--artifacts-dir", cmd)
        self.assertIn("adir", cmd)


if __name__ == "__main__":
    unittest.main()
