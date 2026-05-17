# Crypto Testnet Runbook

Paper and Binance Spot Testnet only. No live trading. No mainnet.

## Primary Inspection Points

- Latest paper-forward result:
  `artifacts/crypto_paper/paper_forward/crypto_paper_forward_result.json`
- Latest semantic summary:
  `artifacts/crypto_paper/semantic/crypto_semantic_summary.json`
- Latest dashboard health:
  `artifacts/crypto_paper/dashboard/dashboard_data.json`
- Latest notifier result:
  `artifacts/crypto_paper/semantic/telegram_notify_result.json`
- Latest testnet result:
  `artifacts/crypto_testnet/binance_testnet_execution_result.json`
- Latest testnet exchange state:
  `artifacts/crypto_testnet/binance_testnet_exchange_state.json`
- Latest testnet reconciliation rows:
  `artifacts/crypto_testnet/binance_testnet_reconciliation.json`
- Latest readiness summary:
  `artifacts/crypto_testnet/crypto_testnet_readiness.json`

## How To Inspect Latest Run Status

- Read `paper_forward.status`, `paper_forward.run_id`, and `paper_forward.heartbeat`
- Read `semantic.operational_status`
- Read `dashboard.operational_status`
- Read `testnet_result.ok`, `testnet_result.severity`, `testnet_result.category`, and `testnet_result.heartbeat`

## How To Inspect Reconciliation Status

- Read `exchange_state.reconciliation_summary`
- Read `exchange_state.mismatch_details`
- Read `exchange_state.mismatches`
- Do not proceed if mismatch count is non-zero

## How To Inspect Open Orders State

- Read `exchange_state.open_orders`
- Read `testnet_result.open_order_limit`
- If the current open-order count is unclear, stop and investigate before any new attempt

## How To Inspect Dashboard Operational Health

- Read `dashboard_data.json`
- Confirm:
  - `operational_status`
  - `paper_forward_status`
  - `telegram_status`
  - `testnet.operational_status`
  - `heartbeats`

## Response Rules

- Kill switch active:
  Stop immediately. Do not submit. Clear the kill switch only after confirming why it was enabled.
- Reconciliation mismatch:
  Stop immediately. Inspect `mismatch_details`, `open_orders`, and `balances`. Do not continue while state is ambiguous.
- Stale heartbeat:
  Treat the system as stale. Refresh paper-forward, semantic, dashboard, and readiness artifacts before continuing.
- Telegram failure:
  Restore notifier health before relying on alerts. Do not assume silent success.
- Dashboard stale:
  Rebuild the dashboard from fresh semantic/paper artifacts. Do not use stale UI state for decisions.
- Exchange filter reject:
  Inspect symbol allowlist, price tick, lot size, min notional, and max notional before retrying.
- Too many open orders:
  Stop and reconcile open orders intentionally. Do not keep submitting into an unknown working-order set.
- Unknown or failed run status:
  Treat as blocked. Do not infer safety from partial artifacts.

## Rollback / Stop Procedure

1. Set `BINANCE_TESTNET_KILL_SWITCH=1` or enable the kill-switch file.
2. Stop new testnet attempts.
3. Inspect `binance_testnet_execution_result.json` and `binance_testnet_exchange_state.json`.
4. Confirm reconciliation state and open orders.
5. Re-run readiness evaluation only after the state is understood.

## Explicit Operator Rule

Do not continue if state is ambiguous.

Ambiguous includes:

- stale heartbeat
- missing artifact
- missing reconciliation state
- unknown open orders
- notifier failure
- blocked or failed testnet status
- any unexplained mismatch
