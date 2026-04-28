# Crypto Config Promotion Proposal

## Summary
- Experiment name: crypto_baseline_grid_v1
- Selected config ID: cfg-001
- Selection method: best_eligible
- Eligible for candidate: True
- Paper-forward enabled: yes
- Live trading enabled: no

## Selected Metrics
- Closed trades: 1
- Open trades: 1
- Net profit: 0.17453785607196376
- Expectancy: 0.17453785607196376
- Profit factor: None
- Win rate: 1.0
- Max drawdown: -0.037493753123442275
- Total fees: 0.05022476261869065
- Total slippage: 0.025112443778110942

## Proposed Strategy Parameters
| Parameter | Current value | Candidate value |
| --- | --- | --- |
| name | intraday_crypto_baseline | intraday_crypto_baseline |
| timeframe | 5m | 5m |
| lookback_limit | 120 | 120 |
| fast_ma_window | 9 | 2 |
| slow_ma_window | 21 | 3 |
| min_abs_signal_strength | 0.001 | 0.0001 |
| max_volatility_pct | 0.08 | 1.0 |
| risk_reward_ratio | 1.5 | 1.5 |
| stop_loss_pct | 0.006 | 0.02 |
| take_profit_pct | 0.009 | 0.01 |
| max_paper_notional | 25.0 | 25.0 |
| allow_short | False | False |

## Safety Checks
- live_enabled remains false: True
- no API keys: True
- no broker settings: True
- no live trading: true
- paper-only candidate: true

## Validation Errors
- None.

## Validation Warnings
- closed_trades_count below preferred threshold.
- Small sample size: fewer than 30 closed trades.
- Profit factor is not above 1.0.
- Drawdown was calculated from event-level equity points.
- Strategy is not proven live.

## Manual Review Instructions
- This did not modify production crypto.json.
- Review crypto_config_candidate.json.
- If accepted, manually copy or apply changes.
- Run paper-forward testing before any live integration.
- Do not enable live trading.

## Notes
- Paper-only.
- Simulated fees and slippage.
- No real orders placed.
- Winning config was not auto-applied.
