from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/anomaly_db"
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"

    ANOMALY_SCORE_THRESHOLD: float = -0.15
    MIN_TRAINING_SAMPLES: int = 100
    ISOLATION_FOREST_CONTAMINATION: float = 0.05

    class Config:
        env_file = ".env"


settings = Settings()
