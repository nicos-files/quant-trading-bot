# Crypto Testnet Readiness Checklist

Paper and Binance Spot Testnet only. No live trading. No mainnet.

## Required Environment Variables

- `ENABLE_BINANCE_TESTNET_EXECUTION=1`
- `BINANCE_TESTNET_BASE_URL=https://testnet.binance.vision`
- `BINANCE_TESTNET_ORDER_TEST_ONLY=1` for dry-run/order-test validation
- `BINANCE_TESTNET_ALLOWED_SYMBOLS=BTCUSDT,ETHUSDT` or a stricter allowlist
- `BINANCE_TESTNET_MAX_NOTIONAL=25` or lower unless intentionally reviewed
- `BINANCE_TESTNET_API_KEY` and `BINANCE_TESTNET_API_SECRET` only for controlled testnet use

## Required Safety Environment Variables

- `BINANCE_TESTNET_BLOCK_ON_PREVIOUS_RECONCILIATION_MISMATCH=1`
- `BINANCE_TESTNET_MAX_OPEN_ORDERS` set to an explicit cap
- `CRYPTO_LOCAL_TZ=America/Argentina/Buenos_Aires` if local display must stay aligned

## Kill Switch Requirements

- `BINANCE_TESTNET_KILL_SWITCH` must remain available as an emergency hard stop
- `artifacts/crypto_testnet/binance_testnet_kill_switch.json` must be recognized as an emergency stop file
- Do not disable or bypass kill switches casually

## Required Artifact Paths

- `artifacts/crypto_paper/paper_forward/crypto_paper_forward_result.json`
- `artifacts/crypto_paper/semantic/crypto_semantic_summary.json`
- `artifacts/crypto_paper/dashboard/dashboard_data.json`
- `artifacts/crypto_paper/semantic/telegram_notify_result.json`
- `artifacts/crypto_testnet/binance_testnet_execution_result.json`
- `artifacts/crypto_testnet/binance_testnet_exchange_state.json`
- `artifacts/crypto_testnet/binance_testnet_reconciliation.json`
- `artifacts/crypto_testnet/crypto_testnet_readiness.json`

## Pre-Run Checks

- Confirm the latest paper-forward run finished `SUCCESS`
- Confirm semantic operational status is not `ERROR` or `BLOCKED`
- Confirm dashboard is fresh and not stale
- Confirm no stale-data operational events are active
- Confirm Telegram notifier is not failing closed
- Confirm the latest testnet result points to a testnet base URL only
- Confirm reconciliation mismatch count is zero
- Confirm kill switch file is not active unless intentionally stopping execution
- Confirm open-orders state is understood before any new attempt

## Dry-Run Checks

- Run readiness evaluation first
- Run testnet executor in dry-run or `order/test` mode only
- Verify `crypto_testnet_readiness.json` reports `dry_run_ready=true`
- Verify `binance_testnet_execution_result.json` remains `ok=true`
- Verify `exchange_state.reconciliation_summary.count == 0`
- Verify dashboard operational health remains understandable and current

## Allowed Modes

- `paper-forward` only
- `Binance Spot Testnet` with `BINANCE_TESTNET_ORDER_TEST_ONLY=1`
- Controlled Binance Spot Testnet submit only after checklist and readiness pass

## Forbidden Modes

- Binance mainnet
- Futures, margin, withdraw, or any non-spot endpoint
- Live trading with real money
- Ambiguous state continuation after stale heartbeat, mismatch, or blocked status

## Acceptance Criteria Before First Controlled Testnet Submit

- Latest paper-forward result is `SUCCESS`
- Latest semantic summary has no `ERROR` or `CRITICAL` operational counts
- Latest dashboard is fresh
- Latest Telegram notifier result is not `ERROR` or `CRITICAL`
- Latest testnet execution result is `ok=true`
- Latest testnet heartbeat is fresh
- Latest exchange reconciliation reports zero mismatches
- Latest readiness summary reports:
  - `dry_run_ready=true`
  - `submit_ready=true`
  - `status=READY`
- Operator explicitly confirms `BINANCE_TESTNET_ORDER_TEST_ONLY=0` only for the controlled window

## Explicit Reminders

- No live trading
- No mainnet
- No secrets in artifacts
- Do not continue when state is ambiguous
