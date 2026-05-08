# Crypto Paper Strategy Evaluation

Paper-only evaluation. Metrics are based on simulated fills, fees, and slippage.

## Executive Summary
- Closed trades: 3
- Open trades: 4
- Net profit: 0.642299
- Win rate: 100.0000
- Profit factor: n/a
- Expectancy: 0.21409966702902528

## Trade Quality
- Average win: 0.21409966702902528
- Average loss: n/a
- Average win/loss ratio: n/a
- Best trade: {'trade_id': 'crypto-trade-0001', 'symbol': 'BTCUSDT', 'net_pnl': 0.3003124791982777, 'return_pct': 1.201249916793111, 'exit_reason': 'TAKE_PROFIT'}
- Worst trade: {'trade_id': 'crypto-trade-0002', 'symbol': 'BTCUSDT', 'net_pnl': 0.1674519655759657, 'return_pct': 0.6698078623038628, 'exit_reason': 'TAKE_PROFIT'}
- Consecutive wins max: 3
- Consecutive losses max: 0

## Exit Breakdown
- STOP_LOSS: count=0 total_net_pnl=0
- TAKE_PROFIT: count=3 total_net_pnl=0.6422990010870758
- MANUAL_SELL: count=0 total_net_pnl=0
- UNKNOWN: count=0 total_net_pnl=0

## Fees and Slippage
- Total fees: 0.150793
- Total slippage: 0.075397
- Fee drag % of gross P&L: 19.013314265750424

## Per-Symbol Results
| Symbol | Trades | Win rate | Net P&L | Expectancy | Fees | Stop-loss count | Take-profit count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 3 | 100.0000 | 0.642299 | 0.21409966702902528 | 0.150793 | 0 | 3 |

## Open Trades
- BTCUSDT: qty=0.00030913 entry_price=80870.97528 entry_time=2026-05-05T11:00:10.565774 unrealized=-0.051979010242375986
- BTCUSDT: qty=0.00030865 entry_price=80996.648085 entry_time=2026-05-05T11:30:09.822216 unrealized=-0.0518983606331301
- BTCUSDT: qty=0.00030755 entry_price=81286.352865 entry_time=2026-05-05T12:30:09.564412 unrealized=-0.051713394736400145
- BTCUSDT: qty=0.00030682 entry_price=81482.110695 entry_time=2026-05-05T14:30:11.271222 unrealized=-0.05158915517204443

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
