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
import html
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

# Default Telegram parse_mode for outbound alert messages.
_DEFAULT_PARSE_MODE = "HTML"

# Reasons that mark an ORDER_REJECTED as routine paper-only noise. By default
# the notifier suppresses these to keep the user's chat actionable; they are
# still counted in the daily summary's rejected_orders metric.
_NOISY_REJECTION_REASON_SUBSTRINGS: tuple[str, ...] = (
    "cash_insufficient",
)

_EMOJI_BY_EVENT_TYPE: dict[str, str] = {
    "BUY_FILLED_PAPER": "\U0001F7E2",  # green circle
    "TAKE_PROFIT": "\u2705",            # white heavy check mark
    "STOP_LOSS": "\U0001F534",          # red circle
    "ORDER_REJECTED": "\u26A0\uFE0F",   # warning sign
    "WARNING": "\u26A0\uFE0F",          # warning sign
    "ERROR": "\U0001F6A8",              # rotating police light
    "DAILY_SUMMARY": "\U0001F4CA",      # bar chart
}

_SPANISH_DISCLAIMER_PAPER_MANUAL = "Paper-only \u00B7 Manual-review"
_SPANISH_DISCLAIMER_PAPER_NO_REAL = "Paper-only \u00B7 No orden real enviada"


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
    parser.add_argument(
        "--bootstrap-dedupe",
        "--mark-existing-sent",
        dest="bootstrap_dedupe",
        action="store_true",
        help=(
            "Read current semantic events and mark every alertable event_id "
            "as already sent in the dedupe state. Does not contact Telegram. "
            "Does not require TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID. Useful "
            "the first time the notifier is wired up against a populated "
            "artifacts directory, to avoid replaying historical alerts."
        ),
    )
    parser.add_argument(
        "--include-order-rejected",
        dest="include_order_rejected",
        action="store_true",
        help=(
            "Send all ORDER_REJECTED events. By default, rejected orders "
            "whose reason matches a routine pattern (e.g. cash_insufficient) "
            "are suppressed to reduce noise; they are still counted in the "
            "daily summary's rejected_orders metric."
        ),
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
    bootstrap_dedupe: bool = False,
    include_order_rejected: bool = False,
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
        bootstrap_dedupe: When True, mark every current alertable event_id as
            already sent without contacting Telegram and without requiring
            ``TELEGRAM_BOT_TOKEN`` or ``TELEGRAM_CHAT_ID``. Mutually compatible
            with ``min_severity``; mutually exclusive with sending. Always
            persists the dedupe state.
        env: Optional environment-variable map for tests.
        sender: Optional callable replacing the Telegram sender for tests.
            Signature: ``sender(bot_token, chat_id, text) -> dict``.
        now: Optional clock override for the daily-summary timestamp.

    Returns:
        Dict with ``sent``, ``skipped``, ``messages`` (text only), ``state_path``,
        ``dry_run``, ``bootstrap_dedupe``, ``marked_count``, ``paper_only``,
        ``live_trading``, and a token-redacted ``chat_id_masked``.
    """

    if min_severity not in _SEVERITY_RANK:
        raise ValueError(f"Invalid min_severity: {min_severity!r}")

    source_env = env if env is not None else os.environ

    artifacts_root = Path(artifacts_dir)
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    semantic_dir = artifacts_root / "semantic"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    resolved_state_path = (
        Path(state_path) if state_path is not None else semantic_dir / _STATE_FILENAME
    )

    # The ENABLE_CRYPTO_TELEGRAM_ALERTS gate guards real network sends only.
    # Dry-run and bootstrap-dedupe never contact Telegram, so they bypass it.
    enabled = str(source_env.get(ENABLE_FLAG) or "").strip()
    if enabled != "1" and not dry_run and not bootstrap_dedupe:
        return {
            "ok": False,
            "paper_only": True,
            "live_trading": False,
            "sent": [],
            "skipped": [],
            "messages": [],
            "dry_run": bool(dry_run),
            "bootstrap_dedupe": bool(bootstrap_dedupe),
            "marked_count": 0,
            "reason": f"{ENABLE_FLAG}_not_enabled",
            "chat_id_masked": None,
            "state_path": None,
        }

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
        if event_type == "ORDER_REJECTED" and not include_order_rejected:
            reason = str((event.get("metadata") or {}).get("reason") or "").lower()
            if any(noise in reason for noise in _NOISY_REJECTION_REASON_SUBSTRINGS):
                continue
        candidates.append(event)

    state = _load_state(resolved_state_path)
    sent_ids: set[str] = set(state.get("sent_event_ids") or [])
    sent_payload: list[dict[str, Any]] = []
    skipped_payload: list[dict[str, Any]] = []
    messages: list[str] = []

    if bootstrap_dedupe:
        before = len(sent_ids)
        for event in candidates:
            event_id = str(event.get("event_id") or "")
            if event_id and event_id not in sent_ids:
                sent_ids.add(event_id)
        marked_count = len(sent_ids) - before
        _save_state(
            resolved_state_path,
            {
                "sent_event_ids": sorted(sent_ids),
                "last_updated_at": moment.isoformat(),
                "paper_only": True,
                "bootstrap_dedupe": True,
            },
        )
        return {
            "ok": True,
            "paper_only": True,
            "live_trading": False,
            "sent": [],
            "skipped": [],
            "messages": [],
            "dry_run": False,
            "bootstrap_dedupe": True,
            "marked_count": int(marked_count),
            "considered_count": len(candidates),
            "chat_id_masked": None,
            "state_path": str(resolved_state_path),
            "min_severity": min_severity,
        }

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
        "bootstrap_dedupe": False,
        "marked_count": 0,
        "chat_id_masked": chat_id_masked,
        "state_path": str(resolved_state_path),
        "min_severity": min_severity,
    }


def format_event_message(event: dict[str, Any]) -> str:
    """Render an event as a concise HTML action card for Telegram.

    The output is suitable for ``parse_mode="HTML"``. All user-derived
    substrings (symbol, reason) are HTML-escaped. The card is intentionally
    short and mobile-friendly. No raw JSON, no severity tag, no event_type
    suffixed with underscores.
    """

    event_type = str(event.get("event_type") or "")
    symbol = str(event.get("symbol") or "")
    metadata = event.get("metadata") or {}
    quote = _quote_label(metadata.get("quote_asset"))

    if event_type == "BUY_FILLED_PAPER":
        return _format_buy_filled_card(symbol=symbol, metadata=metadata, quote=quote)
    if event_type == "TAKE_PROFIT":
        return _format_exit_card(
            symbol=symbol,
            metadata=metadata,
            quote=quote,
            emoji=_EMOJI_BY_EVENT_TYPE["TAKE_PROFIT"],
            title="TAKE PROFIT",
            manual_action_es="Si copiaste este trade, revisar toma de ganancia.",
        )
    if event_type == "STOP_LOSS":
        return _format_exit_card(
            symbol=symbol,
            metadata=metadata,
            quote=quote,
            emoji=_EMOJI_BY_EVENT_TYPE["STOP_LOSS"],
            title="STOP LOSS",
            manual_action_es="Si copiaste este trade, revisar cierre o reducci\u00F3n.",
        )
    if event_type == "ORDER_REJECTED":
        return _format_order_rejected_card(symbol=symbol, metadata=metadata)
    if event_type == "ERROR":
        return _format_error_card(event=event)
    if event_type == "WARNING":
        return _format_warning_card(event=event)
    # Fallback: minimal card from the human title + manual action.
    return _format_generic_card(event=event)


def format_daily_summary(summary: dict[str, Any], moment: datetime) -> str:
    """Render the daily portfolio summary as a concise HTML card."""

    snapshot = summary.get("snapshot") or {}
    performance = summary.get("performance") or {}
    quote = _quote_label((snapshot.get("quote_asset") if isinstance(snapshot, dict) else None) or "USDT")
    rejected_count = summary.get("rejected_orders_count")

    lines: list[str] = []
    lines.append(f"{_EMOJI_BY_EVENT_TYPE['DAILY_SUMMARY']} <b>Crypto Paper Summary</b>")
    lines.append("")
    lines.append(f"<b>Equity:</b> {_fmt_amount(snapshot.get('equity'))} {quote}")
    lines.append(
        f"<b>P&amp;L realizado:</b> {_fmt_signed_amount(snapshot.get('realized_pnl'))} {quote}"
    )
    lines.append(f"<b>Trades cerrados:</b> {_fmt_int(performance.get('closed_trades_count'))}")
    lines.append(f"<b>Win rate:</b> {_fmt_pct_int(performance.get('win_rate'))}")
    lines.append(f"<b>Take profits:</b> {_fmt_int(performance.get('take_profit_count'))}")
    lines.append(f"<b>Stop losses:</b> {_fmt_int(performance.get('stop_loss_count'))}")
    lines.append(f"<b>Fees:</b> {_fmt_amount(performance.get('total_fees'))} {quote}")
    if rejected_count is not None and int(rejected_count or 0) > 0:
        lines.append(f"<b>\u00D3rdenes rechazadas:</b> {_fmt_int(rejected_count)}")

    small_sample = _small_sample_warning(summary)
    if small_sample:
        lines.append("")
        lines.append(
            f"{_EMOJI_BY_EVENT_TYPE['WARNING']} "
            f"Muestra chica: menos de 30 trades cerrados."
        )
    lines.append("")
    lines.append(f"<b>Estado:</b>")
    lines.append(_SPANISH_DISCLAIMER_PAPER_MANUAL)
    return "\n".join(lines)


# --- Action-card renderers --------------------------------------------------


def _format_buy_filled_card(
    *, symbol: str, metadata: dict[str, Any], quote: str
) -> str:
    title = f"PAPER BUY \u2014 {html.escape(symbol)}"
    fill_price = metadata.get("fill_price")
    gross_notional = metadata.get("gross_notional")
    sl = metadata.get("stop_loss")
    tp = metadata.get("take_profit")
    lines = [
        f"{_EMOJI_BY_EVENT_TYPE['BUY_FILLED_PAPER']} <b>{title}</b>",
        "",
        "<b>Acci\u00F3n manual:</b>",
        "Revisar compra manual. No ejecutar autom\u00E1tico.",
        "",
        f"<b>Precio ref:</b> {_fmt_price(fill_price)}",
        f"<b>Monto paper:</b> {_fmt_amount(gross_notional)} {quote}",
    ]
    if sl is not None:
        lines.append(f"<b>Stop loss:</b> {_fmt_price(sl)}")
    if tp is not None:
        lines.append(f"<b>Take profit:</b> {_fmt_price(tp)}")
    lines.append("")
    lines.append("<b>Estado:</b>")
    lines.append(_SPANISH_DISCLAIMER_PAPER_MANUAL)
    return "\n".join(lines)


def _format_exit_card(
    *,
    symbol: str,
    metadata: dict[str, Any],
    quote: str,
    emoji: str,
    title: str,
    manual_action_es: str,
) -> str:
    head = f"{title} \u2014 {html.escape(symbol)}"
    entry = metadata.get("entry_average_price")
    exit_price = metadata.get("fill_price")
    realized = metadata.get("realized_pnl")
    return_pct = metadata.get("return_pct")
    lines = [
        f"{emoji} <b>{head}</b>",
        "",
        "<b>Acci\u00F3n manual:</b>",
        manual_action_es,
        "",
        f"<b>Entry promedio:</b> {_fmt_price(entry)}",
        f"<b>Exit paper:</b> {_fmt_price(exit_price)}",
        f"<b>P&amp;L realizado:</b> {_fmt_signed_amount(realized)} {quote}",
    ]
    if return_pct is not None:
        lines.append(f"<b>Return:</b> {_fmt_signed_pct(return_pct)}")
    lines.append("")
    lines.append("<b>Estado:</b>")
    lines.append(_SPANISH_DISCLAIMER_PAPER_NO_REAL)
    return "\n".join(lines)


def _format_order_rejected_card(*, symbol: str, metadata: dict[str, Any]) -> str:
    head = f"ORDEN RECHAZADA \u2014 {html.escape(symbol)}"
    reason = str(metadata.get("reason") or "unspecified")
    lines = [
        f"{_EMOJI_BY_EVENT_TYPE['ORDER_REJECTED']} <b>{head}</b>",
        "",
        "<b>Motivo:</b>",
        html.escape(reason),
        "",
        "<b>Acci\u00F3n manual:</b>",
        "No copiar autom\u00E1ticamente. Revisar s\u00F3lo si se repite demasiado.",
        "",
        "<b>Estado:</b>",
        "Paper-only",
    ]
    return "\n".join(lines)


def _format_error_card(*, event: dict[str, Any]) -> str:
    title = str(event.get("human_title") or "ERROR")
    manual = str(event.get("manual_action") or "Investigar logs.")
    short_message = str(event.get("human_message") or "")[:240]
    lines = [
        f"{_EMOJI_BY_EVENT_TYPE['ERROR']} <b>{html.escape(title)}</b>",
        "",
        "<b>Acci\u00F3n manual:</b>",
        html.escape(manual),
    ]
    if short_message:
        lines.extend(["", html.escape(short_message)])
    lines.append("")
    lines.append("<b>Estado:</b>")
    lines.append(_SPANISH_DISCLAIMER_PAPER_MANUAL)
    return "\n".join(lines)


def _format_warning_card(*, event: dict[str, Any]) -> str:
    title = str(event.get("human_title") or "Warning")
    metadata = event.get("metadata") or {}
    raw = str(metadata.get("raw_warning") or event.get("human_message") or "")[:240]
    lines = [
        f"{_EMOJI_BY_EVENT_TYPE['WARNING']} <b>{html.escape(title)}</b>",
        "",
        html.escape(raw),
        "",
        "<b>Estado:</b>",
        _SPANISH_DISCLAIMER_PAPER_MANUAL,
    ]
    return "\n".join(lines)


def _format_generic_card(*, event: dict[str, Any]) -> str:
    title = str(event.get("human_title") or event.get("event_type") or "Event")
    manual = str(event.get("manual_action") or "").strip()
    lines = [f"<b>{html.escape(title)}</b>"]
    if manual:
        lines.append("")
        lines.append("<b>Acci\u00F3n manual:</b>")
        lines.append(html.escape(manual))
    lines.append("")
    lines.append("<b>Estado:</b>")
    lines.append(_SPANISH_DISCLAIMER_PAPER_MANUAL)
    return "\n".join(lines)


# --- Formatting helpers -----------------------------------------------------


def _quote_label(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text or "USDT"


def _small_sample_warning(summary: dict[str, Any]) -> bool:
    warnings = summary.get("warnings") or []
    for warning in warnings:
        text = str(warning or "")
        if text.startswith("small_sample_size:"):
            return True
    return False


def _fmt_price(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:,.2f}"


def _fmt_amount(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:,.2f}"


def _fmt_signed_amount(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    sign = "+" if parsed >= 0 else "\u2212"  # minus sign for negatives
    return f"{sign}{abs(parsed):,.2f}"


def _fmt_signed_pct(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    sign = "+" if parsed >= 0 else "\u2212"
    return f"{sign}{abs(parsed) * 100.0:.2f}%"


def _fmt_pct_int(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    return f"{round(parsed * 100.0)}%"


def _fmt_int(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _default_sender(*, bot_token: str, chat_id: str, text: str) -> dict[str, Any]:
    return send_telegram_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text,
        parse_mode=_DEFAULT_PARSE_MODE,
    )


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
        bootstrap_dedupe=bool(args.bootstrap_dedupe),
        include_order_rejected=bool(args.include_order_rejected),
    )
    sys.stdout.write(
        json.dumps(
            {
                "ok": result.get("ok"),
                "paper_only": result.get("paper_only"),
                "live_trading": result.get("live_trading"),
                "dry_run": result.get("dry_run"),
                "bootstrap_dedupe": result.get("bootstrap_dedupe"),
                "marked_count": result.get("marked_count"),
                "considered_count": result.get("considered_count"),
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
    if args.bootstrap_dedupe:
        sys.stdout.write(
            f"[CRYPTO-TELEGRAM-BOOTSTRAP] marked {result.get('marked_count') or 0} "
            f"event_ids as already-sent (considered {result.get('considered_count') or 0}, "
            f"min_severity={result.get('min_severity')}). No Telegram contact made.\n"
        )
    if args.dry_run:
        for message in result.get("messages") or []:
            sys.stdout.write("---\n")
            sys.stdout.write(message + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
