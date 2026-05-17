from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_write_json, atomic_write_text


_TESTNET_DIRNAME = "crypto_testnet"
_OPS_DIRNAME = "crypto_ops"
_READINESS_FILENAME = "crypto_testnet_readiness.json"
_STATUS_JSON_FILENAME = "crypto_operational_status.json"
_STATUS_MD_FILENAME = "crypto_operational_status.md"


def evaluate_crypto_operational_status(
    *,
    paper_artifacts_dir: str | Path,
    testnet_artifacts_dir: str | Path | None = None,
    ops_artifacts_dir: str | Path | None = None,
    now: datetime | None = None,
    max_heartbeat_age_minutes: int | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    paper_root = Path(paper_artifacts_dir)
    testnet_root = (
        Path(testnet_artifacts_dir)
        if testnet_artifacts_dir is not None
        else paper_root.parent / _TESTNET_DIRNAME
    )
    ops_root = (
        Path(ops_artifacts_dir)
        if ops_artifacts_dir is not None
        else paper_root.parent / _OPS_DIRNAME
    )
    ops_root.mkdir(parents=True, exist_ok=True)

    forward_result = _load_json(
        paper_root / "paper_forward" / "crypto_paper_forward_result.json", default={}
    )
    semantic_summary = _load_json(
        paper_root / "semantic" / "crypto_semantic_summary.json", default={}
    )
    dashboard_data = _load_json(
        paper_root / "dashboard" / "dashboard_data.json", default={}
    )
    notify_result = _load_json(
        paper_root / "semantic" / "telegram_notify_result.json", default={}
    )
    readiness = _load_json(
        testnet_root / _READINESS_FILENAME, default={}
    )
    testnet_result = _load_json(
        testnet_root / "binance_testnet_execution_result.json", default={}
    )

    heartbeat_age_minutes = int(
        max_heartbeat_age_minutes
        if max_heartbeat_age_minutes is not None
        else (
            readiness.get("max_heartbeat_age_minutes")
            if isinstance(readiness, dict) and readiness.get("max_heartbeat_age_minutes") is not None
            else 30
        )
    )
    cutoff = moment - timedelta(minutes=max(1, heartbeat_age_minutes))

    artifact_inputs = {
        "paper_forward_result": _artifact_input(
            paper_root / "paper_forward" / "crypto_paper_forward_result.json",
            forward_result,
        ),
        "semantic_summary": _artifact_input(
            paper_root / "semantic" / "crypto_semantic_summary.json",
            semantic_summary,
        ),
        "dashboard_data": _artifact_input(
            paper_root / "dashboard" / "dashboard_data.json",
            dashboard_data,
        ),
        "telegram_notify_result": _artifact_input(
            paper_root / "semantic" / "telegram_notify_result.json",
            notify_result,
        ),
        "testnet_readiness": _artifact_input(
            testnet_root / _READINESS_FILENAME,
            readiness,
        ),
        "testnet_result": _artifact_input(
            testnet_root / "binance_testnet_execution_result.json",
            testnet_result,
        ),
    }

    paper_forward_status = str(forward_result.get("status") or "UNKNOWN") if isinstance(forward_result, dict) and forward_result else "UNKNOWN"
    semantic_status = str(semantic_summary.get("operational_status") or "UNKNOWN") if isinstance(semantic_summary, dict) and semantic_summary else "UNKNOWN"
    dashboard_status = str(dashboard_data.get("operational_status") or "UNKNOWN") if isinstance(dashboard_data, dict) and dashboard_data else "UNKNOWN"
    telegram_status = _telegram_status(notify_result)
    testnet_readiness_status = str(readiness.get("status") or "UNKNOWN") if isinstance(readiness, dict) and readiness else "UNKNOWN"
    dry_run_ready = bool(readiness.get("dry_run_ready")) if isinstance(readiness, dict) else False
    submit_ready = bool(readiness.get("submit_ready")) if isinstance(readiness, dict) else False
    next_allowed_mode = str(readiness.get("next_allowed_mode") or "blocked") if isinstance(readiness, dict) and readiness else "blocked"

    missing_reasons = _missing_artifact_reasons(artifact_inputs)
    stale_reasons = _stale_reasons(
        cutoff=cutoff,
        forward_result=forward_result,
        semantic_summary=semantic_summary,
        dashboard_data=dashboard_data,
        readiness=readiness,
    )
    blocked_reasons = _blocked_reasons(
        paper_forward_status=paper_forward_status,
        semantic_status=semantic_status,
        dashboard_status=dashboard_status,
        testnet_readiness_status=testnet_readiness_status,
    )
    degraded_reasons = _degraded_reasons(
        paper_forward_status=paper_forward_status,
        semantic_status=semantic_status,
        dashboard_status=dashboard_status,
        telegram_status=telegram_status,
        testnet_readiness_status=testnet_readiness_status,
        dry_run_ready=dry_run_ready,
        submit_ready=submit_ready,
    )

    if missing_reasons:
        overall_status = "UNKNOWN"
        final_decision = "DO_NOT_RUN"
        blocking_reasons = missing_reasons
    elif stale_reasons:
        overall_status = "STALE"
        final_decision = "DO_NOT_RUN"
        blocking_reasons = stale_reasons
    elif blocked_reasons:
        overall_status = "BLOCKED"
        final_decision = "DO_NOT_RUN"
        blocking_reasons = blocked_reasons
    elif degraded_reasons:
        overall_status = "DEGRADED"
        if dry_run_ready and not submit_ready:
            final_decision = "TESTNET_DRY_RUN_ALLOWED"
        elif submit_ready:
            final_decision = "PAPER_ONLY"
        else:
            final_decision = "PAPER_ONLY"
        blocking_reasons = degraded_reasons
    else:
        overall_status = "OK"
        if submit_ready:
            final_decision = "TESTNET_SUBMIT_ALLOWED"
        elif dry_run_ready:
            final_decision = "TESTNET_DRY_RUN_ALLOWED"
        else:
            final_decision = "PAPER_ONLY"
        blocking_reasons = []

    warnings = _dedupe(
        list(forward_result.get("warnings") or []) if isinstance(forward_result, dict) else []
        + list(semantic_summary.get("warnings") or []) if isinstance(semantic_summary, dict) else []
        + list(dashboard_data.get("warnings") or []) if isinstance(dashboard_data, dict) else []
        + list(readiness.get("warnings") or []) if isinstance(readiness, dict) else []
        + list(testnet_result.get("warnings") or []) if isinstance(testnet_result, dict) else []
    )

    result = {
        "generated_at_utc": moment.isoformat(),
        "overall_status": overall_status,
        "final_decision": final_decision,
        "paper_forward_status": paper_forward_status,
        "dashboard_status": dashboard_status,
        "semantic_status": semantic_status,
        "telegram_status": telegram_status,
        "testnet_readiness_status": testnet_readiness_status,
        "dry_run_ready": bool(dry_run_ready),
        "submit_ready": bool(submit_ready),
        "next_allowed_mode": next_allowed_mode,
        "blocking_reasons": list(blocking_reasons),
        "warnings": warnings,
        "artifact_inputs": artifact_inputs,
        "live_trading_enabled": False,
        "mainnet_enabled": False,
    }

    json_path = ops_root / _STATUS_JSON_FILENAME
    md_path = ops_root / _STATUS_MD_FILENAME
    atomic_write_json(json_path, result)
    atomic_write_text(md_path, _render_operational_status_markdown(result))
    result["artifacts"] = {
        _STATUS_JSON_FILENAME: str(json_path),
        _STATUS_MD_FILENAME: str(md_path),
    }
    return result


def _missing_artifact_reasons(artifact_inputs: dict[str, dict[str, Any]]) -> list[str]:
    required = (
        "paper_forward_result",
        "semantic_summary",
        "dashboard_data",
        "testnet_readiness",
    )
    missing: list[str] = []
    for name in required:
        item = artifact_inputs.get(name) or {}
        if not bool(item.get("exists")):
            missing.append(f"missing_artifact:{name}")
    return missing


def _stale_reasons(
    *,
    cutoff: datetime,
    forward_result: Any,
    semantic_summary: Any,
    dashboard_data: Any,
    readiness: Any,
) -> list[str]:
    reasons: list[str] = []
    if isinstance(forward_result, dict):
        stamp = (forward_result.get("heartbeat") or {}).get("last_updated_at")
        if stamp and not _is_fresh(stamp, cutoff=cutoff):
            reasons.append("stale_paper_forward_heartbeat")
    if isinstance(semantic_summary, dict):
        stamp = ((semantic_summary.get("heartbeats") or {}).get("semantic_generated_at")) or semantic_summary.get("generated_at")
        if stamp and not _is_fresh(stamp, cutoff=cutoff):
            reasons.append("stale_semantic_summary")
    if isinstance(dashboard_data, dict):
        stamp = dashboard_data.get("generated_at")
        if stamp and not _is_fresh(stamp, cutoff=cutoff):
            reasons.append("stale_dashboard")
    if isinstance(readiness, dict):
        stamp = readiness.get("generated_at")
        if stamp and not _is_fresh(stamp, cutoff=cutoff):
            reasons.append("stale_testnet_readiness")
    return reasons


def _blocked_reasons(
    *,
    paper_forward_status: str,
    semantic_status: str,
    dashboard_status: str,
    testnet_readiness_status: str,
) -> list[str]:
    reasons: list[str] = []
    if paper_forward_status != "SUCCESS":
        reasons.append(f"paper_forward_status:{paper_forward_status}")
    if semantic_status in {"ERROR", "BLOCKED", "UNKNOWN"}:
        reasons.append(f"semantic_status:{semantic_status}")
    if dashboard_status in {"ERROR", "BLOCKED", "UNKNOWN"}:
        reasons.append(f"dashboard_status:{dashboard_status}")
    if testnet_readiness_status == "UNKNOWN":
        reasons.append("testnet_readiness_unknown")
    return reasons


def _degraded_reasons(
    *,
    paper_forward_status: str,
    semantic_status: str,
    dashboard_status: str,
    telegram_status: str,
    testnet_readiness_status: str,
    dry_run_ready: bool,
    submit_ready: bool,
) -> list[str]:
    reasons: list[str] = []
    if paper_forward_status == "PARTIAL":
        reasons.append("paper_forward_partial")
    if semantic_status == "DEGRADED":
        reasons.append("semantic_degraded")
    if dashboard_status == "DEGRADED":
        reasons.append("dashboard_degraded")
    if telegram_status in {"ERROR", "DEGRADED"}:
        reasons.append(f"telegram_status:{telegram_status}")
    if testnet_readiness_status == "NOT_READY" and dry_run_ready and not submit_ready:
        reasons.append("testnet_submit_not_ready_dry_run_only")
    elif testnet_readiness_status == "NOT_READY":
        reasons.append("testnet_not_ready_paper_only")
    if submit_ready and (semantic_status == "DEGRADED" or dashboard_status == "DEGRADED"):
        reasons.append("testnet_blocked_by_degraded_paper_plane")
    return _dedupe(reasons)


def _telegram_status(notify_result: Any) -> str:
    if not isinstance(notify_result, dict) or not notify_result:
        return "UNKNOWN"
    severity = str(notify_result.get("severity") or "").upper()
    if severity == "CRITICAL":
        return "BLOCKED"
    if severity == "ERROR":
        return "ERROR"
    if severity == "WARNING":
        return "DEGRADED"
    if notify_result.get("ok") is True:
        return "OK"
    return "UNKNOWN"


def _artifact_input(path: Path, payload: Any) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "readable": payload not in ({}, [], None),
    }


