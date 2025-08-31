class UserAgent:
    def __init__(self, name="UserAgent"):
        self.name = name

    def present_recommendation(self, strategy, ticker):
        """
        Genera un mensaje claro para el usuario basado en la estrategia.
        """
        accion = strategy["acción"]
        justificacion = strategy["justificación"]
        rsi = strategy.get("RSI")
        macd = strategy.get("MACD")
        roe = strategy.get("ROE")
        pe = strategy.get("P/E")

        message = f"""
📈 Recomendación para {ticker}:
➡️ Acción sugerida: {accion.upper()}
🧠 Justificación: {justificacion}

🔍 Indicadores técnicos:
- RSI: {rsi}
- MACD: {macd}

📊 Datos fundamentales:
- ROE: {roe}
- P/E: {pe}
"""
        return message.strip()