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
from typing import Callable

from app.config import settings

_executor = ThreadPoolExecutor(max_workers=max(1, settings.AI_JOB_WORKERS), thread_name_prefix="ai-job")

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


def submit(fn: Callable, *args, **kwargs) -> None:
    """Executa `fn(db, *args, **kwargs)` em segundo plano com sessão própria."""
    run = _runner(fn, *args, **kwargs)
    if RUN_INLINE:
        run()
    else:
        _executor.submit(run)


def submit_long(fn: Callable, *args, **kwargs) -> None:
    """Como `submit`, numa thread só dela: tarefas de dezenas de minutos (a
    reprodução de dado real) não podem prender um dos poucos workers das
    conversas e diagnósticos."""
    run = _runner(fn, *args, **kwargs)
    if RUN_INLINE:
        run()
    else:
        threading.Thread(target=run, daemon=True, name="long-job").start()
