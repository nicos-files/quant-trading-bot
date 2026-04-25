# Crypto Paper Parameter Experiment

## Summary
- Experiment name: crypto_baseline_grid_v1
- Symbols: BTCUSDT
- Configs tested: 1
- Eligible configs: 1
- Best config: cfg-001
- Best expectancy: 0.17453785607196376
- Best profit factor: None
- Best net P&L: 0.17453785607196376
- Best max drawdown %: -0.037493753123442275

## Ranking
| Rank | Config ID | Eligible | Closed trades | Net P&L | Expectancy | Profit factor | Win rate | Max drawdown % | Total fees |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | cfg-001 | True | 1 | 0.174538 | 0.17453785607196376 | None | 1.0 | -0.037493753123442275 | 0.050225 |

## Best Config Details
- Config ID: cfg-001
- Parameters: {'timeframe': '5m', 'lookback_limit': 120, 'fast_ma_window': 2, 'slow_ma_window': 3, 'min_abs_signal_strength': 0.0001, 'max_volatility_pct': 1.0, 'min_volume_ratio': None, 'risk_reward_ratio': 1.5, 'stop_loss_pct': 0.02, 'take_profit_pct': 0.01, 'max_paper_notional': 25.0, 'allow_short': False}
- Metrics: {'closed_trades_count': 1, 'open_trades_count': 1, 'winning_trades_count': 1, 'losing_trades_count': 0, 'flat_trades_count': 0, 'win_rate': 1.0, 'loss_rate': 0.0, 'average_win': 0.17453785607196376, 'average_loss': None, 'average_trade_pnl': 0.17453785607196376, 'median_trade_pnl': 0.17453785607196376, 'best_trade': {'trade_id': 'crypto-trade-0001', 'symbol': 'BTCUSDT', 'net_pnl': 0.17453785607196376, 'return_pct': 0.698151424287855, 'exit_reason': 'TAKE_PROFIT'}, 'worst_trade': {'trade_id': 'crypto-trade-0001', 'symbol': 'BTCUSDT', 'net_pnl': 0.17453785607196376, 'return_pct': 0.698151424287855, 'exit_reason': 'TAKE_PROFIT'}, 'gross_profit': 0.17453785607196376, 'gross_loss': 0, 'net_profit': 0.17453785607196376, 'profit_factor': None, 'expectancy': 0.17453785607196376, 'average_return_pct': 0.698151424287855, 'average_holding_seconds': 300.0, 'total_fees': 0.05022476261869065, 'total_slippage': 0.025112443778110942, 'fee_drag_pct_of_gross_pnl': 22.345692051139547, 'slippage_drag_pct_of_gross_pnl': 11.17287381878823, 'stop_loss_count': 0, 'take_profit_count': 1, 'manual_sell_count': 0, 'stop_loss_rate': 0.0, 'take_profit_rate': 1.0, 'average_win_loss_ratio': None, 'largest_win': 0.17453785607196376, 'largest_loss': None, 'consecutive_wins_max': 1, 'consecutive_losses_max': 0, 'symbols_traded': ['BTCUSDT'], 'per_symbol_metrics': {'BTCUSDT': {'closed_trades_count': 1, 'open_trades_count': 1, 'win_rate': 1.0, 'net_profit': 0.17453785607196376, 'average_trade_pnl': 0.17453785607196376, 'best_trade': {'trade_id': 'crypto-trade-0001', 'symbol': 'BTCUSDT', 'net_pnl': 0.17453785607196376, 'return_pct': 0.698151424287855, 'exit_reason': 'TAKE_PROFIT'}, 'worst_trade': {'trade_id': 'crypto-trade-0001', 'symbol': 'BTCUSDT', 'net_pnl': 0.17453785607196376, 'return_pct': 0.698151424287855, 'exit_reason': 'TAKE_PROFIT'}, 'total_fees': 0.05022476261869065, 'stop_loss_count': 0, 'take_profit_count': 1, 'average_holding_seconds': 300.0, 'expectancy': 0.17453785607196376}}, 'warnings': ['Drawdown calculated from event-level equity points, not every candle.', 'Small sample size: fewer than 30 closed trades.', 'Open trades are excluded from closed-trade expectancy.', 'Paper-only results; no real execution occurred.', 'Fees and slippage are simulated.'], 'metadata': {'paper_only': True, 'live_trading': False}, 'paper_only': True, 'live_trading': False, 'max_drawdown_pct': -0.037493753123442275, 'rejected_orders_count': 0}
- Warnings: ['Drawdown calculated from event-level equity points, not every candle.', 'Small sample size: fewer than 30 closed trades.', 'Open trades are excluded from closed-trade expectancy.', 'Paper-only results; no real execution occurred.', 'Fees and slippage are simulated.']

