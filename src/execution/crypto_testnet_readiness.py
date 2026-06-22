from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.brokers.binance_spot_testnet import is_testnet_base_url
from src.utils.atomic_io import atomic_write_json


_TESTNET_DIRNAME = "crypto_testnet"
_READINESS_FILENAME = "crypto_testnet_readiness.json"

_NO_CLIENT_UNAVAILABLE_PREFIXES: tuple[str, ...] = (
    "server_time_unavailable:no_client",
    "exchange_filters_unavailable:no_client",
    "exchange_reconciliation_unavailable:no_client",
)


def evaluate_crypto_testnet_readiness(
    *,
    paper_artifacts_dir: str | Path,
    testnet_artifacts_dir: str | Path | None = None,
    output_path: str | Path | None = None,
    now: datetime | None = None,
    max_heartbeat_age_minutes: int = 30,
) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    paper_root = Path(paper_artifacts_dir)
    testnet_root = (
        Path(testnet_artifacts_dir)
        if testnet_artifacts_dir is not None
        else paper_root.parent / _TESTNET_DIRNAME
    )

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
    testnet_result = _load_json(
        testnet_root / "binance_testnet_execution_result.json", default={}
    )
    exchange_state = _load_json(
        testnet_root / "binance_testnet_exchange_state.json", default={}
    )
    reconciliation = _load_json(
        testnet_root / "binance_testnet_reconciliation.json", default=[]
    )
    run_context = _derive_testnet_run_context(
        testnet_result=testnet_result,
        exchange_state=exchange_state,
    )

    checks: list[dict[str, Any]] = []
    cutoff = moment - timedelta(minutes=max(1, int(max_heartbeat_age_minutes)))

    _append_check(
        checks,
        check_id="paper_forward_result_present",
        ok=isinstance(forward_result, dict) and bool(forward_result),
        message="paper_forward/crypto_paper_forward_result.json must exist.",
        required_for=("dry_run", "submit"),
    )
    _append_check(
        checks,
        check_id="paper_forward_status_success",
        ok=str(forward_result.get("status") or "") == "SUCCESS",
        message="Latest crypto_paper_forward status must be SUCCESS.",
        required_for=("dry_run", "submit"),
        details={"status": forward_result.get("status")},
    )
    _append_check(
        checks,
        check_id="paper_forward_heartbeat_fresh",
        ok=_is_fresh(
            ((forward_result.get("heartbeat") or {}).get("last_updated_at")),
            cutoff=cutoff,
        ),
        message="Latest paper-forward heartbeat must be present and fresh.",
        required_for=("dry_run", "submit"),
        details={"heartbeat": (forward_result.get("heartbeat") or {}).get("last_updated_at")},
    )
    _append_check(
        checks,
        check_id="semantic_summary_present",
        ok=isinstance(semantic_summary, dict) and bool(semantic_summary),
        message="semantic/crypto_semantic_summary.json must exist.",
        required_for=("dry_run", "submit"),
    )
    _append_check(
        checks,
        check_id="semantic_not_blocked",
        ok=str(semantic_summary.get("operational_status") or "") not in {"ERROR", "BLOCKED"},
        message="Semantic operational status must not be ERROR or BLOCKED.",
        required_for=("dry_run", "submit"),
        details={"operational_status": semantic_summary.get("operational_status")},
    )
    _append_check(
        checks,
        check_id="semantic_no_critical_events",
        ok=(int((semantic_summary.get("events_count_by_severity") or {}).get("CRITICAL") or 0) == 0
            and int((semantic_summary.get("events_count_by_severity") or {}).get("ERROR") or 0) == 0),
        message="Semantic summary must not report ERROR/CRITICAL event counts.",
        required_for=("dry_run", "submit"),
        details={"events_count_by_severity": semantic_summary.get("events_count_by_severity")},
    )
    _append_check(
        checks,
        check_id="semantic_no_stale_data",
        ok=int(semantic_summary.get("stale_data_count") or 0) == 0,
        message="Semantic summary must not report stale market data.",
        required_for=("dry_run", "submit"),
        details={"stale_data_count": semantic_summary.get("stale_data_count")},
    )
    _append_check(
        checks,
        check_id="dashboard_data_present",
        ok=isinstance(dashboard_data, dict) and bool(dashboard_data),
        message="dashboard/dashboard_data.json must exist.",
        required_for=("dry_run", "submit"),
    )
    _append_check(
        checks,
        check_id="dashboard_fresh",
        ok=_is_fresh(dashboard_data.get("generated_at"), cutoff=cutoff),
        message="Dashboard generated_at must be present and fresh.",
        required_for=("dry_run", "submit"),
        details={"generated_at": dashboard_data.get("generated_at")},
    )
    _append_check(
        checks,
        check_id="telegram_notifier_healthy",
        ok=(not notify_result) or str(notify_result.get("severity") or "INFO") not in {"ERROR", "CRITICAL"},
        message="Telegram notifier status must not be ERROR or CRITICAL.",
        required_for=("submit",),
        details={"severity": notify_result.get("severity"), "category": notify_result.get("category")},
    )
    _append_check(
        checks,
        check_id="testnet_result_present",
        ok=isinstance(testnet_result, dict) and bool(testnet_result),
        message="crypto_testnet/binance_testnet_execution_result.json must exist.",
        required_for=("dry_run", "submit"),
    )
    _append_check(
        checks,
        check_id="testnet_base_url_is_testnet",
        ok=is_testnet_base_url(str(testnet_result.get("base_url") or "")) if testnet_result else False,
        message="Latest testnet result must point to a Binance Spot Testnet base URL.",
        required_for=("dry_run", "submit"),
        details={"base_url": testnet_result.get("base_url")},
    )
    _append_check(
        checks,
        check_id="testnet_last_result_ok",
        ok=bool(testnet_result.get("ok")) and str(testnet_result.get("severity") or "INFO") not in {"ERROR", "CRITICAL"},
        message="Latest testnet result must be ok and free of ERROR/CRITICAL severity.",
        required_for=("dry_run", "submit"),
        details={
            "ok": testnet_result.get("ok"),
            "severity": testnet_result.get("severity"),
            "category": testnet_result.get("category"),
        },
    )
    _append_check(
        checks,
        check_id="testnet_client_context_valid",
        ok=bool(
            run_context["local_dry_run_no_client"]
            or run_context["connected_client_available"]
        ),
        message=(
            "Latest testnet run must be either a local dry-run without client "
            "or a connected Binance Spot Testnet run with client validation."
        ),
        required_for=("dry_run", "submit"),
        details={
            "local_dry_run_no_client": run_context["local_dry_run_no_client"],
            "connected_client_available": run_context["connected_client_available"],
            "mode": run_context["mode"],
        },
    )
    _append_check(
        checks,
        check_id="testnet_heartbeat_fresh",
        ok=_is_fresh(
            ((testnet_result.get("heartbeat") or {}).get("last_updated_at"))
            or testnet_result.get("last_attempt_at")
            or ((testnet_result.get("result") or {}).get("metadata") or {}).get("generated_at"),
            cutoff=cutoff,
        ),
        message="Latest testnet heartbeat must be present and fresh.",
        required_for=("dry_run", "submit"),
        details={"heartbeat": (testnet_result.get("heartbeat") or {}).get("last_updated_at")},
    )
    _append_check(
        checks,
        check_id="submit_requires_connected_client",
        ok=bool(run_context["connected_client_available"]),
        message="Controlled submit requires a connected Binance Spot Testnet client.",
        required_for=("submit",),
        details={
            "connected_client_available": run_context["connected_client_available"],
            "mode": run_context["mode"],
        },
    )
    _append_check(
        checks,
        check_id="submit_requires_server_time_validation",
        ok=bool(run_context["server_time_available"]),
        message="Controlled submit requires real server time validation.",
        required_for=("submit",),
        details={"server_time_available": run_context["server_time_available"]},
    )
    _append_check(
        checks,
        check_id="submit_requires_exchange_filters",
        ok=bool(run_context["exchange_filters_available"]),
        message="Controlled submit requires real exchange filters validation.",
        required_for=("submit",),
        details={"exchange_filters_available": run_context["exchange_filters_available"]},
    )
    _append_check(
        checks,
        check_id="exchange_state_present",
        ok=isinstance(exchange_state, dict) and bool(exchange_state),
        message="crypto_testnet/binance_testnet_exchange_state.json must exist.",
        required_for=("dry_run", "submit"),
    )
    _append_check(
        checks,
        check_id="submit_requires_exchange_reconciliation",
        ok=bool(run_context["exchange_reconciliation_available"]),
        message="Controlled submit requires real exchange reconciliation.",
        required_for=("submit",),
        details={
            "exchange_reconciliation_available": run_context["exchange_reconciliation_available"],
            "account_checked": exchange_state.get("account_checked"),
            "open_orders_checked": exchange_state.get("open_orders_checked"),
        },
    )
    _append_check(
        checks,
        check_id="reconciliation_artifact_present",
        ok=isinstance(reconciliation, list),
        message="crypto_testnet/binance_testnet_reconciliation.json must exist.",
        required_for=("dry_run", "submit"),
    )
    mismatch_count = int(((exchange_state.get("reconciliation_summary") or {}).get("count")) or 0)
    _append_check(
        checks,
        check_id="reconciliation_clean",
        ok=isinstance(exchange_state, dict) and bool(exchange_state) and mismatch_count == 0,
        message="Exchange reconciliation must report zero mismatches.",
        required_for=("dry_run", "submit"),
        details={
            "reconciliation_summary": exchange_state.get("reconciliation_summary"),
            "mismatches": exchange_state.get("mismatches"),
        },
    )
    _append_check(
        checks,
        check_id="kill_switch_not_active",
        ok=not _kill_switch_enabled(testnet_root),
        message="Testnet kill switch file must not be active.",
        required_for=("dry_run", "submit"),
    )

    dry_run_ready = all(
        check["ok"]
        for check in checks
        if "dry_run" in tuple(check.get("required_for") or ())
    )
    submit_ready = all(
        check["ok"]
        for check in checks
        if "submit" in tuple(check.get("required_for") or ())
    )
    readiness = {
        "generated_at": moment.isoformat(),
        "paper_only": True,
        "live_trading": False,
        "testnet": True,
        "status": "READY" if dry_run_ready else "NOT_READY",
        "dry_run_ready": bool(dry_run_ready),
        "submit_ready": bool(submit_ready),
        "next_allowed_mode": (
            "controlled_submit"
            if submit_ready
            else ("order_test_only_or_dry_run" if dry_run_ready else "blocked")
        ),
        "max_heartbeat_age_minutes": int(max_heartbeat_age_minutes),
        "checks": checks,
        "artifacts": {
            "paper_forward_result": str(paper_root / "paper_forward" / "crypto_paper_forward_result.json"),
            "semantic_summary": str(paper_root / "semantic" / "crypto_semantic_summary.json"),
            "dashboard_data": str(paper_root / "dashboard" / "dashboard_data.json"),
            "telegram_notify_result": str(paper_root / "semantic" / "telegram_notify_result.json"),
            "testnet_result": str(testnet_root / "binance_testnet_execution_result.json"),
            "exchange_state": str(testnet_root / "binance_testnet_exchange_state.json"),
            "reconciliation": str(testnet_root / "binance_testnet_reconciliation.json"),
        },
        "summary": {
            "paper_forward_status": forward_result.get("status"),
            "semantic_operational_status": semantic_summary.get("operational_status"),
            "dashboard_operational_status": dashboard_data.get("operational_status"),
            "telegram_status": notify_result.get("severity") or notify_result.get("category"),
            "testnet_status": testnet_result.get("severity") or testnet_result.get("category"),
            "reconciliation_mismatch_count": mismatch_count,
            "testnet_order_test_only": testnet_result.get("order_test_only"),
            "testnet_run_mode": run_context["mode"],
            "connected_client_available": run_context["connected_client_available"],
            "server_time_available": run_context["server_time_available"],
            "exchange_filters_available": run_context["exchange_filters_available"],
            "exchange_reconciliation_available": run_context["exchange_reconciliation_available"],
        },
        "warnings": [
            check["message"]
            for check in checks
            if not check["ok"]
        ],
    }

    target_path = (
        Path(output_path)
        if output_path is not None
        else testnet_root / _READINESS_FILENAME
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target_path, readiness)
    readiness["artifact_path"] = str(target_path)
    return readiness


