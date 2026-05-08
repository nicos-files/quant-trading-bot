# Crypto Paper Strategy Evaluation

Paper-only evaluation. Metrics are based on simulated fills, fees, and slippage.

## Executive Summary
- Closed trades: 11
- Open trades: 3
- Net profit: -0.920794
- Win rate: 63.6364
- Profit factor: 0.6542784647184302
- Expectancy: -0.08370856926775044

## Trade Quality
- Average win: 0.24894348053698212
- Average loss: -0.6658496564260324
- Average win/loss ratio: 0.3738734084105315
- Best trade: {'trade_id': 'crypto-trade-0004', 'symbol': 'BTCUSDT', 'net_pnl': 0.3649687241573047, 'return_pct': 1.4598748966292188, 'exit_reason': 'TAKE_PROFIT'}
- Worst trade: {'trade_id': 'crypto-trade-0008', 'symbol': 'BTCUSDT', 'net_pnl': -0.8144283226022724, 'return_pct': -3.2577132904090895, 'exit_reason': 'STOP_LOSS'}
- Consecutive wins max: 7
- Consecutive losses max: 4

## Exit Breakdown
- STOP_LOSS: count=4 total_net_pnl=-2.6633986257041298
- TAKE_PROFIT: count=7 total_net_pnl=1.7426043637588748
- MANUAL_SELL: count=0 total_net_pnl=0
- UNKNOWN: count=0 total_net_pnl=0

## Fees and Slippage
- Total fees: 0.549629
- Total slippage: 0.274814
- Fee drag % of gross P&L: 148.0819047353873

## Per-Symbol Results
| Symbol | Trades | Win rate | Net P&L | Expectancy | Fees | Stop-loss count | Take-profit count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 11 | 63.6364 | -0.920794 | -0.08370856926775044 | 0.549629 | 4 | 7 |

## Open Trades
- BTCUSDT: qty=0.00031270 entry_price=79949.544795 entry_time=2026-05-07T16:25:11.389372 unrealized=0.08191731694651294
- BTCUSDT: qty=0.00031239 entry_price=80028.05403 entry_time=2026-05-07T16:30:11.082174 unrealized=0.08183695430412864
- BTCUSDT: qty=0.00031271 entry_price=79947.39372000001 entry_time=2026-05-07T17:45:08.542826 unrealized=0.08191952102452413

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
