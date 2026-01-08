Este proyecto construye un pipeline modular para análisis financiero basado en precios, fundamentales, sentimiento y estrategia.

---

## 🧩 Arquitectura por capas

### 1. Ingesta (`data/raw/`)
Recolecta datos crudos desde APIs y scrapers:

- `ingest_prices.py` → precios históricos
- `ingest_fundamentals.py` → ratios financieros
- `ingest_sentiment.py` → titulares y posts
- `investing_scraper.py` → datos desde Investing
- `alfaV_fetcher.py` → precios desde Alpha Vantage

---

### 2. Procesamiento (`data/processed/`)
Transforma y limpia los datos:

- `process_prices.py` → limpieza de precios
- `process_indicators.py` → cálculo de indicadores técnicos
- `process_fundamentals.py` → estructuración de ratios
- `process_sentiment.py` → análisis de sentimiento

---

### 3. Feature Engineering (`features.parquet`)
Combina todos los datos en un solo dataset por ticker:

- `feature_engineering.py` → une indicadores, fundamentales y sentimiento

---

### 4. Modelado y estrategia (`data/results/`)
Entrena modelos, genera señales y evalúa decisiones:

- `train_model.py` → entrenamiento
- `predict.py` → predicciones
- `strategy_agent.py` → decisiones
- `backtest.py` → simulación histórica

---

## ✅ Orden de ejecución sugerido

1. `ingest_prices.py`
2. `ingest_fundamentals.py`
3. `ingest_sentiment.py`
4. `process_prices.py`
5. `process_fundamentals.py`
6. `process_sentiment.py`
7. `process_indicators.py`
8. `feature_engineering.py`
9. `train_model.py`
10. `strategy_agent.py`

---

## 📦 Estructura de carpetas

