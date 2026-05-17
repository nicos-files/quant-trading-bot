# Crypto Operational Alerts

Paper and testnet only. No mainnet. No live trading.

## Severity Model

- `INFO`: informational state, no intervention needed.
- `WARNING`: degraded state, action may be required if repeated.
- `ERROR`: blocked or failed operational state requiring review.
- `CRITICAL`: hard stop / fail-closed condition.

## Event Categories

- `DATA_STALE`: stale quote or stale market data blocked a signal/exit.
- `DATA_INVALID`: malformed or invalid data payload.
- `LEDGER_CORRUPT`: corrupt paper ledger/snapshot caused fail-closed behavior.
- `LOCK_ACTIVE`: another process already holds the operational lock.
- `RISK_BLOCKED`: risk engine blocked a paper action.
- `EXCHANGE_FILTER_REJECT`: Binance Spot Testnet filter reject before submit.
- `TESTNET_KILL_SWITCH`: testnet blocked by env or kill-switch file.
- `TESTNET_RECONCILIATION_MISMATCH`: previous or current reconcile mismatch.
- `TESTNET_OPEN_ORDERS_LIMIT`: open order cap hit before submit.
- `TESTNET_INSUFFICIENT_BALANCE`: testnet account balance insufficient.
- `TESTNET_TIME_SYNC_FAILED`: clock skew or server-time gate failed.
- `TESTNET_SUBMIT_FAILED`: broker/testnet submit failed after attempt.
- `TELEGRAM_NOTIFY_FAILED`: Telegram delivery failure.
- `PAPER_ORDER_PLACED`: paper BUY executed.
- `PAPER_EXIT_PLACED`: paper exit executed.
- `NO_ACTION`: nothing actionable happened.

## Where To Inspect

- Semantic events: `artifacts/crypto_paper/semantic/crypto_semantic_events.json`
- Semantic summary: `artifacts/crypto_paper/semantic/crypto_semantic_summary.json`
- Latest semantic markdown: `artifacts/crypto_paper/semantic/crypto_latest_action.md`
- Telegram notifier result: `artifacts/crypto_paper/semantic/telegram_notify_result.json`
- Dashboard JSON: `artifacts/crypto_paper/dashboard/dashboard_data.json`
- Dashboard markdown: `artifacts/crypto_paper/dashboard/latest_summary.md`
- Daily close: `artifacts/crypto_paper/daily_close/crypto_paper_daily_report.md`
- History: `artifacts/crypto_paper/history/crypto_paper_history_report.md`
- Testnet result: `artifacts/crypto_testnet/binance_testnet_execution_result.json`
- Testnet exchange state: `artifacts/crypto_testnet/binance_testnet_exchange_state.json`

## Telegram Behavior

- `ERROR` and `CRITICAL` operational events are eligible for immediate alert.
- `WARNING` events remain visible in semantic summary and dashboard and may appear in daily summary.
- Alerts are deduplicated via `telegram_alert_state.json`.
- Every notifier run writes `telegram_notify_result.json` with status, failure reason, and heartbeat timestamps.
- Messages explicitly label `PAPER` or `TESTNET` and state that there is no live/mainnet path.

## Heartbeats

- `paper_run_id`: unique id for the latest paper-forward run.
- `paper_as_of`: latest paper snapshot timestamp.
- `paper_run_started_at`: UTC start time of the latest paper-forward run.
- `paper_run_completed_at`: UTC completion time of the latest paper-forward run.
- `semantic_run_id`: unique id for the latest semantic rebuild.
- `semantic_generated_at`: last semantic render time.
- `testnet_run_id`: unique id for the latest Binance Spot Testnet executor run.
- `testnet_last_attempt_at`: last visible Binance Spot Testnet execution attempt time.
- `telegram_run_id`: unique id for the latest notifier run.
- `telegram_last_attempt_at`: last notifier attempt time.
- `telegram_last_success_at`: last successful Telegram send time.

## Reconciliation Drift Levels

- `tolerable_drift` (`INFO`): very small local-vs-exchange quantity drift; investigate only if repeated.
- `warning` (`WARNING`): small drift worth review before trusting repeated testnet mirroring.
- `error` (`ERROR`): material drift or missing exchange balance; treat as unsafe until explained.
- `critical_hard_stop` (`CRITICAL`): hard mismatch such as a locally filled order still open on exchange.

Current policy remains fail-closed for previous persisted mismatches. Severity is now more descriptive; it does not relax the existing safety posture.

## Operator Actions

- Kill switch active:
  Disable only after confirming why testnet was halted. Do not bypass casually.
- Ledger corrupt:
  Stop trusting paper artifacts. Inspect and recover the corrupt JSON before rerun.
- Stale data:
  Check market-data freshness/provider health before trusting signal absence.
- Reconciliation mismatch:
  Inspect `binance_testnet_exchange_state.json` and `openOrders/account` drift before new submits.
- Exchange filter reject:
  Check symbol filters, notional, tick size, step size and min notional.
- Open orders cap hit:
  Review testnet working orders and clean up or raise the cap intentionally.

## Reminder

- Paper-forward results are simulated.
- Testnet may place real testnet orders only when explicitly enabled.
- No file in this workflow should enable mainnet trading.
