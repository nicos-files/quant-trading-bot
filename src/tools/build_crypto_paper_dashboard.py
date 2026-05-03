"""Build a static, paper-only dashboard from crypto paper-forward artifacts.

Reads the canonical paper-forward artifacts under ``artifacts/crypto_paper/`` and
the semantic layer under ``artifacts/crypto_paper/semantic/`` (rebuilding it on
the fly when missing) and writes three artifacts under
``artifacts/crypto_paper/dashboard/``:

- ``index.html`` — single-file static dashboard with embedded CSS, no external
  network or CDN dependencies.
- ``dashboard_data.json`` — machine-readable mirror of the same data.
- ``latest_summary.md`` — short markdown summary suitable for sharing.

Paper-only / manual-review only. This tool never executes trades, never calls
broker or live APIs, and never invents fills or P&L.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.reports.crypto_paper_semantics import (
    PAPER_DISCLAIMER,
    build_semantic_layer,
)


_DASHBOARD_DIRNAME = "dashboard"
_INDEX_FILENAME = "index.html"
_DATA_FILENAME = "dashboard_data.json"
_SUMMARY_FILENAME = "latest_summary.md"

_RECENT_FILLS_LIMIT = 10
_RECENT_EXITS_LIMIT = 10
_RECENT_EVENTS_LIMIT = 25


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a static, paper-only dashboard from crypto paper-forward artifacts. "
            "No network, no live trading, manual review only."
        )
    )
    parser.add_argument(
        "--artifacts-dir",
        default="artifacts/crypto_paper",
        help="Crypto paper artifacts root (default: artifacts/crypto_paper).",
    )
    parser.add_argument(
        "--dashboard-dir",
        default=None,
        help="Destination for dashboard files (default: <artifacts-dir>/dashboard).",
    )
    parser.add_argument(
        "--rebuild-semantic",
        action="store_true",
        help="Force rebuild of the semantic layer from the canonical artifacts.",
    )
    return parser


def build_crypto_paper_dashboard(
    *,
    artifacts_dir: str | Path,
    dashboard_dir: str | Path | None = None,
    rebuild_semantic: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    artifacts_root = Path(artifacts_dir)
    target_dir = (
        Path(dashboard_dir)
        if dashboard_dir is not None
        else artifacts_root / _DASHBOARD_DIRNAME
    )
    target_dir.mkdir(parents=True, exist_ok=True)

    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    semantic_layer = _load_or_build_semantic_layer(
        artifacts_root=artifacts_root,
        rebuild=rebuild_semantic,
        moment=moment,
    )

    fills = _load_json(artifacts_root / "crypto_paper_fills.json", default=[])
    orders = _load_json(artifacts_root / "crypto_paper_orders.json", default=[])
    exit_events = _load_json(artifacts_root / "crypto_paper_exit_events.json", default=[])
    positions = _load_json(artifacts_root / "crypto_paper_positions.json", default=[])

    if not isinstance(fills, list):
        fills = []
    if not isinstance(orders, list):
        orders = []
    if not isinstance(exit_events, list):
        exit_events = []
    if not isinstance(positions, list):
        positions = []

    summary = semantic_layer.get("summary") or {}
    events = semantic_layer.get("events") or []

    snapshot = summary.get("snapshot") or {}
    performance = summary.get("performance") or {}

    rejected_count = sum(
        1
        for order in orders
        if isinstance(order, dict) and str(order.get("status") or "").upper() == "REJECTED"
    )

    recent_fills = _sort_recent(
        [item for item in fills if isinstance(item, dict)],
        key="filled_at",
        limit=_RECENT_FILLS_LIMIT,
    )
    recent_exits = _sort_recent(
        [item for item in exit_events if isinstance(item, dict)],
        key="exited_at",
        limit=_RECENT_EXITS_LIMIT,
    )
    recent_events = events[:_RECENT_EVENTS_LIMIT]

    open_positions_table = [
        {
            "symbol": position.get("symbol"),
            "quantity": position.get("quantity"),
            "avg_entry_price": position.get("avg_entry_price"),
            "last_price": position.get("last_price"),
            "unrealized_pnl": position.get("unrealized_pnl"),
            "stop_loss": (position.get("metadata") or {}).get("stop_loss"),
            "take_profit": (position.get("metadata") or {}).get("take_profit"),
        }
        for position in positions
        if isinstance(position, dict)
    ]

    current_action = _select_current_action(events)

    dashboard_data = {
        "generated_at": moment.isoformat(),
        "paper_only": True,
        "not_auto_executed": True,
        "live_trading": False,
        "disclaimer": PAPER_DISCLAIMER,
        "snapshot": {
            "as_of": snapshot.get("as_of"),
            "equity": snapshot.get("equity"),
            "cash": snapshot.get("cash"),
            "positions_value": snapshot.get("positions_value"),
            "realized_pnl": snapshot.get("realized_pnl"),
            "unrealized_pnl": snapshot.get("unrealized_pnl"),
            "fees_paid": snapshot.get("fees_paid"),
            "open_positions_count": snapshot.get("open_positions_count", 0),
        },
        "performance": {
            "starting_equity": performance.get("starting_equity"),
            "total_return_pct": performance.get("total_return_pct"),
            "closed_trades_count": performance.get("closed_trades_count"),
            "open_trades_count": performance.get("open_trades_count"),
            "win_rate": performance.get("win_rate"),
            "expectancy": performance.get("expectancy"),
            "profit_factor": performance.get("profit_factor"),
            "net_profit": performance.get("net_profit"),
            "total_fees": performance.get("total_fees"),
            "total_slippage": performance.get("total_slippage"),
            "stop_loss_count": performance.get("stop_loss_count"),
            "take_profit_count": performance.get("take_profit_count"),
            "rejected_orders_count": rejected_count,
        },
        "open_positions": open_positions_table,
        "recent_fills": recent_fills,
        "recent_exits": recent_exits,
        "recent_events": recent_events,
        "current_action": current_action,
        "warnings": list(summary.get("warnings") or []),
        "forward_run_status": summary.get("forward_run_status"),
    }

    index_html = _render_index_html(dashboard_data)
    summary_md = _render_summary_markdown(dashboard_data)

    index_path = target_dir / _INDEX_FILENAME
    data_path = target_dir / _DATA_FILENAME
    summary_path = target_dir / _SUMMARY_FILENAME

    index_path.write_text(index_html, encoding="utf-8")
    data_path.write_text(
        json.dumps(dashboard_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    summary_path.write_text(summary_md, encoding="utf-8")

    return {
        "ok": True,
        "paper_only": True,
        "live_trading": False,
        "dashboard_dir": str(target_dir),
        "artifacts": {
            "index_html": str(index_path),
            "dashboard_data": str(data_path),
            "latest_summary_md": str(summary_path),
        },
        "data": dashboard_data,
    }


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


def _select_current_action(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not events:
        return None
    return {
        "event_type": events[0].get("event_type"),
        "severity": events[0].get("severity"),
        "symbol": events[0].get("symbol"),
        "human_title": events[0].get("human_title"),
        "human_message": events[0].get("human_message"),
        "manual_action": events[0].get("manual_action"),
        "paper_only": True,
        "not_auto_executed": True,
    }


def _sort_recent(items: list[dict[str, Any]], *, key: str, limit: int) -> list[dict[str, Any]]:
    sorted_items = sorted(
        items,
        key=lambda item: str(item.get(key) or ""),
        reverse=True,
    )
    return sorted_items[: max(0, int(limit))]


def _render_index_html(data: dict[str, Any]) -> str:
    snapshot = data.get("snapshot") or {}
    performance = data.get("performance") or {}
    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8" />')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1" />')
    parts.append("<title>Crypto Paper Dashboard (paper-only)</title>")
    parts.append("<style>")
    parts.append(_EMBEDDED_CSS)
    parts.append("</style>")
    parts.append("</head>")
    parts.append("<body>")
    parts.append('<header class="banner">')
    parts.append("<h1>Crypto Paper Dashboard</h1>")
    parts.append(
        '<p class="paper-only-banner">'
        f"{html.escape(PAPER_DISCLAIMER)} No live trading. No broker integration."
        "</p>"
    )
    parts.append(
        f'<p class="generated-at">Generated at {html.escape(str(data.get("generated_at") or "n/a"))}</p>'
    )
    parts.append("</header>")

    parts.append('<section class="cards">')
    parts.append(_render_card("Equity", _format_number(snapshot.get("equity"))))
    parts.append(_render_card("Cash", _format_number(snapshot.get("cash"))))
    parts.append(_render_card("Positions value", _format_number(snapshot.get("positions_value"))))
    parts.append(_render_card("Realized P&L", _format_number(snapshot.get("realized_pnl"))))
    parts.append(_render_card("Unrealized P&L", _format_number(snapshot.get("unrealized_pnl"))))
    parts.append(
        _render_card(
            "Total return",
            _format_pct(performance.get("total_return_pct"), already_pct=True),
        )
    )
    parts.append(_render_card("Closed trades", _format_int(performance.get("closed_trades_count"))))
    parts.append(_render_card("Open trades", _format_int(snapshot.get("open_positions_count"))))
    parts.append(_render_card("Win rate", _format_pct(performance.get("win_rate"))))
    parts.append(_render_card("Expectancy", _format_number(performance.get("expectancy"))))
    parts.append(_render_card("Profit factor", _format_number(performance.get("profit_factor"))))
    parts.append(_render_card("Take-profits", _format_int(performance.get("take_profit_count"))))
    parts.append(_render_card("Stop-losses", _format_int(performance.get("stop_loss_count"))))
    parts.append(_render_card("Rejected orders", _format_int(performance.get("rejected_orders_count"))))
    parts.append(_render_card("Total fees", _format_number(performance.get("total_fees"))))
    parts.append(_render_card("Total slippage", _format_number(performance.get("total_slippage"))))
    parts.append("</section>")

    current_action = data.get("current_action")
    if current_action:
        parts.append('<section class="block">')
        parts.append("<h2>Current manual action</h2>")
        parts.append(
            f'<p class="severity severity-{html.escape(str(current_action.get("severity") or "INFO").lower())}">'
            f'{html.escape(str(current_action.get("severity") or "INFO"))} — '
            f'{html.escape(str(current_action.get("event_type") or ""))}'
            "</p>"
        )
        parts.append(
            f'<p class="title">{html.escape(str(current_action.get("human_title") or ""))}</p>'
        )
        parts.append(
            f'<p class="message">{html.escape(str(current_action.get("human_message") or ""))}</p>'
        )
        parts.append(
            f'<p class="manual-action"><strong>Manual action:</strong> '
            f'{html.escape(str(current_action.get("manual_action") or ""))}</p>'
        )
        parts.append("</section>")

    parts.append('<section class="block">')
    parts.append("<h2>Open positions</h2>")
    parts.append(_render_table(
        ["symbol", "quantity", "avg_entry_price", "last_price", "unrealized_pnl", "stop_loss", "take_profit"],
        data.get("open_positions") or [],
    ))
    parts.append("</section>")

    parts.append('<section class="block">')
    parts.append("<h2>Recent fills (paper)</h2>")
    parts.append(_render_table(
        ["filled_at", "symbol", "side", "quantity", "fill_price", "gross_notional", "fee", "fill_id"],
        data.get("recent_fills") or [],
    ))
    parts.append("</section>")

    parts.append('<section class="block">')
    parts.append("<h2>Recent exits (paper)</h2>")
    parts.append(_render_table(
        ["exited_at", "symbol", "exit_reason", "exit_quantity", "trigger_price", "fill_price", "realized_pnl", "source"],
        data.get("recent_exits") or [],
    ))
    parts.append("</section>")

    parts.append('<section class="block">')
    parts.append("<h2>Recent semantic events</h2>")
    event_rows = [
        {
            "created_at": event.get("created_at"),
            "event_type": event.get("event_type"),
            "severity": event.get("severity"),
            "symbol": event.get("symbol"),
            "human_title": event.get("human_title"),
            "manual_action": event.get("manual_action"),
        }
        for event in (data.get("recent_events") or [])
    ]
    parts.append(_render_table(
        ["created_at", "event_type", "severity", "symbol", "human_title", "manual_action"],
        event_rows,
    ))
    parts.append("</section>")

    warnings = data.get("warnings") or []
    if warnings:
        parts.append('<section class="block warnings">')
        parts.append("<h2>Warnings</h2>")
        parts.append("<ul>")
        for warning in warnings:
            parts.append(f"<li>{html.escape(str(warning))}</li>")
        parts.append("</ul>")
        parts.append("</section>")

    parts.append('<footer class="footer">')
    parts.append(f'<p>{html.escape(PAPER_DISCLAIMER)}</p>')
    parts.append("<p>No live execution occurred. Fees and slippage are simulated.</p>")
    parts.append("<p>Manual review required before mirroring in any live account.</p>")
    parts.append("</footer>")
    parts.append("</body></html>")
    return "\n".join(parts)


def _render_card(label: str, value: str) -> str:
    return (
        '<div class="card">'
        f'<div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div>'
        "</div>"
    )


def _render_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">(none)</p>'
    parts: list[str] = []
    parts.append("<table>")
    parts.append("<thead><tr>")
    for column in columns:
        parts.append(f"<th>{html.escape(column)}</th>")
    parts.append("</tr></thead>")
    parts.append("<tbody>")
    for row in rows:
        parts.append("<tr>")
        for column in columns:
            value = row.get(column)
            parts.append(f"<td>{html.escape(_format_cell(value))}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return _format_number(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{parsed:,.6f}".rstrip("0").rstrip(".")


def _format_int(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


def _format_pct(value: Any, *, already_pct: bool = False) -> str:
    if value is None:
        return "n/a"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return str(value)
    if already_pct:
        return f"{parsed:.2f}%"
    return f"{parsed * 100.0:.2f}%"


def _render_summary_markdown(data: dict[str, Any]) -> str:
    snapshot = data.get("snapshot") or {}
    performance = data.get("performance") or {}
    lines: list[str] = []
    lines.append("# Crypto Paper Dashboard Summary")
    lines.append("")
    lines.append(f"**{PAPER_DISCLAIMER}**")
    lines.append("")
    lines.append(f"- Generated at: {data.get('generated_at') or 'n/a'}")
    lines.append(f"- Equity: {_format_number(snapshot.get('equity'))}")
    lines.append(f"- Cash: {_format_number(snapshot.get('cash'))}")
    lines.append(f"- Realized P&L: {_format_number(snapshot.get('realized_pnl'))}")
    lines.append(f"- Unrealized P&L: {_format_number(snapshot.get('unrealized_pnl'))}")
    lines.append(f"- Total return: {_format_pct(performance.get('total_return_pct'), already_pct=True)}")
    lines.append(f"- Closed trades: {_format_int(performance.get('closed_trades_count'))}")
    lines.append(f"- Win rate: {_format_pct(performance.get('win_rate'))}")
    lines.append(f"- Take-profits: {_format_int(performance.get('take_profit_count'))}")
    lines.append(f"- Stop-losses: {_format_int(performance.get('stop_loss_count'))}")
    lines.append(f"- Rejected orders: {_format_int(performance.get('rejected_orders_count'))}")
    lines.append("")
    current_action = data.get("current_action")
    if current_action:
        lines.append("## Current manual action")
        lines.append(f"- Type: {current_action.get('event_type')}")
        lines.append(f"- Severity: {current_action.get('severity')}")
        if current_action.get("symbol"):
            lines.append(f"- Symbol: {current_action.get('symbol')}")
        lines.append(f"- Title: {current_action.get('human_title')}")
        lines.append(f"- Manual action: {current_action.get('manual_action')}")
        lines.append("")
    warnings = data.get("warnings") or []
    if warnings:
        lines.append("## Warnings")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")
    lines.append("## Disclaimers")
    lines.append("- Paper-only. No live execution occurred.")
    lines.append("- Fees and slippage are simulated.")
    lines.append("- Manual review required before mirroring in any live account.")
    lines.append("")
    return "\n".join(lines)


_EMBEDDED_CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 0; background: #0e1116; color: #e6edf3; }
.banner { padding: 16px 24px; background: #1f242c; border-bottom: 2px solid #2d333b; }
.banner h1 { margin: 0 0 4px 0; font-size: 22px; }
.paper-only-banner { color: #ffd33d; font-weight: 600; margin: 6px 0; }
.generated-at { color: #8b949e; font-size: 12px; margin: 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; padding: 16px 24px; }
.card { background: #161b22; border: 1px solid #2d333b; border-radius: 6px; padding: 12px; }
.card .label { font-size: 12px; color: #8b949e; text-transform: uppercase; }
.card .value { font-size: 18px; font-weight: 600; margin-top: 6px; word-break: break-all; }
.block { padding: 16px 24px; border-top: 1px solid #2d333b; }
.block h2 { font-size: 16px; margin: 0 0 12px 0; color: #58a6ff; }
.block table { width: 100%; border-collapse: collapse; font-size: 12px; }
.block th, .block td { padding: 6px 8px; border-bottom: 1px solid #2d333b; text-align: left; vertical-align: top; }
.block th { background: #1f242c; color: #8b949e; }
.empty { color: #8b949e; font-style: italic; }
.severity { display: inline-block; padding: 2px 8px; border-radius: 4px; font-weight: 600; }
.severity-info { background: #1f6feb33; color: #79c0ff; }
.severity-action { background: #d29922; color: #1c2128; }
.severity-warning { background: #d29922; color: #1c2128; }
.severity-critical { background: #da3633; color: #fff; }
.title { font-weight: 600; margin: 6px 0; }
.message { color: #c9d1d9; }
.manual-action { color: #ffa657; }
.warnings ul { margin: 0; padding-left: 20px; }
.footer { padding: 16px 24px; border-top: 1px solid #2d333b; color: #8b949e; font-size: 12px; }
.footer p { margin: 4px 0; }
"""


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
    result = build_crypto_paper_dashboard(
        artifacts_dir=args.artifacts_dir,
        dashboard_dir=args.dashboard_dir,
        rebuild_semantic=bool(args.rebuild_semantic),
    )
    sys.stdout.write(
        f"[CRYPTO-DASHBOARD] paper-only OK\n"
        f"- index_html: {result['artifacts']['index_html']}\n"
        f"- dashboard_data: {result['artifacts']['dashboard_data']}\n"
        f"- latest_summary_md: {result['artifacts']['latest_summary_md']}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
