from pandas_datareader import data as web
from datetime import datetime
import pandas as pd
import os


tickers_us = [
    "AAPL.US",   # Apple
    "TSLA.US",   # Tesla
    "GOOGL.US",  # Google (Alphabet)
    "MSFT.US",   # Microsoft
    "META.US",   # Meta (Facebook)
    "NVDA.US",   # Nvidia
    "AMZN.US",   # Amazon
    "JPM.US",    # JPMorgan Chase
    "BRK.B.US",  # Berkshire Hathaway
    "V.US",      # Visa
    "MA.US",     # Mastercard
    "DIS.US",    # Disney
    "NFLX.US",   # Netflix
    "INTC.US",   # Intel
    "AMD.US",    # AMD
]

tickers_ba = [
    "GGAL.BA",   # Grupo Galicia
    "YPFD.BA",   # YPF
    "PAMP.BA",   # Pampa Energía
    "BMA.BA",    # Banco Macro
    "TXAR.BA",   # Ternium
    "CEPU.BA",   # Central Puerto
    "AAPL.BA",   # CEDEAR Apple
    "TSLA.BA",   # CEDEAR Tesla
    "GOOGL.BA",  # CEDEAR Google
    "MSFT.BA",   # CEDEAR Microsoft
]



def fetch_price_data_safe(ticker, start="2023-01-01", end="2025-08-29"):
    print(f"📡 Intentando descargar {ticker}...")
    try:
        df = web.DataReader(ticker, "stooq", start, end)
        if df.empty:
            print(f"⚠️ Sin datos para {ticker}.")
            return None
        df.reset_index(inplace=True)
        df["ticker"] = ticker
        print(f"✅ {ticker}: {len(df)} registros.")
        return df
    except Exception as e:
        print(f"❌ Error con {ticker}: {e}")
        return None

# Ejecutar con fallback
all_tickers = tickers_ba + tickers_us
dataframes = []

for ticker in all_tickers:
    df = fetch_price_data_safe(ticker)
    if df is not None:
        dataframes.append(df)



def save_to_parquet(df: pd.DataFrame, ticker: str):
    """
    Guarda el DataFrame en formato Parquet en data/raw/
    """
    os.makedirs("data/raw/", exist_ok=True)
    path = f"data/raw/{ticker.replace('.', '_')}.parquet"
    df.to_parquet(path, index=False)
    print(f"✅ Datos guardados en {path}")

