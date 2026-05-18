from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.execution.binance_testnet_executor import (
    ARTIFACTS_SUBDIR,
    ENABLE_FLAG,
    KILL_SWITCH_ENV,
    ORDER_TEST_ONLY_FLAG,
    run_binance_testnet_execution,
)
from src.execution.crypto_operational_status import (
    evaluate_crypto_operational_status,
)
from src.execution.crypto_testnet_readiness import (
    evaluate_crypto_testnet_readiness,
)
from src.utils.atomic_io import atomic_write_json


_OPS_DIRNAME = "crypto_ops"
_DRY_RUN_FILENAME = "crypto_testnet_dry_run_result.json"
_ALLOWED_DECISIONS = frozenset({"TESTNET_DRY_RUN_ALLOWED", "TESTNET_SUBMIT_ALLOWED"})


def run_crypto_testnet_dry_run(
    *,
    paper_artifacts_dir: str | Path,
    testnet_artifacts_dir: str | Path | None = None,
    ops_artifacts_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    client: Any | None = None,
    rebuild_semantic: bool = False,
    now: datetime | None = None,
    max_heartbeat_age_minutes: int | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    paper_root = Path(paper_artifacts_dir)
    testnet_root = (
        Path(testnet_artifacts_dir)
        if testnet_artifacts_dir is not None
        else paper_root.parent / ARTIFACTS_SUBDIR
    )
    ops_root = (
        Path(ops_artifacts_dir)
        if ops_artifacts_dir is not None
        else paper_root.parent / _OPS_DIRNAME
    )
    testnet_root.mkdir(parents=True, exist_ok=True)
    ops_root.mkdir(parents=True, exist_ok=True)

    readiness = evaluate_crypto_testnet_readiness(
        paper_artifacts_dir=paper_root,
        testnet_artifacts_dir=testnet_root,
        now=moment,
        max_heartbeat_age_minutes=(
            int(max_heartbeat_age_minutes)
            if max_heartbeat_age_minutes is not None
            else 30
        ),
    )
    operational = evaluate_crypto_operational_status(
        paper_artifacts_dir=paper_root,
        testnet_artifacts_dir=testnet_root,
        ops_artifacts_dir=ops_root,
        now=moment,
        max_heartbeat_age_minutes=max_heartbeat_age_minutes,
    )

    result: dict[str, Any] = {
        "generated_at_utc": moment.isoformat(),
        "ok": False,
        "status": "BLOCKED",
        "mode": "TESTNET_DRY_RUN",
        "environment": "binance_spot_testnet",
        "paper_only": False,
        "testnet": True,
        "live_trading_enabled": False,
        "mainnet_enabled": False,
        "dry_run": True,
        "submit_attempted": False,
        "order_test_only_forced": True,
        "readiness_status": readiness.get("status"),
        "operational_overall_status": operational.get("overall_status"),
        "operational_final_decision": operational.get("final_decision"),
        "dry_run_ready": bool(readiness.get("dry_run_ready")),
        "submit_ready": bool(readiness.get("submit_ready")),
        "next_allowed_mode": operational.get("next_allowed_mode") or readiness.get("next_allowed_mode"),
        "blocking_reasons": list(operational.get("blocking_reasons") or []),
        "warnings": list(readiness.get("warnings") or []) + list(operational.get("warnings") or []),
        "artifact_inputs": {
            "readiness_artifact": str(testnet_root / "crypto_testnet_readiness.json"),
            "operational_status_artifact": str(ops_root / "crypto_operational_status.json"),
            "testnet_execution_result": str(testnet_root / "binance_testnet_execution_result.json"),
        },
        "artifacts": {
            _DRY_RUN_FILENAME: str(testnet_root / _DRY_RUN_FILENAME),
        },
    }

    decision = str(operational.get("final_decision") or "")
    if decision not in _ALLOWED_DECISIONS:
        result["reason"] = f"operational_status_blocked:{decision or 'UNKNOWN'}"
        _write_dry_run_result(testnet_root, result)
        return result

    source_env: dict[str, str] = dict(env if env is not None else os.environ)
    source_env[ORDER_TEST_ONLY_FLAG] = "1"

    execution = run_binance_testnet_execution(
        paper_artifacts_dir=paper_root,
        testnet_artifacts_dir=testnet_root,
        env=source_env,
        client=client,
        rebuild_semantic=bool(rebuild_semantic),
        now=moment,
        dry_run=True,
    )
    status = _status_from_execution(execution)
    result.update(
        {
            "ok": bool(execution.get("ok")),
            "status": status,
            "reason": execution.get("reason"),
            "executor_ok": bool(execution.get("ok")),
            "executor_run_id": execution.get("run_id"),
            "executor_category": execution.get("category"),
            "executor_severity": execution.get("severity"),
            "executor_action_taken": execution.get("action_taken"),
            "enable_flag_required": str(source_env.get(ENABLE_FLAG) or ""),
            "kill_switch_env_value": str(source_env.get(KILL_SWITCH_ENV) or ""),
        }
    )
    result["warnings"] = _dedupe(
        list(result.get("warnings") or [])
        + list(execution.get("warnings") or [])
    )
    if not execution.get("ok"):
        result["blocking_reasons"] = _dedupe(
            list(result.get("blocking_reasons") or [])
            + [str(execution.get("reason") or execution.get("category") or "executor_blocked")]
        )
    _write_dry_run_result(testnet_root, result)
    return result


def _write_dry_run_result(testnet_root: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(testnet_root / _DRY_RUN_FILENAME, payload)


def _status_from_execution(execution: Mapping[str, Any]) -> str:
    if bool(execution.get("ok")):
        return "SUCCESS"
    severity = str(execution.get("severity") or "").upper()
    if severity in {"CRITICAL", "ERROR"}:
        return "BLOCKED"
    return "ERROR"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


__all__ = ["run_crypto_testnet_dry_run"]
