"""
Camada única de acesso aos modelos de linguagem.

Toda chamada de IA do sistema — explicação de aviso, conversa, diário, próximo
passo, diagnóstico, avaliação — passa por aqui, por três motivos:

1. Privacidade por máquina: um computador em "somente IA local" nunca tem dados
   enviados a provedores em nuvem; um em "sem IA" não tem dados enviados a
   nenhum modelo, e cada funcionalidade cai na sua análise local.
2. Redação: antes de sair do servidor o texto passa pelo filtro de segredos e,
   quando o destino é a nuvem, também pelo de dados pessoais.
3. Auditoria: cada tentativa fica registrada (provedor, destino, duração, erro)
   e o texto exatamente como foi enviado volta para quem chamou poder guardar.
"""
import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, List, Optional

import httpx

from app.config import settings
from app.core.redaction import redact_for_llm

LOCAL = "local"
CLOUD = "cloud"

PRIVACY_ANY = "any"
PRIVACY_LOCAL_ONLY = "local_only"
PRIVACY_NO_AI = "no_ai"


def _call_ollama(prompt: str, temperature: float = 0.3) -> str:
    """Ollama pela API nativa (sem dependência do SDK da OpenAI)."""
    url = f"{settings.OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    # connect=5s: host do Ollama desligado falha rápido e a cadeia segue
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        return response.json()["response"]


def _call_cloud_llm(prompt: str, temperature: float = 0.3) -> str:
    """API compatível com OpenAI (Groq, OpenRouter...)."""
    url = settings.CLOUD_LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.CLOUD_LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    headers = {"Authorization": f"Bearer {settings.CLOUD_LLM_API_KEY}"}
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def _call_claude_cli(prompt: str, temperature: float = 0.3) -> str:
    """Claude Code CLI em modo headless.

    O prompt vai por stdin (evita limite de tamanho de argumento) e a resposta
    volta em JSON, de onde extraímos o campo "result". Requer o CLI instalado
    na imagem e ~/.claude/.credentials.json montado. A temperatura não é
    configurável pelo CLI.
    """
    cmd = [settings.CLAUDE_CLI_PATH, "-p", "--output-format", "json", "--model", settings.CLAUDE_CLI_MODEL]
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=settings.CLAUDE_CLI_TIMEOUT,
        cwd="/tmp",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude cli retornou {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:300]}")
    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude cli reportou erro: {str(envelope.get('result'))[:300]}")
    return envelope["result"]


@dataclass
class Provider:
    name: str
    destination: str
    call: Callable[[str, float], str]


@dataclass
class Attempt:
    provider: str
    destination: str
    ok: bool
    duration_ms: int
    error: Optional[str] = None


@dataclass
class LLMResult:
    ok: bool
    text: str = ""
    value: Any = None
    provider: Optional[str] = None
    destination: str = "none"
    prompt_sent: str = ""
    attempts: List[Attempt] = field(default_factory=list)
    duration_ms: int = 0

    def attempts_json(self) -> List[dict]:
        return [asdict(a) for a in self.attempts]


def privacy_of(machine) -> str:
    return (getattr(machine, "ai_privacy", None) or PRIVACY_ANY) if machine is not None else PRIVACY_ANY


def provider_chain(privacy: str = PRIVACY_ANY, exclude: Iterable[str] = ()) -> List[Provider]:
    """Provedores na ordem de preferência, já filtrados pela privacidade.

    O Claude CLI vem primeiro porque habilitá-lo é uma escolha explícita; o
    Ollama continua como reserva local; a nuvem compatível com OpenAI por último.
    """
    if privacy == PRIVACY_NO_AI:
        return []
    chain: List[Provider] = []
    if settings.CLAUDE_CLI_ENABLED and privacy == PRIVACY_ANY:
        chain.append(Provider(f"claude-cli/{settings.CLAUDE_CLI_MODEL}", CLOUD, _call_claude_cli))
    chain.append(Provider(f"ollama/{settings.OLLAMA_MODEL}", LOCAL, _call_ollama))
    if settings.CLOUD_LLM_API_KEY and privacy == PRIVACY_ANY:
        chain.append(Provider(f"cloud/{settings.CLOUD_LLM_MODEL}", CLOUD, _call_cloud_llm))
    excluded = set(exclude)
    return [p for p in chain if p.name not in excluded]


def complete(
    prompt: str,
    *,
    privacy: str = PRIVACY_ANY,
    parse: Optional[Callable[[str], Any]] = None,
    exclude: Iterable[str] = (),
    temperature: float = 0.3,
) -> LLMResult:
    """Tenta cada provedor até um responder algo que `parse` aceite.

    `parse` pode levantar exceção para rejeitar uma resposta (JSON inválido,
    números inventados): a rejeição conta como falha daquele provedor e a
    cadeia passa ao próximo.
    """
    started = time.monotonic()
    attempts: List[Attempt] = []
    last_sent = prompt
    for provider in provider_chain(privacy, exclude):
        sent = redact_for_llm(prompt, provider.destination)
        last_sent = sent
        t0 = time.monotonic()
        try:
            raw = provider.call(sent, temperature)
            value = parse(raw) if parse else raw
            attempts.append(Attempt(provider.name, provider.destination, True, int((time.monotonic() - t0) * 1000)))
            return LLMResult(
                ok=True,
                text=raw,
                value=value,
                provider=provider.name,
                destination=provider.destination,
                prompt_sent=sent,
                attempts=attempts,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as e:
            attempts.append(
                Attempt(provider.name, provider.destination, False, int((time.monotonic() - t0) * 1000), str(e)[:300])
            )
            print(f"[LLM] Provedor {provider.name} falhou: {e}")

    return LLMResult(
        ok=False,
        prompt_sent=last_sent,
        attempts=attempts,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def extract_json(raw: str) -> Any:
    """Extrai o JSON da resposta mesmo com texto antes ou depois."""
    starts = [i for i in (raw.find("{"), raw.find("[")) if i != -1]
    if not starts:
        raise ValueError("Nenhum JSON na resposta")
    start = min(starts)
    closer = "}" if raw[start] == "{" else "]"
    end = raw.rfind(closer) + 1
    if end == 0:
        raise ValueError("JSON sem fechamento")
    return json.loads(raw[start:end])
