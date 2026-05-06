import json
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools.build_crypto_paper_dashboard import build_crypto_paper_dashboard, main


class BuildCryptoPaperDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.dashboard_dir = self.artifacts_dir / "dashboard"
        self.now = datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed_minimal_artifacts(self) -> None:
        snapshot = {
            "as_of": "2026-05-03T17:45:00",
            "equity": 100.642299,
            "cash": 100.642299,
            "positions_value": 0.0,
            "realized_pnl": 0.717299,
            "unrealized_pnl": 0.0,
            "fees_paid": 0.150793,
            "positions": [],
        }
        metrics = {
            "closed_trades_count": 3,
            "open_trades_count": 0,
            "win_rate": 1.0,
            "expectancy": 0.214,
            "profit_factor": None,
            "net_profit": 0.642299,
            "total_fees": 0.150793,
            "total_slippage": 0.075,
            "stop_loss_count": 0,
            "take_profit_count": 3,
            "warnings": ["Small sample size: fewer than 30 closed trades."],
        }
        equity_curve = [{"equity": 100.0, "as_of": "2026-04-28T13:56:54"}]
        fills = [
            {
                "fill_id": "crypto-paper-fill-20260428T150008-0001",
                "order_id": "crypto-paper-order-20260428T150008-0001",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "quantity": 0.000328,
                "fill_price": 76026.5,
                "gross_notional": 25.0,
                "fee": 0.025,
                "filled_at": "2026-04-28T15:00:08",
                "metadata": {"stop_loss": 74468.7, "take_profit": 76748.4},
            }
        ]
        exits = [
            {
                "exit_id": "crypto-exit-BTCUSDT-20260503T174500-0001",
                "symbol": "BTCUSDT",
                "exit_reason": "TAKE_PROFIT",
                "exit_quantity": 0.001,
                "trigger_price": 77131.478,
                "fill_price": 77092.91,
                "realized_pnl": 0.717,
                "fee": 0.075,
                "exited_at": "2026-05-03T17:45:00",
                "source": "stop_take_quote_fallback",
                "metadata": {"stop_loss": 74840.0, "take_profit": 77131.478},
            }
        ]
        orders = [
            {
                "order_id": "crypto-paper-order-20260430T230009-0001",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "status": "REJECTED",
                "reason": "risk:cash_insufficient",
                "reference_price": 76323.24,
                "requested_notional": 25.0,
                "created_at": "2026-04-30T23:00:09",
                "metadata": {},
            }
        ]
        (self.artifacts_dir / "crypto_paper_snapshot.json").write_text(
            json.dumps(snapshot), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_positions.json").write_text("[]", encoding="utf-8")
        (self.artifacts_dir / "crypto_paper_fills.json").write_text(
            json.dumps(fills), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_orders.json").write_text(
            json.dumps(orders), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_exit_events.json").write_text(
            json.dumps(exits), encoding="utf-8"
        )
        (self.artifacts_dir / "evaluation" / "crypto_paper_strategy_metrics.json").write_text(
            json.dumps(metrics), encoding="utf-8"
        )
        (self.artifacts_dir / "history" / "crypto_paper_equity_curve.json").write_text(
            json.dumps(equity_curve), encoding="utf-8"
        )

    def test_dashboard_writes_index_html(self) -> None:
        self._seed_minimal_artifacts()
        result = build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        index_path = self.dashboard_dir / "index.html"
        self.assertTrue(index_path.exists())
        content = index_path.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("<!DOCTYPE html>"))
        self.assertIn("Crypto Paper Dashboard", content)
        self.assertEqual(result["artifacts"]["index_html"], str(index_path))

    def test_dashboard_writes_dashboard_data_json(self) -> None:
        self._seed_minimal_artifacts()
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        data_path = self.dashboard_dir / "dashboard_data.json"
        self.assertTrue(data_path.exists())
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["paper_only"], True)
        self.assertEqual(payload["live_trading"], False)
        self.assertIn("snapshot", payload)
        self.assertIn("performance", payload)
        self.assertIn("recent_events", payload)

    def test_dashboard_writes_latest_summary_markdown(self) -> None:
        self._seed_minimal_artifacts()
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        summary_path = self.dashboard_dir / "latest_summary.md"
        self.assertTrue(summary_path.exists())
        content = summary_path.read_text(encoding="utf-8")
        self.assertIn("# Crypto Paper Dashboard Summary", content)
        self.assertIn("Paper-only", content)

    def test_dashboard_contains_equity_pnl_and_trade_metrics(self) -> None:
        self._seed_minimal_artifacts()
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        content = (self.dashboard_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("Equity", content)
        self.assertIn("Realized P&amp;L", content)
        self.assertIn("Unrealized P&amp;L", content)
        self.assertIn("Closed trades", content)
        self.assertIn("Win rate", content)
        self.assertIn("Expectancy", content)
        self.assertIn("Take-profits", content)
        self.assertIn("Stop-losses", content)
        self.assertIn("Rejected orders", content)
        self.assertIn("Total fees", content)
        self.assertIn("Total slippage", content)
        self.assertIn("BTCUSDT", content)
        self.assertIn("TAKE_PROFIT", content)
        self.assertIn("Small sample size", content)

    def test_dashboard_includes_paper_only_disclaimer(self) -> None:
        self._seed_minimal_artifacts()
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        content = (self.dashboard_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("Paper-only", content)
        self.assertIn("manual-review", content)
        self.assertNotIn("live trading", content.lower().replace("no live trading", ""))

    def test_dashboard_does_not_require_network(self) -> None:
        # Block all socket activity during dashboard build.
        self._seed_minimal_artifacts()

        original_socket = socket.socket

        def _no_network(*args, **kwargs):  # noqa: ANN001
            raise AssertionError("dashboard build must not perform network IO")

        with patch("socket.socket", _no_network):
            try:
                build_crypto_paper_dashboard(
                    artifacts_dir=self.artifacts_dir,
                    dashboard_dir=self.dashboard_dir,
                    now=self.now,
                )
            finally:
                # Defensive: restore even if patch contextmanager already does it.
                socket.socket = original_socket

    def test_dashboard_handles_empty_artifacts_directory_gracefully(self) -> None:
        result = build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertTrue((self.dashboard_dir / "index.html").exists())
        payload = json.loads((self.dashboard_dir / "dashboard_data.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["snapshot"]["open_positions_count"], 0)

    def test_dashboard_does_not_reference_external_cdn(self) -> None:
        self._seed_minimal_artifacts()
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        content = (self.dashboard_dir / "index.html").read_text(encoding="utf-8").lower()
        for forbidden in ("https://", "http://", "cdn.", "<script", "src="):
            self.assertNotIn(
                forbidden,
                content,
                f"dashboard html must not reference external resources: found {forbidden!r}",
            )

    def test_main_cli_returns_zero_and_writes_files(self) -> None:
        self._seed_minimal_artifacts()
        rc = main([
            "--artifacts-dir", str(self.artifacts_dir),
            "--dashboard-dir", str(self.dashboard_dir),
        ])
        self.assertEqual(rc, 0)
        self.assertTrue((self.dashboard_dir / "index.html").exists())


class BuildCryptoPaperDashboardSignalOnlyTests(unittest.TestCase):
    """Dashboard surfaces SIGNAL_ONLY count and recent SIGNAL_ONLY events."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.dashboard_dir = self.artifacts_dir / "dashboard"
        self.now = datetime(2026, 5, 5, 23, 30, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed_with_signal_only(self) -> None:
        order = {
            "order_id": "crypto-paper-order-20260505T123007-0001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "status": "REJECTED",
            "reason": "risk:cash_insufficient",
            "reference_price": 81482.11,
            "requested_notional": 25.0,
            "created_at": "2026-05-05T12:30:07",
            "metadata": {"stop_loss": 79812.56, "take_profit": 82255.80},
        }
        snapshot = {
            "as_of": "2026-05-05T23:30:00",
            "equity": 100.0,
            "cash": 100.0,
            "positions_value": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "fees_paid": 0.0,
            "positions": [],
        }
        (self.artifacts_dir / "crypto_paper_orders.json").write_text(
            json.dumps([order]), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_fills.json").write_text("[]", encoding="utf-8")
        (self.artifacts_dir / "crypto_paper_snapshot.json").write_text(
            json.dumps(snapshot), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_positions.json").write_text("[]", encoding="utf-8")
        (self.artifacts_dir / "crypto_paper_exit_events.json").write_text("[]", encoding="utf-8")
        (self.artifacts_dir / "paper_forward" / "crypto_paper_forward_result.json").write_text(
            json.dumps(
                {
                    "recommendations_count": 1,
                    "fills_count": 0,
                    "exits_count": 0,
                    "status": "SUCCESS",
                }
            ),
            encoding="utf-8",
        )

    def test_dashboard_data_includes_signal_only_count_and_recent(self) -> None:
        self._seed_with_signal_only()
        result = build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            rebuild_semantic=True,
            now=self.now,
        )
        data = result["data"]
        self.assertEqual(data["performance"]["signal_only_count"], 1)
        recent = data["recent_signal_only_events"]
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["symbol"], "BTCUSDT")
        self.assertEqual(
            (recent[0].get("metadata") or {}).get("rejection_reason"),
            "risk:cash_insufficient",
        )

    def test_dashboard_html_renders_signal_only_card_and_section(self) -> None:
        self._seed_with_signal_only()
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            rebuild_semantic=True,
            now=self.now,
        )
        content = (self.dashboard_dir / "index.html").read_text(encoding="utf-8")
        # Card and section are present.
        self.assertIn("Signal-only", content)
        self.assertIn("Recent SIGNAL_ONLY events", content)
        # The seeded SIGNAL_ONLY symbol appears in the recent table.
        self.assertIn("BTCUSDT", content)
        # Markdown summary also includes the Signal-only line.
        md_content = (self.dashboard_dir / "latest_summary.md").read_text(encoding="utf-8")
        self.assertIn("Signal-only", md_content)


if __name__ == "__main__":
    unittest.main()
