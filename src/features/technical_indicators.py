

import pandas as pd
import pandas_ta as ta
import os

def calculate_indicators(ticker: str) -> dict:
    """
    Calcula indicadores técnicos para el último día disponible.
    Args:
        ticker (str): Ticker del activo
    Returns:
        dict: RSI, MACD, SMA
    """
    path = f"data/raw/{ticker.replace('.', '_')}.parquet"
    if not os.path.exists(path):
        raise FileNotFoundError(f"No se encontró el archivo para {ticker}")

    df = pd.read_parquet(path)
    df.ta.rsi(length=14, append=True)
    df.ta.macd(append=True)
    df.ta.sma(length=20, append=True)

    latest = df.tail(1).iloc[0]
    indicators = {
        "RSI": round(latest.get("RSI_14", 0), 2),
        "MACD": round(latest.get("MACD_12_26_9", 0), 2),
        "SMA": round(latest.get("SMA_20", 0), 2)
    }

    return indicators
