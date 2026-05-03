"""Telegram alert dispatcher for crypto paper-forward semantic events.

Reads (or rebuilds) the semantic event artifact under
``artifacts/crypto_paper/semantic/`` and sends concise Telegram messages for
the alertable subset only. Maintains a JSON dedupe state so already-sent
events are not resent on subsequent runs.

Refuses to send unless ``ENABLE_CRYPTO_TELEGRAM_ALERTS=1`` is exported.
Supports ``--dry-run`` (prints messages without contacting Telegram),
``--daily-summary`` (also sends a one-line portfolio summary), and
``--force`` (resends previously-sent events). Never logs or returns the bot
token; the resolved chat id is masked.

Paper-only / manual-review only. This tool never executes trades, never
mirrors signals into a live account, and never contacts a broker.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.notifications.telegram_notifier import (
    TelegramConfigError,
    TelegramSendError,
    mask_chat_id,
    redact_token,
    resolve_credentials,
    send_telegram_message,
)
from src.reports.crypto_paper_semantics import (
    ALERTABLE_EVENT_TYPES,
    PAPER_DISCLAIMER,
    SEMANTIC_SEVERITIES,
    build_semantic_layer,
)


ENABLE_FLAG = "ENABLE_CRYPTO_TELEGRAM_ALERTS"

_DEFAULT_MIN_SEVERITY = "ACTION"
_SEVERITY_RANK: dict[str, int] = {name: idx for idx, name in enumerate(SEMANTIC_SEVERITIES)}
_STATE_FILENAME = "telegram_alert_state.json"
_DAILY_SUMMARY_PREFIX = "daily-summary:"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Send concise Telegram alerts for crypto paper-forward semantic events. "
            f"Refuses to send unless {ENABLE_FLAG}=1. Paper-only, manual-review only."
        )
    )
    parser.add_argument(
        "--artifacts-dir",
        default="artifacts/crypto_paper",
        help="Crypto paper artifacts root (default: artifacts/crypto_paper).",
    )
    parser.add_argument(
        "--state-path",
        default=None,
        help=(
            "Path to dedupe state JSON. Default: "
            "<artifacts-dir>/semantic/telegram_alert_state.json"
        ),
    )
    parser.add_argument(
        "--rebuild-semantic",
        action="store_true",
        help="Force rebuild of the semantic layer before alerting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print messages without contacting Telegram. Skips dedupe writes.",
    )
    parser.add_argument(
        "--daily-summary",
        action="store_true",
        help="Also send a one-line daily portfolio summary.",
    )
    parser.add_argument(
        "--min-severity",
        default=_DEFAULT_MIN_SEVERITY,
        choices=list(SEMANTIC_SEVERITIES),
        help=f"Minimum severity to alert on (default: {_DEFAULT_MIN_SEVERITY}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Resend events even if their event_id is already in the dedupe state.",
    )
    return parser


def notify_crypto_paper_telegram(
    *,
    artifacts_dir: str | Path,
    state_path: str | Path | None = None,
    dry_run: bool = False,
    daily_summary: bool = False,
    min_severity: str = _DEFAULT_MIN_SEVERITY,
    force: bool = False,
    rebuild_semantic: bool = False,
    env: dict[str, str] | None = None,
    sender: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Dispatch Telegram alerts for the latest crypto paper semantic events.

    Args:
        artifacts_dir: Crypto paper artifacts root directory.
        state_path: Override path for the dedupe state JSON.
        dry_run: When True, do not contact Telegram and do not write state.
        daily_summary: When True, also send a portfolio summary message.
        min_severity: Minimum severity to alert on.
        force: When True, ignore dedupe state and resend all alertable events.
        rebuild_semantic: When True, rebuild the semantic layer first.
        env: Optional environment-variable map for tests.
        sender: Optional callable replacing the Telegram sender for tests.
            Signature: ``sender(bot_token, chat_id, text) -> dict``.
        now: Optional clock override for the daily-summary timestamp.

    Returns:
        Dict with ``sent``, ``skipped``, ``messages`` (text only), ``state_path``,
        ``dry_run``, ``paper_only``, and a token-redacted ``chat_id_masked``.
    """

    if min_severity not in _SEVERITY_RANK:
        raise ValueError(f"Invalid min_severity: {min_severity!r}")

    source_env = env if env is not None else os.environ
    enabled = str(source_env.get(ENABLE_FLAG) or "").strip()
    if enabled != "1":
        return {
            "ok": False,
            "paper_only": True,
            "live_trading": False,
            "sent": [],
            "skipped": [],
            "messages": [],
            "dry_run": bool(dry_run),
            "reason": f"{ENABLE_FLAG}_not_enabled",
            "chat_id_masked": None,
            "state_path": None,
        }

    artifacts_root = Path(artifacts_dir)
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    semantic_dir = artifacts_root / "semantic"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    resolved_state_path = (
        Path(state_path) if state_path is not None else semantic_dir / _STATE_FILENAME
    )

    semantic_layer = _load_or_build_semantic_layer(
        artifacts_root=artifacts_root,
        rebuild=rebuild_semantic,
        moment=moment,
    )
    events = list(semantic_layer.get("events") or [])

    threshold = _SEVERITY_RANK[min_severity]
    candidates: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        severity = str(event.get("severity") or "INFO")
        if event_type not in ALERTABLE_EVENT_TYPES:
            continue
        if _SEVERITY_RANK.get(severity, -1) < threshold:
            continue
        candidates.append(event)

    state = _load_state(resolved_state_path)
    sent_ids: set[str] = set(state.get("sent_event_ids") or [])
    sent_payload: list[dict[str, Any]] = []
    skipped_payload: list[dict[str, Any]] = []
    messages: list[str] = []

    bot_token: str | None = None
    chat_id: str | None = None
    chat_id_masked: str | None = None
    if not dry_run and (candidates or daily_summary):
        try:
            bot_token, chat_id = resolve_credentials(env=source_env)
        except TelegramConfigError as exc:
            return {
                "ok": False,
                "paper_only": True,
                "live_trading": False,
                "sent": [],
                "skipped": [],
                "messages": [],
                "dry_run": False,
                "reason": str(exc),
                "chat_id_masked": None,
                "state_path": str(resolved_state_path),
            }
        chat_id_masked = mask_chat_id(chat_id)

    transport = sender if sender is not None else _default_sender

    for event in candidates:
        event_id = str(event.get("event_id") or "")
        if not force and event_id in sent_ids:
            skipped_payload.append({"event_id": event_id, "reason": "already_sent"})
            continue
        text = format_event_message(event)
        messages.append(text)
        if dry_run:
            sent_payload.append({"event_id": event_id, "dry_run": True})
            continue
        try:
            transport(bot_token=bot_token or "", chat_id=chat_id or "", text=text)
        except TelegramSendError as exc:
            return {
                "ok": False,
                "paper_only": True,
                "live_trading": False,
                "sent": sent_payload,
                "skipped": skipped_payload,
                "messages": messages,
                "dry_run": False,
                "reason": redact_token(str(exc), bot_token or ""),
                "chat_id_masked": chat_id_masked,
                "state_path": str(resolved_state_path),
            }
        sent_payload.append({"event_id": event_id})
        sent_ids.add(event_id)

    if daily_summary:
        summary_payload = semantic_layer.get("summary") or {}
        text = format_daily_summary(summary_payload, moment)
        summary_event_id = f"{_DAILY_SUMMARY_PREFIX}{moment.strftime('%Y-%m-%d')}"
        if not force and summary_event_id in sent_ids:
            skipped_payload.append({"event_id": summary_event_id, "reason": "already_sent"})
        else:
            messages.append(text)
            if dry_run:
                sent_payload.append({"event_id": summary_event_id, "dry_run": True})
            else:
                try:
                    transport(bot_token=bot_token or "", chat_id=chat_id or "", text=text)
                except TelegramSendError as exc:
                    return {
                        "ok": False,
                        "paper_only": True,
                        "live_trading": False,
                        "sent": sent_payload,
                        "skipped": skipped_payload,
                        "messages": messages,
                        "dry_run": False,
                        "reason": redact_token(str(exc), bot_token or ""),
                        "chat_id_masked": chat_id_masked,
                        "state_path": str(resolved_state_path),
                    }
                sent_payload.append({"event_id": summary_event_id})
                sent_ids.add(summary_event_id)

    if not dry_run:
        _save_state(
            resolved_state_path,
            {
                "sent_event_ids": sorted(sent_ids),
                "last_updated_at": moment.isoformat(),
                "paper_only": True,
            },
        )

    return {
        "ok": True,
        "paper_only": True,
        "live_trading": False,
        "sent": sent_payload,
        "skipped": skipped_payload,
        "messages": messages,
        "dry_run": bool(dry_run),
        "chat_id_masked": chat_id_masked,
        "state_path": str(resolved_state_path),
        "min_severity": min_severity,
    }


