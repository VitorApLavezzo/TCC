"""
Tarefas lentas fora da requisição.

Conversa, diagnóstico, diário e avaliação chamam modelos de linguagem que podem
levar mais de um minuto. A requisição devolve na hora um registro "pendente" e
o trabalho segue aqui, numa sessão de banco própria; o painel consulta até o
registro ficar pronto.

A fila de explicações de avisos continua separada e serial
(`explanation_queue.py`): uma conversa não deve esperar atrás de dez avisos.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Optional

from app.config import settings

_executor = ThreadPoolExecutor(max_workers=max(1, settings.AI_JOB_WORKERS), thread_name_prefix="ai-job")

# Teto de trabalhos de uma mesma conta na fila ou rodando, somando todos os
# tipos. O pool tem 2 workers para todos: sem teto, uma conta recém-criada
# enfileirava trinta avaliações e a conversa dos outros esperava atrás delas
# (e cada pergunta podia gastar até seis chamadas a um provedor pago).
MAX_PER_USER = 3
_inflight: Dict[int, int] = {}
_inflight_lock = threading.Lock()


class Busy(Exception):
    """A conta já tem trabalhos demais na fila; a rota responde 429."""


# Testes trocam para execução imediata e para a sessão do banco de teste.
RUN_INLINE = False
session_factory = None


def _session():
    if session_factory is not None:
        return session_factory()
    from app.database import SessionLocal
    return SessionLocal()


def _runner(fn: Callable, *args, **kwargs) -> Callable[[], None]:
    def run():
        db = _session()
        try:
            fn(db, *args, **kwargs)
        except Exception as e:
            print(f"[Jobs] {getattr(fn, '__name__', fn)} falhou: {e}")
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()
    return run


def _counted(run: Callable[[], None], owner_id: Optional[int]) -> Callable[[], None]:
    """Conta o trabalho na cota do dono enquanto ele estiver na fila ou rodando."""
    if owner_id is None:
        return run
    with _inflight_lock:
        if _inflight.get(owner_id, 0) >= MAX_PER_USER:
            raise Busy()
        _inflight[owner_id] = _inflight.get(owner_id, 0) + 1

    def counted():
        try:
            run()
        finally:
            with _inflight_lock:
                _inflight[owner_id] -= 1
                if _inflight[owner_id] <= 0:
                    del _inflight[owner_id]
    return counted


def submit(fn: Callable, *args, owner_id: Optional[int] = None, **kwargs) -> None:
    """Executa `fn(db, *args, **kwargs)` em segundo plano com sessão própria.

    `owner_id` é a conta que pediu (ou dona da máquina): entra na cota dela.
    """
    run = _counted(_runner(fn, *args, **kwargs), owner_id)
    if RUN_INLINE:
        run()
    else:
        _executor.submit(run)


def submit_long(fn: Callable, *args, owner_id: Optional[int] = None, **kwargs) -> None:
    """Como `submit`, numa thread só dela: tarefas de dezenas de minutos (a
    reprodução de dado real) não podem prender um dos poucos workers das
    conversas e diagnósticos."""
    run = _counted(_runner(fn, *args, **kwargs), owner_id)
    if RUN_INLINE:
        run()
    else:
        threading.Thread(target=run, daemon=True, name="long-job").start()
