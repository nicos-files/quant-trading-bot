import time
import argparse
import pandas as pd
from pathlib import Path
from pandas_datareader import data as web
from datetime import datetime
from typing import Optional
from src.utils.execution_context import (
    get_execution_date,
    get_execution_hour,
    ensure_date_dir
)

# Tickers
tickers_us = [
    "AAPL.US", "TSLA.US", "GOOGL.US", "MSFT.US", "META.US", "NVDA.US",
    "AMZN.US", "JPM.US", "BRK.B.US", "V.US", "MA.US", "DIS.US", "NFLX.US",
    "INTC.US", "AMD.US"
]

tickers_ba = [
    "GGAL.BA", "YPFD.BA", "PAMP.BA", "BMA.BA", "TXAR.BA", "CEPU.BA",
    "AAPL.BA", "TSLA.BA", "GOOGL.BA", "MSFT.BA"
]

START_DATE = "2018-01-01"
END_DATE = datetime.today().strftime("%Y-%m-%d")
FUENTE = "prices"
ROOT = Path(__file__).resolve().parents[3] 
RAW_PATH = ROOT / "data" / "raw"
REQUIRED_COLS = ["open", "high", "low", "close", "volume"]

def save_raw_data(df: pd.DataFrame, fuente: str, ticker: str, date: datetime, hour: Optional[str]):
    target_dir = ensure_date_dir(
        base=RAW_PATH / fuente / ticker,
        date=date,
        hour=hour
    )
    path = target_dir / f"{fuente}_{ticker}.parquet"
    df.to_parquet(path)
    print(f" Guardado: {path}")

def fetch_price_data(ticker: str) -> Optional[pd.DataFrame]:
    print(f" Intentando descargar {ticker} desde Stooq...")
    try:
        df = web.DataReader(ticker, "stooq", START_DATE, END_DATE)
        if df.empty:
            print(f" Stooq sin datos para {ticker}")
            return None
    except Exception as e:
        print(f" Error con Stooq para {ticker}: {e}")
        return None

    df.reset_index(inplace=True)
    df.columns = [col.lower() for col in df.columns]
    df["ticker"] = ticker

    if not all(col in df.columns for col in REQUIRED_COLS):
        print(f" Datos incompletos para {ticker}, se omite.")
        return None

    return df

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    args = parser.parse_args()

    date = get_execution_date(args.date)
    hour = get_execution_hour(args.hour)

    all_tickers = tickers_ba + tickers_us
    for ticker in all_tickers:
        df = fetch_price_data(ticker)
        if df is not None:
            save_raw_data(df, fuente=FUENTE, ticker=ticker, date=date, hour=hour)
        time.sleep(1)  # para evitar bloqueos por exceso de llamadas
