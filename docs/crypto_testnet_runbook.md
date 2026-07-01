# Crypto Testnet Runbook

Paper and Binance Spot Testnet only. No live trading. No mainnet.

## Current State

The repository is currently ready for controlled Binance Spot Testnet operation.

Confirmed state:
- `readiness.status = READY`
- `operational.final_decision = TESTNET_SUBMIT_ALLOWED`
- `blocking_reasons = []`
- Binance Spot Testnet connected and validated
- controlled smoke submit path validated
- post-submit reconciliation validated using exchange deltas
- no live trading and no mainnet support enabled

This is a controlled testnet package, not a live-trading package.

## What READY Means

`READY` means the current paper, semantic, dashboard, testnet, and reconciliation artifacts are internally consistent enough to permit controlled testnet activity.

It does not mean:
- strategy edge is proven
- live execution is allowed
- mainnet is allowed
- the system is production-ready for real money

## What TESTNET_SUBMIT_ALLOWED Means

`TESTNET_SUBMIT_ALLOWED` means the operational aggregator sees no current hard blockers for a controlled Binance Spot Testnet submit.

It still requires operator discipline:
- `BINANCE_TESTNET_ORDER_TEST_ONLY=0` only for the exact submit window
- `BINANCE_TESTNET_CONFIRM_SUBMIT=YES` only inline on the exact smoke submit command
- post-submit reconciliation is mandatory
- immediately return to `BINANCE_TESTNET_ORDER_TEST_ONLY=1` after the submit

## Why This Is Not Live-Ready

The system is still not approved for live or mainnet use because:
- strategy research remains small-sample and paper-biased
- fees and slippage are still simulated on the paper side
- paper and testnet observability are strong, but live execution controls are intentionally absent
- operational procedures are for controlled testnet only
- a successful testnet submit validates plumbing, not profitability or live robustness

## Required Environment Variables

Required for connected Binance Spot Testnet preflight:

```bash
ENABLE_BINANCE_TESTNET_EXECUTION=1
BINANCE_TESTNET_BASE_URL=https://testnet.binance.vision
BINANCE_TESTNET_ALLOWED_SYMBOLS=BTCUSDT
BINANCE_TESTNET_MAX_OPEN_ORDERS=1
BINANCE_TESTNET_MAX_NOTIONAL=25
BINANCE_TESTNET_ORDER_TEST_ONLY=1
BINANCE_TESTNET_API_KEY=REDACTED
BINANCE_TESTNET_API_SECRET=REDACTED
```

Optional but safety-relevant:

```bash
BINANCE_TESTNET_KILL_SWITCH=0
BINANCE_TESTNET_KILL_SWITCH_PATH=/path/to/optional/kill_switch.json
BINANCE_TESTNET_BLOCK_ON_PREVIOUS_RECONCILIATION_MISMATCH=1
```

Critical rule:
- Never export `BINANCE_TESTNET_CONFIRM_SUBMIT=YES` globally.
- Use it only inline on the exact smoke submit command.
- Unset it immediately after the smoke submit command finishes.

## Safe Normal Flow

### A. Connected preflight in order-test mode

```bash
timeout 120s env \
  PYTHONPATH=. \
  ENABLE_BINANCE_TESTNET_EXECUTION=1 \
  BINANCE_TESTNET_ORDER_TEST_ONLY=1 \
  BINANCE_TESTNET_BASE_URL=https://testnet.binance.vision \
  BINANCE_TESTNET_ALLOWED_SYMBOLS=BTCUSDT \
  BINANCE_TESTNET_MAX_OPEN_ORDERS=1 \
  BINANCE_TESTNET_MAX_NOTIONAL=25 \
  .venv/bin/python -m src.tools.run_binance_testnet_execution \
  --paper-artifacts-dir artifacts/crypto_paper \
  --testnet-artifacts-dir artifacts/crypto_testnet \
  --rebuild-semantic
```

### B. Readiness evaluation

```bash
PYTHONPATH=. .venv/bin/python -m src.tools.evaluate_crypto_testnet_readiness \
  --paper-artifacts-dir artifacts/crypto_paper \
  --testnet-artifacts-dir artifacts/crypto_testnet
```

### C. Operational status evaluation

```bash
PYTHONPATH=. .venv/bin/python -m src.tools.evaluate_crypto_operational_status \
  --paper-artifacts-dir artifacts/crypto_paper \
  --testnet-artifacts-dir artifacts/crypto_testnet
```

### D. Dry-run only

```bash
PYTHONPATH=. .venv/bin/python -m src.tools.run_crypto_testnet_dry_run \
  --paper-artifacts-dir artifacts/crypto_pape
```

### E. Smoke submit only with explicit confirmation

Do this only if `readiness.status = READY` and `final_decision = TESTNET_SUBMIT_ALLOWED` immediately before the command.