## Worst Config Details
- Config ID: cfg-001
- Parameters: {'timeframe': '5m', 'lookback_limit': 120, 'fast_ma_window': 2, 'slow_ma_window': 3, 'min_abs_signal_strength': 0.0001, 'max_volatility_pct': 1.0, 'min_volume_ratio': None, 'risk_reward_ratio': 1.5, 'stop_loss_pct': 0.02, 'take_profit_pct': 0.01, 'max_paper_notional': 25.0, 'allow_short': False}
- Metrics: {'closed_trades_count': 1, 'open_trades_count': 1, 'winning_trades_count': 1, 'losing_trades_count': 0, 'flat_trades_count': 0, 'win_rate': 1.0, 'loss_rate': 0.0, 'average_win': 0.17453785607196376, 'average_loss': None, 'average_trade_pnl': 0.17453785607196376, 'median_trade_pnl': 0.17453785607196376, 'best_trade': {'trade_id': 'crypto-trade-0001', 'symbol': 'BTCUSDT', 'net_pnl': 0.17453785607196376, 'return_pct': 0.698151424287855, 'exit_reason': 'TAKE_PROFIT'}, 'worst_trade': {'trade_id': 'crypto-trade-0001', 'symbol': 'BTCUSDT', 'net_pnl': 0.17453785607196376, 'return_pct': 0.698151424287855, 'exit_reason': 'TAKE_PROFIT'}, 'gross_profit': 0.17453785607196376, 'gross_loss': 0, 'net_profit': 0.17453785607196376, 'profit_factor': None, 'expectancy': 0.17453785607196376, 'average_return_pct': 0.698151424287855, 'average_holding_seconds': 300.0, 'total_fees': 0.05022476261869065, 'total_slippage': 0.025112443778110942, 'fee_drag_pct_of_gross_pnl': 22.345692051139547, 'slippage_drag_pct_of_gross_pnl': 11.17287381878823, 'stop_loss_count': 0, 'take_profit_count': 1, 'manual_sell_count': 0, 'stop_loss_rate': 0.0, 'take_profit_rate': 1.0, 'average_win_loss_ratio': None, 'largest_win': 0.17453785607196376, 'largest_loss': None, 'consecutive_wins_max': 1, 'consecutive_losses_max': 0, 'symbols_traded': ['BTCUSDT'], 'per_symbol_metrics': {'BTCUSDT': {'closed_trades_count': 1, 'open_trades_count': 1, 'win_rate': 1.0, 'net_profit': 0.17453785607196376, 'average_trade_pnl': 0.17453785607196376, 'best_trade': {'trade_id': 'crypto-trade-0001', 'symbol': 'BTCUSDT', 'net_pnl': 0.17453785607196376, 'return_pct': 0.698151424287855, 'exit_reason': 'TAKE_PROFIT'}, 'worst_trade': {'trade_id': 'crypto-trade-0001', 'symbol': 'BTCUSDT', 'net_pnl': 0.17453785607196376, 'return_pct': 0.698151424287855, 'exit_reason': 'TAKE_PROFIT'}, 'total_fees': 0.05022476261869065, 'stop_loss_count': 0, 'take_profit_count': 1, 'average_holding_seconds': 300.0, 'expectancy': 0.17453785607196376}}, 'warnings': ['Drawdown calculated from event-level equity points, not every candle.', 'Small sample size: fewer than 30 closed trades.', 'Open trades are excluded from closed-trade expectancy.', 'Paper-only results; no real execution occurred.', 'Fees and slippage are simulated.'], 'metadata': {'paper_only': True, 'live_trading': False}, 'paper_only': True, 'live_trading': False, 'max_drawdown_pct': -0.037493753123442275, 'rejected_orders_count': 0}

## Disqualified / Low Sample Configs
- None.

## Notes
- Paper-only.
- Simulated fees and slippage.
- No live orders placed.
- No broker integration.
- Winning config was not automatically applied.
- Beware overfitting.