def _derive_testnet_run_context(
    *,
    testnet_result: Any,
    exchange_state: Any,
) -> dict[str, Any]:
    result = testnet_result if isinstance(testnet_result, dict) else {}
    state = exchange_state if isinstance(exchange_state, dict) else {}
    warnings = [str(item or "").strip().lower() for item in list(result.get("warnings") or [])]
    time_sync = result.get("time_sync") or {}
    server_time_available = bool(isinstance(time_sync, dict) and time_sync.get("checked"))
    exchange_filters_available = not any(
        warning.startswith("exchange_filters_unavailable:")
        for warning in warnings
    )
    exchange_reconciliation_available = bool(
        state.get("account_checked") and state.get("open_orders_checked")
    ) and str(state.get("reason") or "").strip().lower() != "no_client"
    connected_client_available = bool(
        server_time_available
        or exchange_reconciliation_available
        or str(result.get("api_key_masked") or "").strip()
    )
    local_dry_run_no_client = bool(
        result.get("dry_run")
        and not connected_client_available
        and (
            any(item in warnings for item in _NO_CLIENT_UNAVAILABLE_PREFIXES)
            or str(state.get("reason") or "").strip().lower() == "no_client"
        )
    )
    mode = (
        "TESTNET_DRY_RUN_LOCAL"
        if local_dry_run_no_client
        else ("TESTNET_CONNECTED" if connected_client_available else "TESTNET_UNKNOWN")
    )
    return {
        "mode": mode,
        "local_dry_run_no_client": local_dry_run_no_client,
        "connected_client_available": connected_client_available,
        "server_time_available": server_time_available,
        "exchange_filters_available": exchange_filters_available,
        "exchange_reconciliation_available": exchange_reconciliation_available,
    }


def _append_check(
    checks: list[dict[str, Any]],
    *,
    check_id: str,
    ok: bool,
    message: str,
    required_for: tuple[str, ...],
    details: dict[str, Any] | None = None,
) -> None:
    item: dict[str, Any] = {
        "check_id": check_id,
        "ok": bool(ok),
        "message": message,
        "required_for": list(required_for),
    }
    if details:
        item["details"] = _redact_dict(details)
    checks.append(item)


def _kill_switch_enabled(testnet_root: Path) -> bool:
    path = testnet_root / "binance_testnet_kill_switch.json"
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return True
    return bool(isinstance(payload, dict) and payload.get("enabled") is True)


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


def _redact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        lower = str(key).lower()
        if "secret" in lower or "signature" in lower or lower == "api_key" or lower.endswith("_api_key"):
            continue
        redacted[key] = value
    return redacted


__all__ = ["evaluate_crypto_testnet_readiness"]
