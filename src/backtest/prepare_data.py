import pandas as pd
import numpy as np
import joblib

def prepare_data(features_path, model_path, clip_ret, stop_loss, take_profit):
    df = pd.read_parquet(features_path)

    # Validar targets obligatorios
    df = df.dropna(subset=["target_regresion_t+1", "target_clasificacion_t+1"]).copy()

    # Validar índice temporal
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("El índice del dataset no es de tipo fecha. Se esperaba un DatetimeIndex.")
    df.index = df.index.normalize()

    # Validar columna ticker
    if "ticker" not in df.columns:
        raise ValueError("El dataset no tiene columna 'ticker'.")
    df["ticker"] = df["ticker"].astype(str)

    # Eliminar duplicados y setear índice compuesto
    df = df.reset_index()
    df = df.rename(columns={df.columns[0]: "date"})
    df = df.sort_values(["date", "ticker"])
    df = df.drop_duplicates(subset=["date", "ticker"], keep="last")
    df = df.set_index(["date", "ticker"]).sort_index()

    # Preparar features para el modelo
    drop_cols = [
        "ticker", "daily_return", "target_clasificacion",
        "target_regresion_t+1", "target_clasificacion_t+1",
        "sentimiento_especifico", "sentimiento_general"
    ]
    X = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")

    # Cargar modelo y generar predicciones
    model = joblib.load(model_path)
    expected_features = model.get_booster().feature_names
    missing = [col for col in expected_features if col not in X.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas por el modelo: {missing}")

    for col in X.columns:
        if X[col].dtype == "object":
            X[col] = X[col].astype("category")

    df["prediccion"] = model.predict(X)
    if hasattr(model, "predict_proba"):
        df["proba"] = model.predict_proba(X)[:, 1]

    # Retorno ajustado: clip de outliers y SL/TP
    df["ret_adj"] = (
        df["target_regresion_t+1"]
        .clip(lower=-clip_ret, upper=clip_ret)
        .clip(lower=-stop_loss, upper=take_profit)
    )

    return df
