import os
import pandas as pd
import argparse
from pathlib import Path
from src.utils.execution_context import (
    get_execution_date,
    get_execution_hour,
    ensure_date_dir
)
ROOT = Path(__file__).resolve().parents[3]
PRECIOS_BASE = ROOT / "data" / "processed" / "prices"
INDICADORES_BASE = ROOT / "data" / "processed" / "indicadores"

def calculate_indicators(ticker: str, date, hour: str):
    precios_dir = PRECIOS_BASE / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}" / hour
    if not precios_dir.exists():
        print(f" No se encontró carpeta de precios para {ticker} en {precios_dir}")
        return None

    archivo = precios_dir / f"{ticker}.parquet"
    if not archivo.exists():
        print(f" No se encontró archivo parquet para {ticker} en {archivo}")
        return None

    try:
        df = pd.read_parquet(archivo)
        df = df.sort_index()

        # Indicadores técnicos
        df["SMA_20"] = df["close"].rolling(window=20).mean()
        df["EMA_20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["daily_return"] = df["close"].pct_change()
        df["volatility"] = df["daily_return"].rolling(window=20).std()
        df["volume_avg"] = df["volume"].rolling(window=20).mean()

        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        df["RSI"] = 100 - (100 / (1 + rs))

        ema_12 = df["close"].ewm(span=12, adjust=False).mean()
        ema_26 = df["close"].ewm(span=26, adjust=False).mean()
        df["MACD"] = ema_12 - ema_26
        df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

        rolling_mean = df["close"].rolling(window=20).mean()
        rolling_std = df["close"].rolling(window=20).std()
        df["bollinger_upper"] = rolling_mean + 2 * rolling_std
        df["bollinger_lower"] = rolling_mean - 2 * rolling_std
        df["bollinger_width"] = df["bollinger_upper"] - df["bollinger_lower"]

        df = df.dropna().copy()
        df["ticker"] = ticker

        out_dir = ensure_date_dir(INDICADORES_BASE, date, hour)
        out_path = out_dir / f"{ticker}.parquet"
        df.to_parquet(out_path)

        print(f" Indicadores guardados para {ticker} en {out_path}")
    except Exception as e:
        print(f" Error procesando indicadores para {ticker}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    args = parser.parse_args()

    date = get_execution_date(args.date)
    hour = get_execution_hour(args.hour)

    tickers = [d.name for d in PRECIOS_BASE.iterdir() if d.is_dir()]
    for ticker in tickers:
        calculate_indicators(ticker, date, hour)