```bash
timeout 120s env \
  PYTHONPATH=. \
  ENABLE_BINANCE_TESTNET_EXECUTION=1 \
  BINANCE_TESTNET_BASE_URL=https://testnet.binance.vision \
  BINANCE_TESTNET_ALLOWED_SYMBOLS=BTCUSDT \
  BINANCE_TESTNET_MAX_OPEN_ORDERS=1 \
  BINANCE_TESTNET_MAX_NOTIONAL=25 \
  BINANCE_TESTNET_ORDER_TEST_ONLY=0 \
  BINANCE_TESTNET_CONFIRM_SUBMIT=YES \
  .venv/bin/python -m src.tools.run_binance_testnet_smoke_submit \
  --paper-artifacts-dir artifacts/crypto_paper \
  --testnet-artifacts-dir artifacts/crypto_testnet
```

### F. Post-submit reconciliation

```bash
PYTHONPATH=. .venv/bin/python -m src.tools.evaluate_crypto_testnet_readiness \
  --paper-artifacts-dir artifacts/crypto_paper \
  --testnet-artifacts-dir artifacts/crypto_testnet

PYTHONPATH=. .venv/bin/python -m src.tools.evaluate_crypto_operational_status \
  --paper-artifacts-dir artifacts/crypto_paper \
  --testnet-artifacts-dir artifacts/crypto_testnet
```

### G. Return immediately to safe mode

```bash
export BINANCE_TESTNET_ORDER_TEST_ONLY=1
unset BINANCE_TESTNET_CONFIRM_SUBMIT
```

## Safe Inspection Commands

```bash
python3 - <<'PY'
import json, pathlib
for path in [
    "artifacts/crypto_paper/semantic/crypto_semantic_summary.json",
    "artifacts/crypto_paper/dashboard/dashboard_data.json",
    "artifacts/crypto_testnet/binance_testnet_execution_result.json",
    "artifacts/crypto_testnet/binance_testnet_exchange_state.json",
    "artifacts/crypto_testnet/crypto_testnet_readiness.json",
    "artifacts/crypto_ops/crypto_operational_status.json",
]:
    print(f"\n== {path} ==")
    p = pathlib.Path(path)
    if not p.exists():
        print("MISSING")
        continue
    print(p.read_text(encoding="utf-8")[:4000])
PY
```

## Benign Warnings That Do Not Block By Themselves

These remain visible and should be reviewed, but do not by themselves block controlled testnet:
- `Risk rejected BTCUSDT: symbol_position_exists`
- `Crypto strategy produced no trade candidates.`
- `small_sample_size:closed_trades=...`
- `Small sample size: fewer than 30 closed trades.`
- `Paper-only results; no real execution occurred.`
- `Fees and slippage are simulated.`
- `Limited symbol attribution: no realized per-symbol exit data available.`
- `ignored_historical_paper_semantic_events:...`

These warnings indicate research or reporting limitations, not a broken testnet execution path.

## Warnings And Events That Must Block

Any of the following must block further testnet activity until understood:
- exchange filter reject
- reconciliation mismatch
- stale heartbeat
- wrong base URL
- kill switch active
- missing or unreadable artifacts
- semantic `ERROR` or `CRITICAL`
- unexpected open orders
- corrupt ledger or artifact corruption
- ambiguous or partial state

## Explicit Operator Rule

Do not continue if state is ambiguous.

## Stop Conditions

Stop immediately and do not continue if any of these is true:
- `readiness.status != READY`
- `submit_ready != true`
- `final_decision != TESTNET_SUBMIT_ALLOWED` for a real smoke submit
- `blocking_reasons` is not empty
- `reconciliation_summary.count > 0`
- base URL is not `https://testnet.binance.vision`
- kill switch is active
- open-order count is unknown or non-zero unexpectedly
- state is stale, partial, or ambiguous

## Recovery Procedure

If anything looks wrong:

1. Return to safe mode immediately.

```bash
export BINANCE_TESTNET_ORDER_TEST_ONLY=1
unset BINANCE_TESTNET_CONFIRM_SUBMIT
```

2. Do not repeat the submit.
3. Re-evaluate readiness and operational status.
4. Inspect exchange state, reconciliation, and semantic artifacts.
5. Do not retry until the cause is understood and the system is back to `READY` plus `TESTNET_SUBMIT_ALLOWED`.

## Checklist Before Any Future Smoke Submit

- `git status --short` reviewed
- no artifacts staged for commit
- base URL is Binance Spot Testnet
- `ENABLE_BINANCE_TESTNET_EXECUTION=1`
- `BINANCE_TESTNET_ORDER_TEST_ONLY=1` in the resting state
- `BINANCE_TESTNET_ALLOWED_SYMBOLS=BTCUSDT`
- `BINANCE_TESTNET_MAX_OPEN_ORDERS=1`
- `BINANCE_TESTNET_MAX_NOTIONAL<=25`
- kill switch not active
- readiness is `READY`
- operational status is `TESTNET_SUBMIT_ALLOWED`
- no unexplained warnings or blockers
- `BINANCE_TESTNET_CONFIRM_SUBMIT=YES` prepared only inline for the exact command

## Checklist After Any Smoke Submit

