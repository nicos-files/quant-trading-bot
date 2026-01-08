import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    classification_report, confusion_matrix,
    mean_squared_error, r2_score
)
import matplotlib.pyplot as plt
import numpy as np
import joblib
import os
import sys
sys.path.append("C:/Users/NAguilar/Proyectos/AutoGen/quant-trading-bot")
from src.utils.llm_logger import log_llm_interaction
from datetime import datetime
import time
import argparse
from pathlib import Path
from src.utils.execution_context import get_execution_date

def select_relevant_features(df, target_col, threshold_var=1e-5, max_null_pct=0.3):
    """
    Selecciona features numéricos con suficiente varianza y pocos nulos.
    Args:
        df (DataFrame): Dataset completo
        target_col (str): Columna objetivo
        threshold_var (float): Varianza mínima
        max_null_pct (float): Máximo porcentaje de nulos permitido
    Returns:
        List[str]: Lista de columnas seleccionadas
    """
    numeric = df.select_dtypes(include="number")
    stds = numeric.std()
    null_pct = numeric.isnull().mean()

    selected = [
        col for col in numeric.columns
        if stds[col] > threshold_var and null_pct[col] < max_null_pct and col != target_col
    ]
    return selected



def parse_args():
    parser = argparse.ArgumentParser(description="Entrena modelos usando features diarios.")
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    return parser.parse_args()

args = parse_args()

if args.date:
    date = get_execution_date(args.date)
    print(f"[INFO] Usando fecha manual: {args.date}")
else:
    # Buscar el último folder con features consolidados
    base_path = Path("data/processed/features")
    all_dates = sorted(base_path.glob("*/*/*"), reverse=True)
    found = False
    for d in all_dates:
        candidate = d / "features.parquet"
        if candidate.exists():
            date = datetime.strptime(f"{d.parts[-3]}-{d.parts[-2]}-{d.parts[-1]}", "%Y-%m-%d")
            print(f"[INFO] Usando última fecha disponible: {date.strftime('%Y-%m-%d')}")
            found = True
            break
    if not found:
        raise FileNotFoundError("No se encontró ningún archivo consolidado de features.")

features_path = Path("data/processed/features") / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}" / "features.parquet"

if not features_path.exists():
    raise FileNotFoundError(f"No se encontró el archivo de features: {features_path}")

df = pd.read_parquet(features_path)


# Crear carpeta de modelos
os.makedirs("models", exist_ok=True)

# Columnas a excluir
drop_cols = [
    "ticker",
    "timestamp_proceso",
    "timestamp_ejecucion",
    "target_clasificacion",
    "target_clasificacion_t+1",
    "daily_return",
    "target_regresion_t+1",
    "sentimiento_especifico",
    "sentimiento_general"
]




X_base = df.drop(columns=drop_cols)

# 🔹 Clasificación
targets_clf = {
    "actual": "target_clasificacion",
    "futuro": "target_clasificacion_t+1"
}

for label, target_col in targets_clf.items():
    print(f"\n Clasificación: {target_col}")
    start = time.time()
    log_entry = {
        "timestamp": datetime.now(),
        "module": "train_model",
        "tipo": "clasificacion",
        "target": target_col
    }

    try:
        df_model = df.dropna(subset=[target_col])
        df_model = df_model.drop(columns=[col for col in drop_cols if col in df_model.columns])
        selected_features = select_relevant_features(df_model, target_col)
        log_entry["selected_features"] = selected_features
        X = df_model[selected_features].fillna(0)

        y = df_model[target_col]

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)

        model = xgb.XGBClassifier(use_label_encoder=False, eval_metric="logloss", random_state=42)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        print(f"\n Reporte de clasificación ({label}):")
        print(classification_report(y_test, y_pred))
        print(" Matriz de confusión:")
        print(confusion_matrix(y_test, y_pred))

        model_path = f"models/xgb_clf_{label}.pkl"
        joblib.dump(model, model_path)
        print(f" Modelo guardado: {model_path}")

        importance = model.feature_importances_
        features = X.columns
        sorted_idx = np.argsort(importance)[::-1]

        plt.figure(figsize=(10, 6))
        plt.barh(features[sorted_idx][:20][::-1], importance[sorted_idx][:20][::-1], color="skyblue")
        plt.xlabel("Importancia")
        plt.title(f" Top 20 Features ({label} - Clasificación)")
        plt.tight_layout()
        plt.savefig(f"models/feature_importance_clf_{label}.png")
        plt.close()

        duration = time.time() - start
        log_entry.update({
            "status": "ok",
            "duration_sec": round(duration, 2),
            "accuracy": float((y_pred == y_test).mean()),
            "modelo_path": model_path
        })

    except Exception as e:
        log_entry.update({
            "status": "error",
            "error_msg": str(e)
        })

    log_llm_interaction(log_entry, log_name="train_model")

# 🔹 Regresión
targets_reg = {
    "actual": "daily_return",
    "futuro": "target_regresion_t+1"
}

for label, target_col in targets_reg.items():
    print(f"\n Regresión: {target_col}")
    start = time.time()
    log_entry = {
        "timestamp": datetime.now(),
        "module": "train_model",
        "tipo": "regresion",
        "target": target_col
    }

    try:
        df_model = df.dropna(subset=[target_col])
        X = df_model.drop(columns=drop_cols)
        y = df_model[target_col]

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)

        model = xgb.XGBRegressor(objective="reg:squarederror", n_estimators=100, random_state=42)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        r2 = r2_score(y_test, y_pred)

        print(f"\n Reporte de regresión ({label}):")
        print(f" RMSE: {rmse:.5f}")
        print(f" R² Score: {r2:.5f}")

        model_path = f"models/xgb_reg_{label}.pkl"
        joblib.dump(model, model_path)
        print(f" Modelo guardado: {model_path}")

        importance = model.feature_importances_
        features = X.columns
        sorted_idx = np.argsort(importance)[::-1]

        plt.figure(figsize=(10, 6))
        plt.barh(features[sorted_idx][:20][::-1], importance[sorted_idx][:20][::-1], color="salmon")
        plt.xlabel("Importancia")
        plt.title(f" Top 20 Features ({label} - Regresión)")
        plt.tight_layout()
        plt.savefig(f"models/feature_importance_reg_{label}.png")
        plt.close()

        duration = time.time() - start
        log_entry.update({
            "status": "ok",
            "duration_sec": round(duration, 2),
            "rmse": round(rmse, 5),
            "r2_score": round(r2, 5),
            "modelo_path": model_path,
            "selected_features": selected_features 
        })

    except Exception as e:
        log_entry.update({
            "status": "error",
            "error_msg": str(e)
        })

    log_llm_interaction(log_entry, log_name="train_model")

