# Crypto Paper Latest Action

**Status:** Paper-only / manual-review only. Not auto-executed.

## Snapshot
- As of: 2026-05-05T01:00:07.990613
- Equity: 100.642299
- Cash: 100.642299
- Realized P&L: 0.717299
- Unrealized P&L: 0
- Open positions: 0

## Performance
- Closed trades: 3
- Win rate: 100.00%
- Expectancy: 0.2141
- Net profit: 0.642299
- Take-profits: 3
- Stop-losses: 0

## Latest event
- Type: ORDER_REJECTED
- Severity: WARNING
- Symbol: BTCUSDT
- Title: Paper order rejected BTCUSDT
- Message: Paper order rejected for BTCUSDT reason=risk:cash_insufficient requested_notional=25 reference_price=75,611.1. Paper-only / manual-review only. Not auto-executed.
- Manual action: Inspect rejection reason. No live action required; fix configuration if reason is recurring.

## Warnings
- small_sample_size:closed_trades=3_below_min_30
- Small sample size: fewer than 30 closed trades.
- Paper-only results; no real execution occurred.
- Fees and slippage are simulated.
- provider_unhealthy:451 Client Error:  for url: https://api.binance.com/api/v3/ping
- Crypto provider unhealthy; intraday crypto engine remains in no-op mode.
- Crypto provider error for BTCUSDT: 451 Client Error:  for url: https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=120
- Crypto provider failed for all enabled symbols; engine returned no-op.
- Quote retrieval failed for BTCUSDT: 451 Client Error:  for url: https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT
- id_collision_with_diff_content:order_id=crypto-paper-order-0001
- id_collision_with_diff_content:fill_id=crypto-paper-fill-0001
- Provider unhealthy during crypto paper daily close.
- Limited symbol attribution: no realized per-symbol exit data available.

## Disclaimers
- Paper-only. No live execution occurred.
- Fees and slippage are simulated.
- Manual review required before mirroring in any live account.
