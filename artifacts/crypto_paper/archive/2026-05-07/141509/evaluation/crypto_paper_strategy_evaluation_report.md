# Crypto Paper Strategy Evaluation

Paper-only evaluation. Metrics are based on simulated fills, fees, and slippage.

## Executive Summary
- Closed trades: 7
- Open trades: 4
- Net profit: 1.742604
- Win rate: 100.0000
- Profit factor: n/a
- Expectancy: 0.24894348053698212

## Trade Quality
- Average win: 0.24894348053698212
- Average loss: n/a
- Average win/loss ratio: n/a
- Best trade: {'trade_id': 'crypto-trade-0004', 'symbol': 'BTCUSDT', 'net_pnl': 0.3649687241573047, 'return_pct': 1.4598748966292188, 'exit_reason': 'TAKE_PROFIT'}
- Worst trade: {'trade_id': 'crypto-trade-0002', 'symbol': 'BTCUSDT', 'net_pnl': 0.1674519655759657, 'return_pct': 0.6698078623038628, 'exit_reason': 'TAKE_PROFIT'}
- Consecutive wins max: 7
- Consecutive losses max: 0

## Exit Breakdown
- STOP_LOSS: count=0 total_net_pnl=0
- TAKE_PROFIT: count=7 total_net_pnl=1.7426043637588748
- MANUAL_SELL: count=0 total_net_pnl=0
- UNKNOWN: count=0 total_net_pnl=0

## Fees and Slippage
- Total fees: 0.352095
- Total slippage: 0.176048
- Fee drag % of gross P&L: 16.80884406319097

## Per-Symbol Results
| Symbol | Trades | Win rate | Net P&L | Expectancy | Fees | Stop-loss count | Take-profit count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 7 | 100.0000 | 1.742604 | 0.24894348053698212 | 0.352095 | 0 | 7 |

## Open Trades
- BTCUSDT: qty=0.00030265 entry_price=82603.230975 entry_time=2026-05-06T11:50:11.030006 unrealized=-0.4351138731275296
- BTCUSDT: qty=0.00030367 entry_price=82327.393125 entry_time=2026-05-06T12:20:09.876378 unrealized=-0.43657172173311376
- BTCUSDT: qty=0.00030606 entry_price=81683.06112 entry_time=2026-05-06T14:30:11.001248 unrealized=-0.44001548509033367
- BTCUSDT: qty=0.00030566 entry_price=81790.875 entry_time=2026-05-06T14:35:11.164794 unrealized=-0.43943547201787686

## Warnings
- Small sample size: fewer than 30 closed trades.
- Open trades are excluded from closed-trade expectancy.
- Paper-only results; no real execution occurred.
- Fees and slippage are simulated.

## Notes
- Paper-only.
- No live orders placed.
- No broker integration.
- Metrics are based on simulated fills, fees, and slippage.
