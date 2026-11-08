"""Base de testes: SQLite em memória, IA desligada e jobs executados na hora, sem Ollama, Groq nem threads."""
import os
import secrets

# A chave de sessão é obrigatória e precisa ser forte: config.py recusa as
# públicas e as curtas. Cada execução da suíte usa uma chave nova.
os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(48))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.migrations import upgrade_schema
from app.database import get_db
from app.main import app
from app.services import jobs

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


# O SQLite ignora chave estrangeira por padrão e o PostgreSQL de produção não:
# sem o PRAGMA, um delete na ordem errada passaria nos testes.
@event.listens_for(engine, "connect")
def _enable_foreign_keys(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
upgrade_schema(engine)

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
    # O limite de tentativas conta por IP e a suíte inteira vem do mesmo cliente.
    ratelimit.reset()
    yield


@pytest.fixture(autouse=True)
def isolated_models(tmp_path, monkeypatch):
    """Cada teste usa um diretório de modelos próprio e vazio; o padrão no container é o volume de produção."""
    from app.services import ml_service
    models_dir = tmp_path / "ml_models"
    models_dir.mkdir()
    monkeypatch.setattr(ml_service, "MODEL_DIR", str(models_dir))
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
