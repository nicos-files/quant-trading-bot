import os
import requests
import pandas as pd
import argparse
import hashlib
import time
from pathlib import Path
from typing import Optional
from src.utils.execution_context import (
    get_execution_date,
    get_execution_hour,
    ensure_date_dir
)

# =========================
# CONFIGURACIÓN
# =========================
ROOT = Path(__file__).resolve().parents[3] 
RAW_PATH = ROOT / "data" / "raw" /"sentiment"
HASH_INDEX_PATH = Path("data/indexes/sentiment_hashes_seen.csv")
RAW_PATH.mkdir(parents=True, exist_ok=True)
HASH_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

TICKERS = ["AAPL", "TSLA", "GOOGL", "MSFT", "META", "NVDA", "AMZN"]
API_KEY = "9a1cce8fb2df4f2f9b47b238e68e6a3e"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# =========================
# FUNCIONES AUXILIARES
# =========================

def hash_headline(row):
    base = f"{row.get('title', '')}_{row.get('source', '')}_{row.get('publishedAt', '')}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()

def filter_new_headlines(df, seen_hashes_path):
    df["hash"] = df.apply(hash_headline, axis=1)
    if seen_hashes_path.exists():
        seen = pd.read_csv(seen_hashes_path)["hash"].tolist()
        df = df[~df["hash"].isin(seen)]
    return df

def update_seen_hashes(df, seen_hashes_path):
    seen_df = pd.DataFrame({"hash": df["hash"].unique()})
    if seen_hashes_path.exists():
        prev = pd.read_csv(seen_hashes_path)
        seen_df = pd.concat([prev, seen_df]).drop_duplicates()
    seen_df.to_csv(seen_hashes_path, index=False)

def save_sentiment(df, ticker, source, date, hour):
    target_dir = ensure_date_dir(
        base=RAW_PATH / ticker,
        date=date,
        hour=hour
    )
    filename = f"sentiment_{ticker}_{source}.parquet"
    path = target_dir / filename
    df.to_parquet(path, index=False)
    print(f" Guardado: {path}")


# =========================
# FUNCIONES DE INGESTA
# =========================

def fetch_general_news_raw(api_key, date, hour):
    print(" Descargando titulares económicos generales...")
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": "economy OR inflation OR interest rates OR recession",
        "language": "en",
        "sortBy": "publishedAt",
        "apiKey": api_key,
        "pageSize": 30
    }

    try:
        response = requests.get(url, params=params)
        articles = response.json().get("articles", [])
        df = pd.DataFrame([{
            "source": "newsapi",
            "title": a.get("title"),
            "description": a.get("description"),
            "publishedAt": a.get("publishedAt")
        } for a in articles if "title" in a])
        df = filter_new_headlines(df, HASH_INDEX_PATH)
        if not df.empty:
            save_sentiment(df, ticker="economy", source="newsapi", date=date, hour=hour)
            update_seen_hashes(df, HASH_INDEX_PATH)
            time.sleep(1)
    except Exception as e:
        print(f" Error al descargar titulares generales: {e}")

def fetch_general_reddit_raw(date, hour):
    print(" Descargando posts generales de Reddit sobre economía...")
    query = "economy OR inflation OR interest rates OR recession"
    url = f"https://www.reddit.com/search.json?q={query}&limit=30"

    try:
        response = requests.get(url, headers=HEADERS)
        posts = response.json().get("data", {}).get("children", [])
        df = pd.DataFrame([{
            "source": "reddit",
            "title": p["data"].get("title"),
            "subreddit": p["data"].get("subreddit"),
            "publishedAt": p["data"].get("created_utc")
        } for p in posts if "title" in p["data"]])
        df = filter_new_headlines(df, HASH_INDEX_PATH)
        if not df.empty:
            save_sentiment(df, ticker="economy", source="reddit", date=date, hour=hour)
            update_seen_hashes(df, HASH_INDEX_PATH)
            time.sleep(1)
    except Exception as e:
        print(f" Error al descargar posts generales de Reddit: {e}")

def fetch_newsapi_sentiment(ticker, api_key, date, hour):
    print(f"NewsAPI para {ticker}")
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": ticker,
        "from": "2025-09-01",
        "sortBy": "popularity",
        "language": "en",
        "apiKey": api_key,
        "pageSize": 20
    }

    try:
        response = requests.get(url, params=params)
        if response.status_code != 200:
            print(f"  Error HTTP {response.status_code} NewsAPI {ticker}")
            return

        articles = response.json().get("articles", [])
        df = pd.DataFrame([{
            "source": "newsapi",
            "title": a.get("title"),
            "publishedAt": a.get("publishedAt")
        } for a in articles if "title" in a])
        df = filter_new_headlines(df, HASH_INDEX_PATH)
        if not df.empty:
            save_sentiment(df, ticker=ticker, source="newsapi", date=date, hour=hour)
            update_seen_hashes(df, HASH_INDEX_PATH)
        time.sleep(1)

    except Exception as e:
        print(f"  Error NewsAPI {ticker}: {e}")


def fetch_reddit_by_ticker(ticker, date, hour):
    print(f"Reddit para {ticker}")
    url = f"https://www.reddit.com/search.json?q={ticker}&limit=20"

    try:
        response = requests.get(url, headers=HEADERS)
        posts = response.json().get("data", {}).get("children", [])
        df = pd.DataFrame([{
            "source": "reddit",
            "title": p["data"]["title"],
            "publishedAt": p["data"].get("created_utc")
        } for p in posts if "title" in p["data"]])
        df = filter_new_headlines(df, HASH_INDEX_PATH)
        if not df.empty:
            save_sentiment(df, ticker=ticker, source="reddit", date=date, hour=hour)
            update_seen_hashes(df, HASH_INDEX_PATH)
            time.sleep(1)
    except Exception as e:
        print(f"Error Reddit {ticker}: {e}")

# =========================
# EJECUCIÓN PRINCIPAL
# =========================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    args = parser.parse_args()

    date = get_execution_date(args.date)
    hour = get_execution_hour(args.hour)

    fetch_general_news_raw(API_KEY, date, hour)
    fetch_general_reddit_raw(date, hour)

    for ticker in TICKERS:
        fetch_newsapi_sentiment(ticker, API_KEY, date, hour)
        fetch_reddit_by_ticker(ticker, date, hour)
