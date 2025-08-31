import pandas as pd
import os

def load_parquet(path):
    if os.path.exists(path):
        return pd.read_parquet(path)
    else:
        print(f"⚠️ No se encontró el archivo: {path}")
        return pd.DataFrame()

def combine_features():
    indicadores = load_parquet("data/processed/indicadores.parquet")
    fundamentales = load_parquet("data/processed/fundamentales.parquet")
    sentimiento_especifico = load_parquet("data/processed/sentimiento.parquet")
    sentimiento_general = load_parquet("data/processed/sentimiento_general.parquet")

    # Merge por ticker
    df = indicadores.merge(fundamentales, on="ticker", how="left")

    # Si sentimiento específico tiene ticker, lo usamos
    if "ticker" in sentimiento_especifico.columns:
        df = df.merge(sentimiento_especifico[["ticker", "sentimiento"]], on="ticker", how="left")
        df = df.rename(columns={"sentimiento": "sentimiento_especifico"})
    else:
        df["sentimiento_especifico"] = None

    # Agregar sentimiento general a todos
    sentimiento_valor = sentimiento_general["sentimiento_general"].iloc[0] if not sentimiento_general.empty else None
    df["sentimiento_general"] = sentimiento_valor

    # Guardar
    os.makedirs("data/processed/", exist_ok=True)
    df.to_parquet("data/processed/features.parquet", index=False)
    print("✅ Features combinados guardados en data/processed/features.parquet")


if __name__ == "__main__":
    combine_features()
