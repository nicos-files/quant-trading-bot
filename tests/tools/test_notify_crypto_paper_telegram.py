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

from src.notifications.telegram_notifier import (
    DEFAULT_BOT_TOKEN_ENV,
    DEFAULT_CHAT_ID_ENV,
    TelegramSendError,
)
from src.tools.notify_crypto_paper_telegram import (
    ENABLE_FLAG,
    format_event_message,
    notify_crypto_paper_telegram,
)


BOT_TOKEN = "1234567890:AAAA-secret-token-must-not-leak"
CHAT_ID = "987654321"


def _enabled_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        ENABLE_FLAG: "1",
        DEFAULT_BOT_TOKEN_ENV: BOT_TOKEN,
        DEFAULT_CHAT_ID_ENV: CHAT_ID,
    }
    if extra:
        env.update(extra)
    return env


class _RecordingSender:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, *, bot_token, chat_id, text):
        self.calls.append({"bot_token": bot_token, "chat_id": chat_id, "text": text})
        return {"ok": True}


class NotifyCryptoPaperTelegramTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.now = datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, relative: str, payload) -> None:
        path = self.artifacts_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _seed_take_profit_exit(self) -> None:
        exit_event = {
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
        self._write("crypto_paper_exit_events.json", [exit_event])
        self._write("crypto_paper_snapshot.json", {"equity": 100.64, "positions": []})
        self._write("crypto_paper_positions.json", [])

    def test_refuses_to_send_without_enable_flag(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env={DEFAULT_BOT_TOKEN_ENV: BOT_TOKEN, DEFAULT_CHAT_ID_ENV: CHAT_ID},
            sender=sender,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], f"{ENABLE_FLAG}_not_enabled")
        self.assertEqual(sender.calls, [])

    def test_dry_run_does_not_call_network(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()

        def _no_network(*args, **kwargs):  # noqa: ANN001
            raise AssertionError("dry-run must not perform network IO")

        with patch("socket.socket", _no_network):
            result = notify_crypto_paper_telegram(
                artifacts_dir=self.artifacts_dir,
                env=_enabled_env(),
                sender=sender,
                dry_run=True,
                now=self.now,
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(sender.calls, [])
        self.assertEqual(len(result["messages"]), 1)
        self.assertIn("TAKE_PROFIT", result["messages"][0])

    def test_missing_token_or_chat_fails_cleanly(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env={ENABLE_FLAG: "1"},
            sender=sender,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertIn(DEFAULT_BOT_TOKEN_ENV, result["reason"])
        self.assertEqual(sender.calls, [])

    def test_token_is_not_logged_or_returned(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        encoded = json.dumps({k: v for k, v in result.items() if k != "messages"})
        self.assertNotIn(BOT_TOKEN, encoded)
        # The masked chat_id is allowed; the raw chat_id still must not appear in messages.
        for message in result["messages"]:
            self.assertNotIn(BOT_TOKEN, message)

    def test_sends_only_alertable_events(self) -> None:
        self._seed_take_profit_exit()
        # Add a BUY_SIGNAL via an order; not alertable by default.
        self._write(
            "crypto_paper_orders.json",
            [
                {
                    "order_id": "crypto-paper-order-20260428T150008-0001",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "status": "PENDING",
                    "reason": None,
                    "reference_price": 76000.0,
                    "requested_notional": 25.0,
                    "created_at": "2026-04-28T15:00:08",
                    "metadata": {},
                }
            ],
        )
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(sender.calls), 1)
        self.assertIn("TAKE_PROFIT", sender.calls[0]["text"])
        for call in sender.calls:
            self.assertNotIn("BUY_SIGNAL", call["text"])

    def test_no_action_is_not_sent_by_default(self) -> None:
        # No artifacts seeded -> only NO_ACTION + WARNING events emitted by semantic layer.
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        for call in sender.calls:
            self.assertNotIn("NO_ACTION", call["text"])

    def test_dedupe_prevents_duplicate_sends(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()
        first = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        second = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertEqual(len(first["sent"]), 1)
        self.assertEqual(len(second["sent"]), 0)
        self.assertEqual(len(second["skipped"]), 1)
        self.assertEqual(second["skipped"][0]["reason"], "already_sent")
        # Sender called exactly once across both runs.
        self.assertEqual(len(sender.calls), 1)

    def test_force_resends_already_sent_events(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()
        notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertEqual(len(sender.calls), 1)
        forced = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            force=True,
            now=self.now,
        )
        self.assertEqual(len(forced["sent"]), 1)
        self.assertEqual(len(sender.calls), 2)

    def test_dry_run_does_not_persist_dedupe_state(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            dry_run=True,
            now=self.now,
        )
        state_path = Path(result["state_path"])
        self.assertFalse(state_path.exists())
        # Subsequent non-dry-run must therefore actually send.
        sent = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertEqual(len(sent["sent"]), 1)

    def test_min_severity_filters_below_threshold(self) -> None:
        self._seed_take_profit_exit()
        # Add a rejected order (WARNING severity, alertable). With min_severity=ACTION,
        # it must be filtered out.
        self._write(
            "crypto_paper_orders.json",
            [
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
            ],
        )
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            min_severity="CRITICAL",
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(sender.calls, [])

    def test_daily_summary_sends_one_summary_message(self) -> None:
        self._seed_take_profit_exit()
        self._write(
            "evaluation/crypto_paper_strategy_metrics.json",
            {
                "closed_trades_count": 3,
                "open_trades_count": 0,
                "win_rate": 1.0,
                "take_profit_count": 3,
                "stop_loss_count": 0,
                "warnings": [],
            },
        )
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            daily_summary=True,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        # 1 take-profit alert + 1 daily summary
        self.assertEqual(len(sender.calls), 2)
        summary_text = sender.calls[-1]["text"]
        self.assertIn("DAILY_SUMMARY", summary_text)
        self.assertIn("Paper-only", summary_text)

    def test_send_failure_is_token_redacted(self) -> None:
        self._seed_take_profit_exit()

        def failing_sender(*, bot_token, chat_id, text):  # noqa: ANN001
            raise TelegramSendError(f"boom token={bot_token}")

        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=failing_sender,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertNotIn(BOT_TOKEN, result["reason"])

    def test_format_event_message_includes_disclaimer(self) -> None:
        event = {
            "event_id": "x",
            "event_type": "TAKE_PROFIT",
            "severity": "ACTION",
            "symbol": "BTCUSDT",
            "human_title": "Paper TAKE-PROFIT exit: BTCUSDT",
            "human_message": "...",
            "manual_action": "Review.",
            "metadata": {
                "trigger_price": 77131.478,
                "fill_price": 77092.91,
                "realized_pnl": 0.717,
                "stop_loss": 74840.0,
                "take_profit": 77131.478,
            },
        }
        text = format_event_message(event)
        self.assertIn("[ACTION] TAKE_PROFIT BTCUSDT", text)
        self.assertIn("trigger=", text)
        self.assertIn("realized_pnl=", text)
        self.assertIn("Action: Review.", text)
        self.assertIn("Paper-only", text)

    def test_uses_mocked_http_only(self) -> None:
        # End-to-end network safety: block sockets and rely on injected sender.
        self._seed_take_profit_exit()
        sender = _RecordingSender()

        def _no_network(*args, **kwargs):  # noqa: ANN001
            raise AssertionError("notifier must not open a real socket in tests")

        with patch("socket.socket", _no_network):
            result = notify_crypto_paper_telegram(
                artifacts_dir=self.artifacts_dir,
                env=_enabled_env(),
                sender=sender,
                now=self.now,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(len(sender.calls), 1)


if __name__ == "__main__":
    unittest.main()
