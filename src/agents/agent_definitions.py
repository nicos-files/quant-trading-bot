# src/agents/agent_definitions.py
from agents.llm_wrappers.gpt4all_agent import GPT4AllAgent
from agents.strategy_agent import StrategyAgent
from agents.user_agent import UserAgent

MODEL_NAME = "mistral-7b-instruct-v0.1.Q4_0"
MODEL_PATH = "models/"

# 🧠 Agente de sentimiento (único con LLM)
sentiment_agent = GPT4AllAgent(
    name="SentimentAgent",
    model_path=MODEL_PATH,
    model_name=MODEL_NAME,
    system_message=(
        "Sos un agente especializado en evaluar el sentimiento del mercado. "
        "Analizás titulares, redes sociales y eventos políticos para determinar "
        "cómo podrían afectar los precios de activos financieros."
    )
)

# 📊 Módulo de datos de mercado (no es agente LLM)
# Se define en src/features/technical_indicators.py

# 📈 Módulo de análisis fundamental (no es agente LLM)
# Se define en src/features/fundamental_analysis.py

# 🧪 Módulo de predicción ML (no es agente LLM)
# Se define en src/models/predictor.py

# 🧠 Agente estratega (lógica pura, sin LLM)
strategy_agent = StrategyAgent(name="StrategyAgent")

# 🧑‍💼 Agente usuario (presentación, sin LLM)
user_agent = UserAgent(name="UserAgent")


## Agente analista
#analyst = GPT4AllAgent(
#    name="AnalystAgent",
#    model_path=MODEL_PATH,
#    model_name=MODEL_NAME,
#    system_message=(
#        "Sos un analista financiero experto en acciones y bonos. "
#        "Tu tarea es interpretar datos económicos, técnicos y fundamentales "
#        "para detectar oportunidades de inversión."
#    )
#)
#
## Agente de sentimiento
#sentiment = GPT4AllAgent(
#    name="SentimentAgent",
#    model_path=MODEL_PATH,
#    model_name=MODEL_NAME,
#    system_message=(
#        "Sos un agente especializado en evaluar el sentimiento del mercado. "
#        "Analizás titulares, redes sociales y eventos políticos para determinar "
#        "cómo podrían afectar los precios de activos financieros."
#    )
#)
#
## Agente estratega
#strategist = GPT4AllAgent(
#    name="StrategyAgent",
#    model_path=MODEL_PATH,
#    model_name=MODEL_NAME,
#    system_message=(
#        "Sos un estratega de inversión. Tu rol es combinar los análisis técnicos y sentimentales "
#        "para proponer estrategias concretas de entrada, salida y gestión de riesgo."
#    )
#)
#
## Agente usuario
#user_agent = GPT4AllAgent(
#    name="UserAgent",
#    model_path=MODEL_PATH,
#    model_name=MODEL_NAME,
#    system_message=(
#        "Sos el agente que interactúa con el usuario. Tu tarea es presentar recomendaciones "
#        "de forma clara, resumida y orientada a la acción."
#    )
#)