- return to `BINANCE_TESTNET_ORDER_TEST_ONLY=1`
- unset `BINANCE_TESTNET_CONFIRM_SUBMIT`
- inspect smoke submit result artifact
- inspect exchange state artifact
- inspect readiness artifact
- inspect operational status artifact
- confirm reconciliation count is zero
- confirm no unexpected open orders
- stop if anything is ambiguous

## Testnet Closure Criteria

This controlled testnet package can be considered operationally closed when:
- connected preflight is reproducible
- readiness and operational status are reproducible
- dry-run path is reproducible
- smoke submit path is reproducible
- post-submit reconciliation stays clean
- operators follow inline confirmation discipline
- no one interprets testnet success as live readiness

The package remains testnet-only until a separate live-readiness program is defined and approved.
## Mainnet Read-Only And Live Readiness

Mainnet read-only preflight does not enable live trading.

Important rules:
- mainnet read-only OK does not mean live submit is allowed
- live readiness does not execute orders
- prepare-only does not execute orders
- the read-only API key must never be converted into a trading key by reuse
- `BINANCE_LIVE_CONFIRM_SUBMIT=YES` must never be exported globally in the shell profile or session bootstrap
- `BINANCE_LIVE_CONFIRM_SUBMIT=YES` is future-use only and must be supplied inline only for a separate, explicitly approved live-submit package
- future live trading requires a separate API key with Spot Trading enabled, withdrawals disabled, and IP whitelist enabled
- the first live micro-submit is a separate package and is not implemented here

Safe commands:

```bash
PYTHONPATH=. .venv/bin/python -m src.tools.run_binance_mainnet_readonly_preflight

PYTHONPATH=. .venv/bin/python -m src.tools.evaluate_binance_live_readiness \
  --artifacts-dir artifacts/crypto_mainnet

PYTHONPATH=. .venv/bin/python -m src.tools.run_binance_live_micro_submit \
  --artifacts-dir artifacts/crypto_mainnet \
  --prepare-only
```

Live remains blocked in this package even when readiness is healthy.
## Future Live Micro-Submit Path

This path is implemented but must not be executed casually.

Rules:
- never export `BINANCE_LIVE_CONFIRM_SUBMIT=YES` globally
- use separate live API credentials, never the readonly key
- require a fresh successful mainnet readonly preflight
- require `binance_live_readiness.json` in `READY_FOR_PREPARE_ONLY`
- require `BINANCE_LIVE_KILL_SWITCH=0`
- require `BINANCE_LIVE_ALLOWED_SYMBOLS=BTCUSDT`
- require `BINANCE_LIVE_MAX_NOTIONAL<=5`
- require `BINANCE_LIVE_MAX_DAILY_ORDERS=1`
- require `BINANCE_LIVE_MAX_OPEN_ORDERS=1`
- stop if `live_min_notional_exceeds_configured_cap` appears

Prepared command only. Do not run automatically from documentation:

```bash
timeout 120s env \
  PYTHONPATH=. \
  BINANCE_LIVE_TRADING_ENABLED=1 \
  BINANCE_LIVE_CONFIRM_SUBMIT=YES \
  BINANCE_LIVE_KILL_SWITCH=0 \
  BINANCE_LIVE_BASE_URL=https://api.binance.com \
  BINANCE_LIVE_ALLOWED_SYMBOLS=BTCUSDT \
  BINANCE_LIVE_MAX_NOTIONAL=5 \
  BINANCE_LIVE_MAX_DAILY_ORDERS=1 \
  BINANCE_LIVE_MAX_OPEN_ORDERS=1 \
  BINANCE_LIVE_API_KEY=REDACTED \
  BINANCE_LIVE_API_SECRET=REDACTED \
  .venv/bin/python -m src.tools.run_binance_live_micro_submit \
  --artifacts-dir artifacts/crypto_mainnet \
  --execute
```

Immediate post-submit checks:

```bash
PYTHONPATH=. .venv/bin/python -m src.tools.run_binance_mainnet_readonly_preflight

PYTHONPATH=. .venv/bin/python -m src.tools.evaluate_binance_live_readiness \
  --artifacts-dir artifacts/crypto_mainnet

python3 - <<'"'"'PY'"'"'
import json, pathlib
for path in [
    "artifacts/crypto_mainnet/binance_mainnet_readonly_preflight.json",
    "artifacts/crypto_mainnet/binance_live_readiness.json",
    "artifacts/crypto_mainnet/binance_live_micro_submit_result.json",
]:
    print(f"\n== {path} ==")
    p = pathlib.Path(path)
    if not p.exists():
        print("MISSING")
        continue
    print(p.read_text(encoding="utf-8")[:4000])
PY
```

Stop immediately if any of these appears:
- wrong base URL
- kill switch active
- stale or missing readonly artifact
- readonly/readiness blocking reasons
- open orders present before submit
- open orders present after submit
- missing fill
- delta reconciliation mismatch
- daily cap already consumed
- min notional exceeds configured cap
- any ambiguous or partial state
