import pandas as pd
import joblib
import numpy as np
import matplotlib.pyplot as plt
import os

# Cargar dataset y modelo
df = pd.read_parquet("data/processed/features.parquet")
model = joblib.load("models/xgb_clf_futuro.pkl")

# Filtrar datos válidos
df = df.dropna(subset=["target_regresion_t+1", "target_clasificacion_t+1"])
drop_cols = [
    "ticker", "daily_return", "target_clasificacion", "target_regresion_t+1",
    "target_clasificacion_t+1", "sentimiento_especifico", "sentimiento_general"
]
X = df.drop(columns=drop_cols)

# Predicciones
df["prediccion"] = model.predict(X)

# Simulación de estrategia
df["estrategia_return"] = np.where(df["prediccion"] == 1, df["target_regresion_t+1"], 0)
df["acierto"] = (df["prediccion"] == df["target_clasificacion_t+1"]).astype(int)

# Capital inicial y curva de equity
df["capital"] = (1 + df["estrategia_return"]).cumprod()

# Métricas
retorno_total = df["capital"].iloc[-1] - 1
retorno_promedio = df["estrategia_return"].mean()
tasa_aciertos = df["acierto"].mean()
cantidad_operaciones = df["prediccion"].sum()

# Crear carpeta de simulaciones
os.makedirs("simulations", exist_ok=True)

# Guardar CSV
df[["prediccion", "target_regresion_t+1", "estrategia_return", "capital"]].to_csv("simulations/resultados.csv", index=False)

# Graficar curva de capital
plt.figure(figsize=(10, 5))
plt.plot(df["capital"], label="Estrategia", color="green")
plt.axhline(1, linestyle="--", color="gray", label="Capital inicial")
plt.title("📈 Curva de capital acumulado")
plt.xlabel("Días")
plt.ylabel("Capital")
plt.legend()
plt.tight_layout()
plt.savefig("simulations/equity_curve.png")
plt.close()

# Mostrar resumen
print("\n📊 Resultados de la estrategia:")
print(f"🔹 Retorno total: {retorno_total:.4f}")
print(f"🔹 Retorno promedio por operación: {retorno_promedio:.4f}")
print(f"🔹 Tasa de aciertos: {tasa_aciertos:.2%}")
print(f"🔹 Cantidad de operaciones: {cantidad_operaciones}")
print("✅ Resultados guardados en simulations/")
