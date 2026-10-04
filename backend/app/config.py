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
    # Quanto do caminho até o limite de alerta a leitura anterior precisa ter
    # andado para confirmar a atual. 1,0 exigiria duas leituras de alerta pleno
    # (mata a revocação); 0,0 volta ao comportamento antigo de comparar com zero.
    ML_CONFIRM_FACTOR: float = 0.5
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

    # Origens autorizadas a chamar a API pelo navegador, separadas por vírgula
    # ("*" libera qualquer uma, e nesse caso as credenciais de origem cruzada
    # ficam desligadas — a combinação "*" + credenciais é inválida no padrão
    # CORS e os navegadores recusam). O painel autentica por Bearer no
    # cabeçalho, não por cookie, então nada se perde com isso.
    ALLOWED_ORIGINS: str = "*"

    # Limite de tentativas por IP em login, cadastro e pareamento
    RATE_LIMIT_ENABLED: bool = True

    # --- Deriva do modelo -------------------------------------------------
    # Distância (Jensen-Shannon média entre as métricas) a partir da qual o
    # normal aprendido não descreve mais a máquina
    DRIFT_WARN: float = 0.20
    DRIFT_CRITICAL: float = 0.35
    # Quantas leituras recentes entram na comparação com a janela de treino
    DRIFT_RECENT_SAMPLES: int = 300

    # --- Playbooks (automação com autonomia graduada) ---------------------
    # Janela de arrependimento: uma ação automática é anunciada e só acontece
    # depois deste tempo, para a pessoa poder cancelar antes
    PLAYBOOK_UNDO_SECONDS: int = 120
    # Teto de execuções automáticas por playbook por dia (trava de segurança)
    PLAYBOOK_DAILY_LIMIT: int = 10

    # --- Notificação no celular (Web Push) --------------------------------
    # Geradas uma vez com `docker compose exec backend python -m app.services.push`
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_CONTACT_EMAIL: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
