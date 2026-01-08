import os
import pandas as pd
import sys
import time
from datetime import datetime
from pathlib import Path
import argparse

sys.path.append("C:/Users/NAguilar/Proyectos/AutoGen/quant-trading-bot")
from src.utils.llm_logger import log_llm_interaction
from src.utils.execution_context import (
    ensure_date_dir,
    get_etl_args,
    get_current_args,
    get_execution_date
)

def load_parquet(path):
    return pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame()

def consolidate_daily_features(date: datetime):
    base_dir = Path("data/processed/features") / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}"
    hourly_files = list(base_dir.glob("*/features.parquet"))

    dfs = []
    for f in hourly_files:
        try:
            df = pd.read_parquet(f)
            dfs.append(df)
        except Exception as e:
            print(f"[WARN] No se pudo leer {f}: {e}")

    if dfs:
        df_day = pd.concat(dfs, ignore_index=True).sort_index()
        output_path = base_dir / "features.parquet"
        df_day.to_parquet(output_path)
        print(f"[INFO] Consolidado diario guardado en {output_path}")
        print(f"[INFO] Total de muestras consolidadas: {len(df_day)}")
    else:
        print(f"[WARN] No se encontraron features horarios para consolidar en {base_dir}")

def combine_features(date: datetime, hour: str):
    output_dir = ensure_date_dir(Path("data/processed/features"), date, hour)

    df_sentimiento = pd.read_parquet("data/processed_daily/sentiment_daily.parquet")
    df_fundamentals = pd.read_parquet("data/processed_daily/fundamentals_daily.parquet")
    df_indicadores = pd.read_parquet("data/processed_daily/indicadores_daily.parquet")

    sentimiento_general = df_sentimiento[df_sentimiento["ticker"] == "GENERAL"]
    sentimiento_valor = sentimiento_general["sentimiento_combinado"].iloc[0] if not sentimiento_general.empty else None

    all_rows = []

    for ticker in df_indicadores["ticker"].unique():
        start = time.time()
        log_entry = {
            "timestamp": datetime.now(),
            "module": "feature_engineering",
            "ticker": ticker
        }

        try:
            df_ind = df_indicadores[df_indicadores["ticker"] == ticker].copy()
            if df_ind.empty:
                log_entry["status"] = "skip"
                log_entry["reason"] = "indicadores vacíos"
                log_llm_interaction(log_entry, log_name="feature_engineering")
                continue

            fundamentales = df_fundamentals[df_fundamentals["ticker"] == ticker]
            if fundamentales.empty:
                print(f" No hay fundamentales para {ticker}")
                log_entry["status"] = "error"
                log_entry["reason"] = "fundamentales vacíos"
                log_llm_interaction(log_entry, log_name="feature_engineering")
                continue

            sentimiento_especifico = df_sentimiento[df_sentimiento["ticker"] == ticker]
            sent_valor = sentimiento_especifico["sentimiento_especifico"].iloc[0] if not sentimiento_especifico.empty else sentimiento_valor

            for col in fundamentales.columns:
                if col != "ticker":
                    df_ind.loc[:, col] = fundamentales[col].iloc[0]

            df_ind["sentimiento_especifico"] = sent_valor
            df_ind["sentimiento_general"] = sentimiento_valor

            all_rows.append(df_ind)

            duration = time.time() - start
            log_entry["status"] = "ok"
            log_entry["duration_sec"] = round(duration, 2)
            log_entry["features_generadas"] = len(df_ind.columns)
            log_llm_interaction(log_entry, log_name="feature_engineering")

        except Exception as e:
            log_entry["status"] = "error"
            log_entry["reason"] = str(e)
            log_llm_interaction(log_entry, log_name="feature_engineering")
            continue

    df_final = pd.concat(all_rows, ignore_index=False).sort_index()

    # Enriquecimiento temporal
    df_final["RSI_t-1"] = df_final.groupby("ticker")["RSI"].shift(1)
    df_final["daily_return_t-1"] = df_final.groupby("ticker")["daily_return"].shift(1)
    df_final["MACD_t-1"] = df_final.groupby("ticker")["MACD"].shift(1)

    # Conversión numérica
    for col in df_final.columns:
        if col not in ["ticker", "sentimiento_especifico", "sentimiento_general"]:
            df_final[col] = pd.to_numeric(df_final[col], errors="coerce")

    # Targets y combinaciones
    df_final["target_clasificacion"] = (df_final["daily_return"] > 0).astype(int)
    df_final["RSI_x_volume"] = df_final["RSI"] * df_final["volume_avg"]
    df_final["MACD_x_sentimiento"] = df_final["MACD"] * df_final["sentimiento_general"]

    # Validación
    columns_to_check = [
        "bollinger_upper", "bollinger_lower", "bollinger_width",
        "RSI_t-1", "daily_return_t-1", "MACD_t-1"
    ]
    missing_cols = [col for col in columns_to_check if col not in df_final.columns]
    if missing_cols:
        print(f" Faltan columnas esperadas: {missing_cols}")
    else:
        nulls = df_final[columns_to_check].isnull().mean()
        print("\nValidación de columnas enriquecidas (porcentaje de NaNs):")
        print(nulls.sort_values(ascending=False))

    df_final = df_final.dropna(subset=columns_to_check)

    # Targets futuros
    df_final["target_regresion_t+1"] = df_final.groupby("ticker")["daily_return"].shift(-1)
    df_final["target_clasificacion_t+1"] = (df_final["target_regresion_t+1"] > 0.005).astype(int)
    df_final = df_final.dropna(subset=["target_regresion_t+1", "target_clasificacion_t+1"])

    # Timestamp del proceso (viene del orquestador)
    timestamp_proceso = datetime(
    year=date.year,
    month=date.month,
    day=date.day,
    hour=int(hour[:2]),
    minute=int(hour[2:])
    )
    # Timestamp real de ejecución del script
    timestamp_ejecucion = datetime.now()

    df_final["timestamp_proceso"] = timestamp_proceso
    df_final["timestamp_ejecucion"] = timestamp_ejecucion

    # Guardar archivo horario
    output_path = output_dir / "features.parquet"
    df_final.to_parquet(output_path)
    print(f"Features horarios guardados en {output_path}")
    print(f"Total de muestras: {len(df_final)}")
    print("Preview:")
    print(df_final.head())

    # Consolidar el día completo
    consolidate_daily_features(date)

def parse_args():
    parser = argparse.ArgumentParser(description="Genera features diarios combinando módulos procesados.")
    parser.add_argument("--date", type=str, help="Fecha de ejecución en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora de ejecución en formato HHMM")
    parser.add_argument("--from-etl", action="store_true", help="Usar fecha/hora del último ETL")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    if args.date and args.hour:
        date = args.date
        hour = args.hour
        print(f"[INFO] Usando fecha/hora manual: {date} {hour}")
    elif args.from_etl:
        etl_args = get_etl_args()
        date = etl_args["date"]
        hour = etl_args["hour"]
        print(f"[INFO] Usando fecha/hora del último ETL: {date} {hour}")
    else:
        current_args = get_current_args()
        date = current_args["date"]
        hour = current_args["hour"]
        print(f"[INFO] Usando fecha/hora actual: {date} {hour}")

    combine_features(get_execution_date(date), hour)
