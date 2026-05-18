# Crypto Testnet Dry-Run Procedure

This procedure prepares and validates a controlled Binance Spot Testnet dry-run.

Hard rules:
- No live trading.
- No mainnet.
- No real submit from this procedure.
- Stop immediately if state is ambiguous.

## Preconditions

- Package B readiness and runbook are already in place.
- Package C operational status command is available.
- Paper artifacts are present and fresh.
- Semantic summary and dashboard are present and fresh.
- Binance Spot Testnet remains the only allowed environment.

## Required Artifacts

- `artifacts/crypto_paper/paper_forward/crypto_paper_forward_result.json`
- `artifacts/crypto_paper/semantic/crypto_semantic_summary.json`
- `artifacts/crypto_paper/dashboard/dashboard_data.json`
- `artifacts/crypto_testnet/binance_testnet_execution_result.json`
- `artifacts/crypto_testnet/binance_testnet_exchange_state.json`
- `artifacts/crypto_testnet/binance_testnet_reconciliation.json`

## Required Environment Variables

- `ENABLE_BINANCE_TESTNET_EXECUTION=1`
- `BINANCE_TESTNET_BASE_URL=https://testnet.binance.vision`
- `BINANCE_TESTNET_ALLOWED_SYMBOLS=BTCUSDT,ETHUSDT` or a stricter allowlist
- `BINANCE_TESTNET_MAX_NOTIONAL=<small test amount>`

## Required Safety Flags

- `BINANCE_TESTNET_ORDER_TEST_ONLY=1`
- `BINANCE_TESTNET_BLOCK_ON_PREVIOUS_RECONCILIATION_MISMATCH=1`
- `BINANCE_TESTNET_KILL_SWITCH=0`
- `BINANCE_TESTNET_MAX_OPEN_ORDERS=<tight cap>` when available

This dry-run command also forces `BINANCE_TESTNET_ORDER_TEST_ONLY=1` locally before it calls the executor.

## Step 1: Evaluate Readiness

```bash
PYTHONPATH=. .venv/bin/python -m src.tools.evaluate_crypto_testnet_readiness \
  --paper-artifacts-dir artifacts/crypto_paper
```

Expected:
- `status=READY` for controlled submit readiness
- or `status=NOT_READY` with `dry_run_ready=true` for dry-run-only allowance

## Step 2: Evaluate Operational Status

```bash
PYTHONPATH=. .venv/bin/python -m src.tools.evaluate_crypto_operational_status \
  --paper-artifacts-dir artifacts/crypto_paper
```

Required:
- `final_decision` must be `TESTNET_DRY_RUN_ALLOWED` or `TESTNET_SUBMIT_ALLOWED`

If it returns `DO_NOT_RUN` or `PAPER_ONLY`, stop.

## Step 3: Run the Controlled Dry-Run

```bash
PYTHONPATH=. .venv/bin/python -m src.tools.run_crypto_testnet_dry_run \
  --paper-artifacts-dir artifacts/crypto_paper
```

Behavior:
- reevaluates readiness
- reevaluates operational status
- refuses to continue unless testnet dry-run is allowed
- forces `order-test` mode locally
- calls the existing Binance Spot Testnet executor with `dry_run=true`
- does not place real testnet orders

## Expected Outputs

- `artifacts/crypto_testnet/crypto_testnet_readiness.json`
- `artifacts/crypto_ops/crypto_operational_status.json`
- `artifacts/crypto_ops/crypto_operational_status.md`
- `artifacts/crypto_testnet/crypto_testnet_dry_run_result.json`
- `artifacts/crypto_testnet/binance_testnet_execution_result.json`

## Inspect the Dry-Run Result

Check:
- `ok`
- `status`
- `operational_final_decision`
- `executor_severity`
- `blocking_reasons`
- `warnings`

The dry-run is acceptable only if:
- `ok=true`
- `status=SUCCESS`
- `submit_attempted=false`
- `live_trading_enabled=false`
- `mainnet_enabled=false`

## Stop Conditions

Stop and do not continue if any of the following is true:
- kill switch active
- readiness artifact missing or stale
- operational status is `DO_NOT_RUN`
- operational status is `PAPER_ONLY`
- reconciliation mismatch present
- dashboard or semantic heartbeat stale
- unknown run status
- exchange filter rejects indicate malformed candidate orders

## Reminder

- This is paper/testnet preparation only.
- No live trading.
- No mainnet.
- Do not continue if state is ambiguous.
