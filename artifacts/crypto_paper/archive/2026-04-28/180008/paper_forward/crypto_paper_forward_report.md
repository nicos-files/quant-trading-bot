# Crypto Paper-Forward Daily Report

## Executive Summary
- Run status: SUCCESS
- Paper-only status: True
- Candidate config used: artifacts/crypto_paper/config_promotions/crypto_baseline_grid_v1/crypto_config_candidate.json
- Symbols evaluated: BTCUSDT, ETHUSDT
- Recommendations count: 0
- Fills count: 0
- Exits count: 0
- Realized P&L: 0.000000
- Unrealized P&L: 0.030409
- Total equity: 100.005409
- Warnings: 10

## Signals
- No signals.

## Paper Execution
- Orders: 0
- Fills: 0
- Rejected orders: 0
- Fees: 0.025000
- Slippage: 0.000000

## Exits
- STOP_LOSS / TAKE_PROFIT events: 0
- Realized P&L: 0.000000

## Portfolio
- Cash: 74.975000
- Positions: 1
- Equity: 100.005409
- P&L: 0.030409

## Strategy Evaluation
- Closed trades: 0
- Open trades: 1
- Win rate: None
- Expectancy: None
- Profit factor: None
- Fee drag: None
- Warnings: []

## Manual Trade Tickets
- Tickets generated for human review only: 0

## Warnings
- provider_unhealthy:451 Client Error:  for url: https://api.binance.com/api/v3/ping
- Crypto provider unhealthy; intraday crypto engine remains in no-op mode.
- Crypto provider error for BTCUSDT: 451 Client Error:  for url: https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=120
- Crypto provider failed for all enabled symbols; engine returned no-op.
- Quote retrieval failed for BTCUSDT: 451 Client Error:  for url: https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT
- exit_candle_retrieval_failed:BTCUSDT:451 Client Error:  for url: https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=120
- Provider unhealthy during crypto paper daily close.
- Provider mark failed for BTCUSDT: 451 Client Error:  for url: https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT
- Missing latest price for BTCUSDT; used last known price.
- Limited symbol attribution: no realized per-symbol exit data available.