def format_event_message(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    symbol = str(event.get("symbol") or "")
    metadata = event.get("metadata") or {}
    severity = str(event.get("severity") or "INFO")
    lines: list[str] = []
    head = f"[{severity}] {event_type}"
    if symbol:
        head += f" {symbol}"
    lines.append(head)
    lines.append(str(event.get("human_title") or event_type))

    if event_type == "BUY_FILLED_PAPER":
        lines.append(
            f"qty={_fmt(metadata.get('quantity'))} fill_price={_fmt(metadata.get('fill_price'))} "
            f"notional={_fmt(metadata.get('gross_notional'))}"
        )
        sl = metadata.get("stop_loss")
        tp = metadata.get("take_profit")
        if sl is not None or tp is not None:
            lines.append(f"stop={_fmt(sl)} take={_fmt(tp)}")
    elif event_type in ("TAKE_PROFIT", "STOP_LOSS"):
        lines.append(
            f"trigger={_fmt(metadata.get('trigger_price'))} "
            f"fill={_fmt(metadata.get('fill_price'))} "
            f"realized_pnl={_fmt(metadata.get('realized_pnl'))}"
        )
        sl = metadata.get("stop_loss")
        tp = metadata.get("take_profit")
        if sl is not None or tp is not None:
            lines.append(f"stop={_fmt(sl)} take={_fmt(tp)}")
    elif event_type == "ORDER_REJECTED":
        lines.append(
            f"reason={metadata.get('reason') or 'unspecified'} "
            f"notional={_fmt(metadata.get('requested_notional'))}"
        )
    elif event_type == "ERROR":
        # ERROR messages stay short; metadata is captured in the human_message.
        msg = str(event.get("human_message") or "")
        if msg:
            lines.append(msg[:300])

    manual = str(event.get("manual_action") or "").strip()
    if manual:
        lines.append(f"Action: {manual}")
    lines.append(PAPER_DISCLAIMER)
    return "\n".join(lines)


def format_daily_summary(summary: dict[str, Any], moment: datetime) -> str:
    snapshot = summary.get("snapshot") or {}
    performance = summary.get("performance") or {}
    lines = [
        f"[INFO] DAILY_SUMMARY ({moment.strftime('%Y-%m-%d')})",
        f"equity={_fmt(snapshot.get('equity'))} cash={_fmt(snapshot.get('cash'))} "
        f"realized={_fmt(snapshot.get('realized_pnl'))} unrealized={_fmt(snapshot.get('unrealized_pnl'))}",
        f"closed_trades={performance.get('closed_trades_count')} "
        f"win_rate={_fmt_pct(performance.get('win_rate'))} "
        f"take_profits={performance.get('take_profit_count')} "
        f"stop_losses={performance.get('stop_loss_count')}",
        PAPER_DISCLAIMER,
    ]
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{parsed:,.6f}".rstrip("0").rstrip(".")


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{parsed * 100.0:.2f}%"


def _default_sender(*, bot_token: str, chat_id: str, text: str) -> dict[str, Any]:
    return send_telegram_message(bot_token=bot_token, chat_id=chat_id, text=text)


def _load_or_build_semantic_layer(
    *,
    artifacts_root: Path,
    rebuild: bool,
    moment: datetime,
) -> dict[str, Any]:
    semantic_dir = artifacts_root / "semantic"
    summary_path = semantic_dir / "crypto_semantic_summary.json"
    events_path = semantic_dir / "crypto_semantic_events.json"
    if not rebuild and summary_path.exists() and events_path.exists():
        summary = _load_json(summary_path, default={})
        events = _load_json(events_path, default=[])
        if isinstance(summary, dict) and isinstance(events, list):
            return {"summary": summary, "events": events}
    return build_semantic_layer(
        artifacts_dir=artifacts_root,
        output_dir=semantic_dir,
        write=True,
        now=moment,
    )


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sent_event_ids": [], "paper_only": True}
    payload = _load_json(path, default=None)
    if not isinstance(payload, dict):
        return {"sent_event_ids": [], "paper_only": True}
    if not isinstance(payload.get("sent_event_ids"), list):
        payload["sent_event_ids"] = []
    return payload


def _save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = notify_crypto_paper_telegram(
        artifacts_dir=args.artifacts_dir,
        state_path=args.state_path,
        dry_run=bool(args.dry_run),
        daily_summary=bool(args.daily_summary),
        min_severity=str(args.min_severity),
        force=bool(args.force),
        rebuild_semantic=bool(args.rebuild_semantic),
    )
    sys.stdout.write(
        json.dumps(
            {
                "ok": result.get("ok"),
                "paper_only": result.get("paper_only"),
                "live_trading": result.get("live_trading"),
                "dry_run": result.get("dry_run"),
                "sent_count": len(result.get("sent") or []),
                "skipped_count": len(result.get("skipped") or []),
                "min_severity": result.get("min_severity"),
                "chat_id_masked": result.get("chat_id_masked"),
                "state_path": result.get("state_path"),
                "reason": result.get("reason"),
            },
            sort_keys=True,
        )
        + "\n"
    )
    if args.dry_run:
        for message in result.get("messages") or []:
            sys.stdout.write("---\n")
            sys.stdout.write(message + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
