from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/anomaly_db"
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"

    # Login com Google (OAuth) — vazio desativa o botão no frontend
    GOOGLE_CLIENT_ID: str = ""

    # Fallback em nuvem (API compatível com OpenAI — Groq por padrão)
    # Se CLOUD_LLM_API_KEY estiver vazia, o fallback em nuvem fica desativado
    CLOUD_LLM_BASE_URL: str = "https://api.groq.com/openai/v1"
    CLOUD_LLM_API_KEY: str = ""
    CLOUD_LLM_MODEL: str = "llama-3.3-70b-versatile"

    ANOMALY_SCORE_THRESHOLD: float = -0.15
    MIN_TRAINING_SAMPLES: int = 100
    # 3% de contaminação: menos alarmes falsos que os 5% originais
    ISOLATION_FOREST_CONTAMINATION: float = 0.03
    # Janela de treino (nº de coletas mais recentes) e frequência de retreino
    TRAINING_WINDOW: int = 5000
    RETRAIN_EVERY: int = 30

    class Config:
        env_file = ".env"


settings = Settings()
