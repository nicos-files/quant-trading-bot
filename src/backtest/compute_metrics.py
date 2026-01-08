import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple


def compute_metrics(
    capital_log: List[Dict],
    daily_ret: List[float],
    trades_rows: List[Dict],
    day_dates,
    out_dir: Path,
    cfg: dict
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    df_equity = pd.DataFrame(capital_log)
    if not df_equity.empty:
        df_equity = df_equity.sort_values("date")
    out_dir.mkdir(parents=True, exist_ok=True)

    equity_path = out_dir / "equity_curve.csv"
    df_equity.to_csv(equity_path, index=False)

    if df_equity.empty:
        metrics = {"ret_total": 0.0, "ret_daily_mean": 0.0, "max_drawdown": 0.0, "operations": 0}
        summary = df_equity
    else:
        initial_capital = float(cfg.get("INITIAL_CAPITAL", 100.0))
        ret_total = (df_equity["capital"].iloc[-1] / initial_capital) - 1.0
        ret_daily_mean = float(np.mean(daily_ret)) if daily_ret else 0.0
        drawdown = (df_equity["capital"].cummax() - df_equity["capital"]) / df_equity["capital"].cummax()
        max_drawdown = float(drawdown.max()) if not drawdown.empty else 0.0
        operations = len(trades_rows)
        metrics = {
            "ret_total": float(ret_total),
            "ret_daily_mean": float(ret_daily_mean),
            "max_drawdown": float(max_drawdown),
            "operations": int(operations),
        }
        summary = df_equity

    summary_path = out_dir / "backtest_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    return summary, metrics
