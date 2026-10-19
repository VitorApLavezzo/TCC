"""
Base de testes: SQLite em memória, IA desligada (privacy no_ai) e jobs de
segundo plano executados na hora, para os testes serem determinísticos e
não dependerem de Ollama, Groq nem de threads.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.migrations import upgrade_schema
from app.database import get_db
from app.main import app
from app.services import jobs

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


# O SQLite ignora chave estrangeira por padrão; o PostgreSQL de produção não.
# Sem este PRAGMA, um delete na ordem errada passa nos testes e só falha na
# máquina de quem usa — foi assim que a remoção das máquinas efêmeras do
# benchmark quebrou sem nenhum teste acusar.
@event.listens_for(engine, "connect")
def _ativa_chaves_estrangeiras(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
upgrade_schema(engine)

# Jobs rodam na hora, na sessão de teste
jobs.RUN_INLINE = True
jobs.session_factory = TestingSessionLocal


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture()
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def reset_db():
    from app.database import Base
    from app.core import ratelimit
    Base.metadata.drop_all(bind=engine)
    upgrade_schema(engine)
    # O limite de tentativas conta por IP, e a suíte inteira vem do mesmo
    # cliente de teste: sem zerar, o terceiro teste que cria conta já bateria
    # no teto. O teste do próprio limite liga e controla isso por conta.
    ratelimit.reset()
    yield


@pytest.fixture(autouse=True)
def modelos_isolados(tmp_path, monkeypatch):
    """Cada teste grava e lê modelos num diretório próprio e vazio.

    O diretório padrão de modelos, no container, é o volume de produção — e
    `docker compose exec backend python -m pytest` é o comando documentado. Os
    testes treinam para as máquinas 1 e 2 e apagam o modelo ao apagar a
    máquina efêmera: numa instalação nova, eram os modelos de verdade. E sem
    um diretório por teste, a máquina 1 de um teste carregava o modelo da
    máquina 1 do anterior.
    """
    from app.services import ml_service
    diretorio = tmp_path / "ml_models"
    diretorio.mkdir()
    monkeypatch.setattr(ml_service, "MODEL_DIR", str(diretorio))
    ml_service._cache.clear()
    yield
    ml_service._cache.clear()


@pytest.fixture()
def client():
    return TestClient(app)


TEST_USER = {"email": "t@t.com", "username": "tester", "password": "testpass123"}


@pytest.fixture()
def auth(client):
    client.post("/api/auth/register", json=TEST_USER)
    res = client.post("/api/auth/login", data={"username": TEST_USER["username"], "password": TEST_USER["password"]})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def machine(client, auth):
    res = client.post("/api/machines", json={"name": "PC Teste", "hostname": "HOST", "os_type": "Windows"},
                      headers=auth)
    return res.json()
