"""
Base de testes: SQLite em memória, IA desligada (privacy no_ai) e jobs de
segundo plano executados na hora, para os testes serem determinísticos e
não dependerem de Ollama, Groq nem de threads.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.migrations import upgrade_schema
from app.database import get_db
from app.main import app
from app.services import jobs

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
    Base.metadata.drop_all(bind=engine)
    upgrade_schema(engine)
    yield


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
