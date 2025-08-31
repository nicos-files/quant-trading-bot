class StrategyAgent:
    def __init__(self, name="StrategyAgent"):
        self.name = name

    def generate_strategy(self, sentiment, indicators, fundamentals, prediction_score):
        """
        Combina los inputs y genera una estrategia de inversión.
        """
        strategy = {}

        # Evaluación básica
        if prediction_score > 0.7 and sentiment == "positivo":
            strategy["acción"] = "comprar"
            strategy["justificación"] = "El modelo predice alta probabilidad de éxito y el sentimiento es positivo."
        elif prediction_score < 0.4 or sentiment == "negativo":
            strategy["acción"] = "evitar"
            strategy["justificación"] = "El riesgo es alto por baja predicción o sentimiento negativo."
        else:
            strategy["acción"] = "mantener"
            strategy["justificación"] = "No hay señales claras, se recomienda esperar."

        # Agregar contexto técnico y fundamental
        strategy["RSI"] = indicators.get("RSI")
        strategy["MACD"] = indicators.get("MACD")
        strategy["SMA"] = indicators.get("SMA")
        strategy["ROE"] = fundamentals.get("ROE")
        strategy["P/E"] = fundamentals.get("PE")

        return strategy