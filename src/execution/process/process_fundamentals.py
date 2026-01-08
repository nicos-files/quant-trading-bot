import pandas as pd
import argparse
from pathlib import Path
from src.utils.execution_context import (
    get_execution_date,
    get_execution_hour,
    ensure_date_dir
)

# Columnas clave por fuente
alpha_cols = {
    "Symbol": "ticker",
    "PERatio": "pe_ratio",
    "PriceToBookRatio": "pb_ratio",
    "ReturnOnEquityTTM": "roe",
    "ReturnOnAssetsTTM": "roa",
    "DebtToEquity": "de_ratio",
    "DividendYield": "dividend_yield",
    "EPS": "eps",
    "SharesOutstanding": "shares_outstanding",
    "PercentInstitutions": "percent_institutions",
    "PercentInsiders": "percent_insiders"
}

finnhub_cols = {
    "peBasicExclExtraTTM": "pe_ratio",
    "pbAnnual": "pb_ratio",
    "roeTTM": "roe",
    "roaTTM": "roa",
    "totalDebt/totalEquityAnnual": "de_ratio",
    "dividendYieldIndicatedAnnual": "dividend_yield",
    "epsInclExtraItemsAnnual": "eps",
    "grossMarginTTM": "gross_margin",
    "operatingMarginTTM": "operating_margin",
    "netMarginTTM": "net_margin",
    "freeCashFlowAnnual": "free_cash_flow",
    "shareOutstanding": "shares_outstanding",
    "yearToDatePriceReturnDaily": "ytd_return"
}

ROOT = Path(__file__).resolve().parents[3]
RAW_BASE = ROOT / "data" / "raw" / "fundamentals"
PROCESSED_BASE = ROOT / "data" / "processed" / "fundamentals"
FUENTES = ["alphaV", "finnhub"]

def process_fundamentals(ticker: str, date, hour: str):
    base_dir = RAW_BASE / "alphaV" / ticker / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}" / hour
    alpha_path = base_dir / f"{ticker}.parquet"

    base_dir = RAW_BASE / "finnhub" / ticker / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}" / hour
    finnhub_path = base_dir / f"{ticker}.parquet"

    if not alpha_path.exists() or not finnhub_path.exists():
        print(f" Archivos faltantes para {ticker}")
        return

    print(f" Procesando fundamentales: {ticker}")
    df_alpha = pd.read_parquet(alpha_path)
    df_finnhub = pd.read_parquet(finnhub_path)

    final_data = {v: None for v in alpha_cols.values()}
    final_data.update({v: None for v in finnhub_cols.values()})

    for raw_col, final_col in alpha_cols.items():
        if raw_col in df_alpha.columns:
            final_data[final_col] = df_alpha.at[0, raw_col]

    for raw_col, final_col in finnhub_cols.items():
        if raw_col in df_finnhub.columns:
            final_data[final_col] = df_finnhub.at[0, raw_col]

    df = pd.DataFrame([final_data])
    df["ticker"] = ticker
    df = df.convert_dtypes()

    nulls = df.isnull().sum().sum()
    total = df.shape[1] - 1
    completeness = (total - nulls) / total

    UMBRAL_MINIMO = 0.7
    if completeness >= UMBRAL_MINIMO:
        out_dir = ensure_date_dir(PROCESSED_BASE, date, hour)
        out_path = out_dir / f"{ticker}.parquet"
        df.to_parquet(out_path, index=False)
        print(f"  {ticker} incluido ({completeness:.0%})  {out_path}")
    else:
        print(f"  {ticker} excluido por baja completitud ({completeness:.0%})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    args = parser.parse_args()

    date = get_execution_date(args.date)
    hour = get_execution_hour(args.hour)

    tickers_alpha = [d.name for d in (RAW_BASE / "alphaV").iterdir() if d.is_dir()]
    tickers_finnhub = [d.name for d in (RAW_BASE / "finnhub").iterdir() if d.is_dir()]
    tickers = sorted(set(tickers_alpha) & set(tickers_finnhub))  # Solo tickers con ambas fuentes

    for ticker in tickers:
        process_fundamentals(ticker, date, hour)
