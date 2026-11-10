from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import Optional

# Valores que já circularam publicamente (código, .env.example, compose):
# quem conhece um deles assina sessão de qualquer conta.
_PUBLISHED_KEYS = {"change-this-in-production", "dev-secret-key-change-in-production"}


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/anomaly_db"
    # Obrigatória e forte: sem padrão, para o servidor não subir assinando
    # sessões com uma chave que está no repositório (start.sh gera uma).
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    # Usuário e senha de um túnel na frente do Ollama (ngrok, proxy); vazios = sem senha
    OLLAMA_USERNAME: str = ""
    OLLAMA_PASSWORD: str = ""
    # False: a nuvem escreve primeiro e o modelo local fica de reserva
    LLM_LOCAL_FIRST: bool = True

    # Login com Google (OAuth) — vazio desativa o botão no frontend
    GOOGLE_CLIENT_ID: str = ""

    # Fallback em nuvem (API compatível com OpenAI); CLOUD_LLM_API_KEY vazia o desativa
    CLOUD_LLM_BASE_URL: str = "https://api.groq.com/openai/v1"
    CLOUD_LLM_API_KEY: str = ""
    CLOUD_LLM_MODEL: str = "llama-3.3-70b-versatile"

    # Claude Code CLI headless (assinatura em ~/.claude); habilitado, é o primeiro provedor da cadeia
    CLAUDE_CLI_ENABLED: bool = False
    CLAUDE_CLI_PATH: str = "claude"
    CLAUDE_CLI_MODEL: str = "sonnet"
    CLAUDE_CLI_TIMEOUT: int = 120

    # Fração (%) do próprio histórico da máquina considerada fora do padrão; o limite é recalculado
    # a cada treino, porque um número fixo não acompanha a escala de score_samples.
    ML_ALERT_PERCENTILE: float = 1.0
    # Quanto do caminho até o limite de alerta a leitura anterior precisa ter andado para confirmar
    # a atual (1,0 exigiria duas leituras de alerta pleno e mataria a revocação).
    ML_CONFIRM_FACTOR: float = 0.5
    # O One-Class SVM precisa concordar com o Isolation Forest para a leitura ser fora do padrão
    ML_SVM_CONFIRM: bool = False
    MIN_TRAINING_SAMPLES: int = 100
    # 3% de contaminação: menos alarmes falsos que 5%
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
    # Este servidor aceita contribuições de outros (atua como hub). Desligado
    # por padrão: só instalações cadastradas em REPUTATION_HUB_KEYS
    # ("instalacao:segredo,outra:segredo") podem contribuir.
    REPUTATION_HUB_ACCEPT: bool = False
    REPUTATION_HUB_KEYS: str = ""
    # Segredo desta instalação ao contribuir para REPUTATION_HUB_URL
    REPUTATION_HUB_KEY: str = ""

    # Energia: valores padrão enquanto o usuário não informa os seus
    DEFAULT_TARIFF_KWH: float = 0.85
    # Fator médio de emissão do Sistema Interligado Nacional (kg CO2 por kWh)
    DEFAULT_CO2_KG_PER_KWH: float = 0.0385

    # Retenção de dados brutos
    METRIC_RETENTION_DAYS: int = 120
    PROCESS_SNAPSHOT_RETENTION_DAYS: int = 60

    # Origens autorizadas a chamar a API pelo navegador, separadas por vírgula. Com "*" as
    # credenciais de origem cruzada ficam desligadas (inválido no CORS); o painel usa Bearer.
    ALLOWED_ORIGINS: str = "*"

    # Limite de tentativas por IP em login, cadastro e pareamento
    RATE_LIMIT_ENABLED: bool = True
    # Redes dos proxies que escrevem o IP real em X-Real-IP (o Nginx do Compose fica em
    # 172.16.0.0/12). De outro endereço o cabeçalho é ignorado, senão cada cliente escolhe o balde.
    TRUSTED_PROXY_CIDRS: str = ""

    # Chave do selo do livro de auditoria, guardada fora do banco. Vazia,
    # deriva da SECRET_KEY — quem só tem acesso ao banco não refaz os selos.
    LEDGER_HMAC_KEY: str = ""

    # Distância (Jensen-Shannon média entre as métricas) a partir da qual o
    # normal aprendido não descreve mais a máquina
    DRIFT_WARN: float = 0.20
    DRIFT_CRITICAL: float = 0.35
    # Quantas leituras recentes entram na comparação com a janela de treino
    DRIFT_RECENT_SAMPLES: int = 300

    # Janela de arrependimento: uma ação automática é anunciada e só acontece
    # depois deste tempo, para a pessoa poder cancelar antes
    PLAYBOOK_UNDO_SECONDS: int = 120
    # Teto de execuções automáticas por playbook por dia (trava de segurança)
    PLAYBOOK_DAILY_LIMIT: int = 10

    # Geradas uma vez com `docker compose exec backend python -m app.services.push`
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_CONTACT_EMAIL: str = ""

    class Config:
        env_file = ".env"

    @field_validator("SECRET_KEY")
    @classmethod
    def _strong_key(cls, v: str) -> str:
        v = v.strip()
        if v in _PUBLISHED_KEYS or len(v) < 32:
            raise ValueError("SECRET_KEY precisa ser um valor aleatório próprio, com pelo menos 32 caracteres "
                             "(gere com: python3 -c 'import secrets; print(secrets.token_urlsafe(48))')")
        return v


settings = Settings()
