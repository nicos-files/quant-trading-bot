from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.execution.binance_mainnet_readonly_preflight import ARTIFACTS_SUBDIR
from src.utils.atomic_io import atomic_write_json

_JSON_FILENAME = "binance_live_incident_report.json"
_MD_FILENAME = "binance_live_incident_report.md"


def generate_binance_live_incident_report(
    *,
    artifacts_dir: str | Path = Path("artifacts") / ARTIFACTS_SUBDIR,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)

    live_result = _load_json(root / "binance_live_micro_submit_result.json")
    readonly = _load_json(root / "binance_mainnet_readonly_preflight.json")
    readiness = _load_json(root / "binance_live_readiness.json")
    operations = _load_json(root / "binance_live_operations_status.json")
    cancel_plan = _load_json(root / "binance_live_cancel_open_orders_plan.json")

    latest_live_result = _summarize_live_result(live_result)
    blocking_reasons = _dedupe(
        latest_live_result["blocking_reasons"]
        + _string_list((readiness or {}).get("blocking_reasons"))
        + _string_list((operations or {}).get("blocking_reasons"))
    )
    warnings = _dedupe(
        latest_live_result["warnings"]
        + _string_list((readonly or {}).get("warnings"))
        + _string_list((readiness or {}).get("warnings"))
        + _string_list((operations or {}).get("warnings"))
    )
    open_orders_status = _summarize_open_orders_status(cancel_plan=cancel_plan, readonly=readonly)
    reconciliation_summary = _summarize_reconciliation(live_result=live_result, readonly=readonly)
    daily_cap_status = _summarize_daily_cap(live_result)
    severity = _derive_severity(live_result=live_result, blocking_reasons=blocking_reasons, open_orders_status=open_orders_status, reconciliation_summary=reconciliation_summary)
    summary = _derive_summary(severity=severity, latest_live_result=latest_live_result, open_orders_status=open_orders_status)
    recommended_action = _derive_recommended_action(severity=severity, latest_live_result=latest_live_result)

    payload = {
        "incident_id": f"live-incident-{moment.strftime('%Y%m%d-%H%M%S')}",
        "generated_at_utc": moment.isoformat(),
        "severity": severity,
        "summary": summary,
        "latest_live_result": latest_live_result,
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "open_orders_status": open_orders_status,
        "reconciliation_summary": reconciliation_summary,
        "daily_cap_status": daily_cap_status,
        "recommended_action": recommended_action,
        "safe_commands": _safe_commands(),
        "artifacts": {
            _JSON_FILENAME: str(root / _JSON_FILENAME),
            _MD_FILENAME: str(root / _MD_FILENAME),
        },
    }
    atomic_write_json(root / _JSON_FILENAME, payload)
    (root / _MD_FILENAME).write_text(_build_markdown(payload), encoding="utf-8")
    return payload


def _summarize_live_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {
            "status": "MISSING",
            "submit_attempted": False,
            "placed_count": 0,
            "rejected_count": 0,
            "failure_stage": None,
            "blocking_reasons": ["live_result_missing"],
            "warnings": [],
        }
    return {
        "status": str(payload.get("status") or "UNKNOWN"),
        "submit_attempted": bool(payload.get("submit_attempted")),
        "placed_count": int(payload.get("placed_count") or 0),
        "rejected_count": int(payload.get("rejected_count") or 0),
        "failure_stage": payload.get("failure_stage"),
        "blocking_reasons": _string_list(payload.get("blocking_reasons")),
        "warnings": _string_list(payload.get("warnings")),
    }


def _summarize_open_orders_status(*, cancel_plan: Any, readonly: Any) -> dict[str, Any]:
    if isinstance(cancel_plan, Mapping):
        return {
            "source": "cancel_plan",
            "open_orders_count": int(cancel_plan.get("open_orders_count") or 0),
            "cancel_candidates_count": len(list(cancel_plan.get("cancel_candidates") or [])),
            "status": cancel_plan.get("status"),
        }
    orders = list((readonly or {}).get("open_orders") or []) if isinstance(readonly, Mapping) else []
    return {
        "source": "readonly_preflight",
        "open_orders_count": len(orders),
        "cancel_candidates_count": len(orders),
        "status": "UNPLANNED",
    }


