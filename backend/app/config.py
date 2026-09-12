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

    # Claude Code CLI em modo headless (usa a assinatura autenticada em ~/.claude)
    # Quando habilitado, vira o primeiro provedor da cadeia de explicações.
    CLAUDE_CLI_ENABLED: bool = False
    CLAUDE_CLI_PATH: str = "claude"
    CLAUDE_CLI_MODEL: str = "sonnet"
    CLAUDE_CLI_TIMEOUT: int = 120

    # Que fração do próprio histórico da máquina o modelo consideraria fora do
    # padrão (em %). O limite é recalculado a cada treino a partir dessa fração,
    # em vez de um número fixo: o antigo ANOMALY_SCORE_THRESHOLD=-0.15 era
    # comparado com score_samples, que fica perto de -0.45 em leituras normais —
    # na prática toda leitura era "anômala".
    ML_ALERT_PERCENTILE: float = 0.5
    MIN_TRAINING_SAMPLES: int = 100
    # 3% de contaminação: menos alarmes falsos que os 5% originais
    ISOLATION_FOREST_CONTAMINATION: float = 0.03
    # Janela de treino (nº de coletas mais recentes) e frequência de retreino
    TRAINING_WINDOW: int = 5000
    RETRAIN_EVERY: int = 30

    # Fuso usado para "hora do dia" enquanto o agente não informou o da máquina
    # (-180 = horário de Brasília)
    DEFAULT_TZ_OFFSET_MINUTES: int = -180

    # Tarefas de IA em segundo plano (conversa, diagnóstico, diário, avaliação)
    AI_JOB_WORKERS: int = 2

    # Agendador de rotinas (verificação de resolução, previsões, diário...)
    SCHEDULER_ENABLED: bool = True

    # Endereço do painel usado nos links enviados por Telegram e e-mail
    PUBLIC_BASE_URL: str = ""

    # Telegram (vazio desativa). O bot usa long polling: funciona atrás de NAT,
    # sem precisar expor o servidor à internet.
    TELEGRAM_BOT_TOKEN: str = ""

    # E-mail (vazio desativa)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_TLS: bool = True

    # Reputação de executáveis
    VIRUSTOTAL_API_KEY: str = ""
    # Outro servidor AnomalyDetect que agrega reputação anônima entre instalações
    REPUTATION_HUB_URL: str = ""
    # Este servidor aceita contribuições anônimas de outros (atua como hub)
    REPUTATION_HUB_ACCEPT: bool = True

    # Energia: valores padrão enquanto o usuário não informa os seus
    DEFAULT_TARIFF_KWH: float = 0.85
    # Fator médio de emissão do Sistema Interligado Nacional (kg CO2 por kWh)
    DEFAULT_CO2_KG_PER_KWH: float = 0.0385

    # Retenção de dados brutos
    METRIC_RETENTION_DAYS: int = 120
    PROCESS_SNAPSHOT_RETENTION_DAYS: int = 21

    class Config:
        env_file = ".env"


settings = Settings()
