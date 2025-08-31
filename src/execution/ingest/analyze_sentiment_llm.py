

def analyze_sentiment_llm(agent, headlines):
    """
    Usa el SentimentAgent para analizar una lista de titulares.
    Args:
        agent: instancia de GPT4AllAgent
        headlines: lista de strings
    Returns:
        lista de dicts con titular y sentimiento
    """
    results = []
    for h in headlines:
        prompt = f"¿Cuál es el sentimiento del siguiente titular? '{h}' Responde solo con: positivo, negativo o neutral."
        response = agent.generate_reply(prompt, max_tokens=32).lower()
        if "positivo" in response:
            sentiment = "positivo"
        elif "negativo" in response:
            sentiment = "negativo"
        else:
            sentiment = "neutral"
        results.append({"titular": h, "sentimiento": sentiment})
    return results