def _summarize_reconciliation(*, live_result: Any, readonly: Any) -> dict[str, Any]:
    if isinstance(live_result, Mapping) and isinstance(live_result.get("reconciliation_summary"), Mapping):
        return dict(live_result.get("reconciliation_summary") or {})
    if isinstance(readonly, Mapping) and isinstance(readonly.get("reconciliation_summary"), Mapping):
        return dict(readonly.get("reconciliation_summary") or {})
    return {"count": 0, "highest_severity": "INFO", "blocking_count": 0}


def _summarize_daily_cap(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"daily_cap_consumed": False, "daily_cap_reason": "unknown"}
    return {
        "daily_cap_consumed": bool(payload.get("daily_cap_consumed")),
        "daily_cap_reason": str(payload.get("daily_cap_reason") or ""),
        "requested_notional": payload.get("requested_notional"),
    }


def _derive_severity(*, live_result: Any, blocking_reasons: list[str], open_orders_status: Mapping[str, Any], reconciliation_summary: Mapping[str, Any]) -> str:
    status = str((live_result or {}).get("status") or "").upper() if isinstance(live_result, Mapping) else ""
    if status == "ERROR":
        return "CRITICAL"
    if int(reconciliation_summary.get("blocking_count") or 0) > 0:
        return "CRITICAL"
    if int(open_orders_status.get("open_orders_count") or 0) > 0:
        return "ERROR"
    if blocking_reasons:
        return "ERROR"
    if _string_list((live_result or {}).get("warnings")) if isinstance(live_result, Mapping) else []:
        return "WARNING"
    return "INFO"


def _derive_summary(*, severity: str, latest_live_result: Mapping[str, Any], open_orders_status: Mapping[str, Any]) -> str:
    return (
        f"{severity} live incident snapshot. "
        f"Latest live status={latest_live_result.get('status')}, "
        f"submit_attempted={latest_live_result.get('submit_attempted')}, "
        f"open_orders={open_orders_status.get('open_orders_count')}."
    )


def _derive_recommended_action(*, severity: str, latest_live_result: Mapping[str, Any]) -> str:
    if severity == "CRITICAL" or str(latest_live_result.get("status") or "").upper() == "ERROR":
        return "Set HALTED immediately and investigate before any further live action."
    if severity == "ERROR":
        return "Set OFF, generate a cancel plan, and re-run readonly preflight before continuing."
    if severity == "WARNING":
        return "Keep OFF or READ_ONLY until the warnings are reviewed manually."
    return "No incident action required beyond manual review."


def _safe_commands() -> dict[str, str]:
    return {
        "set_off": "env PYTHONPATH=. BINANCE_LIVE_MODE=OFF .venv/bin/python -m src.tools.evaluate_binance_live_operations",
        "set_halted": "PYTHONPATH=. .venv/bin/python -m src.tools.halt_binance_live_operations --reason manual_halt",
        "readonly_preflight": "PYTHONPATH=. .venv/bin/python -m src.tools.run_binance_mainnet_readonly_preflight",
        "evaluate_readiness": "PYTHONPATH=. .venv/bin/python -m src.tools.evaluate_binance_live_readiness",
        "generate_cancel_plan": "PYTHONPATH=. .venv/bin/python -m src.tools.run_binance_live_cancel_open_orders --prepare-only",
    }


def _build_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Binance Live Incident Report",
        "",
        f"- Incident ID: {payload.get('incident_id')}",
        f"- Severity: {payload.get('severity')}",
        f"- Generated At UTC: {payload.get('generated_at_utc')}",
        f"- Summary: {payload.get('summary')}",
        f"- Recommended Action: {payload.get('recommended_action')}",
        "",
        "## Blocking Reasons",
    ]
    blockers = list(payload.get("blocking_reasons") or [])
    if blockers:
        lines.extend([f"- {item}" for item in blockers])
    else:
        lines.append("- None")
    lines.extend(["", "## Warnings"])
    warnings = list(payload.get("warnings") or [])
    if warnings:
        lines.extend([f"- {item}" for item in warnings])
    else:
        lines.append("- None")
    lines.extend(["", "## Safe Commands"])
    for key, value in dict(payload.get("safe_commands") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    return "\n".join(lines)


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in list(value or []) if str(item).strip()]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