def _load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return default
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _is_fresh(value: Any, *, cutoff: datetime) -> bool:
    parsed = _parse_iso(value)
    if parsed is None:
        return False
    return parsed >= cutoff


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def _render_operational_status_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Crypto Operational Status",
        "",
        f"- Generated at UTC: {result.get('generated_at_utc')}",
        f"- Overall status: {result.get('overall_status')}",
        f"- Final decision: {result.get('final_decision')}",
        f"- Paper forward status: {result.get('paper_forward_status')}",
        f"- Semantic status: {result.get('semantic_status')}",
        f"- Dashboard status: {result.get('dashboard_status')}",
        f"- Telegram status: {result.get('telegram_status')}",
        f"- Testnet readiness status: {result.get('testnet_readiness_status')}",
        f"- Dry-run ready: {result.get('dry_run_ready')}",
        f"- Submit ready: {result.get('submit_ready')}",
        f"- Next allowed mode: {result.get('next_allowed_mode')}",
        "",
        "## Blocking Reasons",
    ]
    reasons = list(result.get("blocking_reasons") or [])
    if not reasons:
        lines.append("- None.")
    else:
        for reason in reasons:
            lines.append(f"- {reason}")
    lines.extend(["", "## Warnings"])
    warnings = list(result.get("warnings") or [])
    if not warnings:
        lines.append("- None.")
    else:
        for warning in warnings:
            lines.append(f"- {warning}")
    lines.extend(["", "## Artifacts"])
    for name, item in dict(result.get("artifact_inputs") or {}).items():
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {name}: exists={bool(item.get('exists'))} readable={bool(item.get('readable'))} path={item.get('path')}"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "- Paper/testnet only.",
            "- No live trading.",
            "- No mainnet.",
            "- Do not run when state is ambiguous.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = ["evaluate_crypto_operational_status"]
