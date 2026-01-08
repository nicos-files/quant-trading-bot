from pathlib import Path
import json
import numpy as np
from prepare_data import prepare_data
from run_backtest import run_backtest
from compute_metrics import compute_metrics
from plot_equity import plot_equity_curve

# Paths
ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "src" / "backtest" / "config_backtest.json"
FEATURES_PATH = ROOT / "data" / "processed" / "features.parquet"
MODEL_PATH = ROOT / "models" / "xgb_clf_futuro.pkl"
OUT_DIR = ROOT / "simulations"

def main():
    try:
        # Cargar configuración
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)

        np.random.seed(cfg["SEED"])
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        # Preparar datos y generar predicciones
        df = prepare_data(
            features_path=FEATURES_PATH,
            model_path=MODEL_PATH,
            clip_ret=cfg["CLIP_RET"],
            stop_loss=cfg["STOP_LOSS"],
            take_profit=cfg["TAKE_PROFIT"]
        )

        # Ejecutar backtest
        capital_log, daily_ret, trades_rows, day_dates = run_backtest(df, cfg)

        # Calcular métricas y guardar resultados
        summary, metrics = compute_metrics(capital_log, daily_ret, trades_rows, day_dates, OUT_DIR, cfg)

        # Graficar curva de equity
        plot_equity_curve(summary, OUT_DIR / "equity_curve_realistic.png")

        # Mostrar resumen
        print("\nResultados del backtest:")
        print(f"- Retorno total: {metrics['ret_total']:.4f}")
        print(f"- Retorno promedio diario: {metrics['ret_daily_mean']:.5f}")
        print(f"- Máx. drawdown: {metrics['max_drawdown']:.2%}")
        print(f"- Cantidad de operaciones: {metrics['operations']}")
        print(f"Guardado en: {OUT_DIR}")

    except Exception as e:
        print("\nError durante el backtest:")
        print(f"{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

if __name__ == "__main__":
    main()
