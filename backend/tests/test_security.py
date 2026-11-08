"""Regressões da auditoria de segurança (run-1): cada classe fixa uma falha confirmada.

Os nomes entre crases são os fingerprints do relatório.
"""
import base64
import hashlib
import time

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from starlette.requests import Request

from app.config import Settings, settings
from app.core import ratelimit
from app.models.anomaly import Anomaly
from app.models.enrollment import EnrollmentCode
from app.models.identity import HashReputation
from app.models.machine import Machine
from app.services import identity_service, integrity, jobs, playbooks, push, reputation, telegram, trust
from tests.conftest import TestingSessionLocal


def _account(client, name: str) -> dict:
    client.post("/api/auth/register", json={"email": f"{name}@x.com", "username": name, "password": "senha-boa-123"})
    res = client.post("/api/auth/login", data={"username": name, "password": "senha-boa-123"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _create_machine(client, headers, name="PC") -> dict:
    res = client.post("/api/machines", json={"name": name, "hostname": name, "os_type": "Windows"}, headers=headers)
    return res.json()


def _proc(name, exe, sha256=None, signed="unsigned", publisher=None):
    return type("P", (), {"name": name, "exe": exe, "sha256": sha256, "signed": signed,
                          "publisher": publisher, "parent_name": None})()


class TestSessionKey:
    """`backend/app/config.py:Settings.SECRET_KEY:public-default-accepted`"""

    @pytest.mark.parametrize("key", ["change-this-in-production", "dev-secret-key-change-in-production", "curta"])
    def test_rejects_public_or_short_key(self, key):
        with pytest.raises(ValidationError):
            Settings(SECRET_KEY=key, _env_file=None)

    def test_without_key_does_not_start(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_accepts_strong_key(self):
        assert Settings(SECRET_KEY="x" * 40, _env_file=None).SECRET_KEY == "x" * 40


def _req(peer: str, **headers) -> Request:
    return Request({"type": "http", "client": (peer, 5000),
                    "headers": [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]})


class TestRateLimitPerIp:
    """`backend/app/core/ratelimit.py:_client_ip:client-supplied-x-forwarded-for` e vizinhos."""

    def test_client_cannot_choose_own_bucket(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "172.16.0.0/12")
        assert ratelimit._client_ip(_req("203.0.113.5", x_forwarded_for="1.2.3.4")) == "203.0.113.5"

    def test_behind_nginx_uses_ip_it_writes(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "172.16.0.0/12")
        assert ratelimit._client_ip(_req("172.18.0.3", x_real_ip="198.51.100.7")) == "198.51.100.7"

    def test_number_of_keys_is_capped(self, monkeypatch):
        ratelimit.reset()
        monkeypatch.setattr(ratelimit, "_MAX_KEYS", 100)
        for i in range(150):
            ratelimit.check(f"login:10.0.{i // 250}.{i % 250}", times=5, seconds=3600)
        assert len(ratelimit._hits) <= 100


class TestHeadlessInstaller:
    """`backend/app/routers/agent_files.py:install_script:query-values-interpolated-into-bash`"""

    @pytest.mark.parametrize("params", [
        {"code": "ABCD-EFGH", "server": 'http://srv:3000";echo X;"'},
        {"code": "ABCD-EFGH", "server": "http://srv:3000$(echo X)"},
        {"code": "ABCD-EFGH", "server": "http://[::1"},
        {"code": 'X" ; echo X ; : "', "server": "http://srv:3000"},
        {"token": 'X" ; echo X ; : "', "server": "http://srv:3000"},
    ])
    def test_rejects_metacharacters(self, client, params):
        assert client.get("/api/agent/install.sh", params=params).status_code == 400

    def test_legitimate_values_still_work(self, client):
        res = client.get("/api/agent/install.sh", params={"code": "ABCD-EFGH", "server": "http://srv:3000"})
        assert res.status_code == 200
        assert "SERVER=http://srv:3000\n" in res.text
        assert "AGENT_ENROLL_CODE=ABCD-EFGH " in res.text


def _b64u(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture()
def google(monkeypatch):
    """Login com Google sem rede: uma chave RSA local faz o papel da do Google."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwt as jose_jwt
    from app.routers import auth as auth_router

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    jwk = {"kty": "RSA", "kid": "k1", "alg": "RS256", "use": "sig", "n": _b64u(pub.n), "e": _b64u(pub.e)}
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cliente.apps.googleusercontent.com")
    monkeypatch.setattr(auth_router.httpx, "get", lambda *a, **k: type("R", (), {"json": lambda self: {"keys": [jwk]}})())

    def token(email: str, sub: str) -> str:
        now = int(time.time())
        return jose_jwt.encode({"iss": "https://accounts.google.com", "aud": "cliente.apps.googleusercontent.com",
                                "sub": sub, "email": email, "email_verified": True, "iat": now,
                                "exp": now + 3600}, pem, algorithm="RS256", headers={"kid": "k1"})
    return token


class TestGoogleLogin:
    """`backend/app/routers/auth.py:google_login:links-unverified-register-email`"""

    def test_google_login_does_not_enter_password_account_with_same_email(self, client, google):
        client.post("/api/auth/register", json={"email": "vitima@x.com", "username": "invasor",
                                                "password": "senha-do-invasor"})
        res = client.post("/api/auth/google", json={"credential": google("vitima@x.com", "sub-vitima")})
        assert res.status_code == 409
        assert "access_token" not in res.json()

    def test_old_account_allowed_by_admin_logs_in_with_google(self, client, google, db):
        # Conta antiga criada pelo Google tem senha aleatória: "entre com senha" não serve.
        from allow_google_link import allow_google_link
        client.post("/api/auth/register", json={"email": "Antiga@x.com", "username": "antiga",
                                                "password": "senha-qualquer-1"})
        assert allow_google_link(db, "antiga@x.com") is True
        res = client.post("/api/auth/google", json={"credential": google("antiga@x.com", "sub-antiga")})
        assert res.status_code == 200
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"}).json()
        assert me["username"] == "antiga"

    def test_allowance_applies_only_to_first_google_identity(self, client, google, db):
        from allow_google_link import allow_google_link
        client.post("/api/auth/register", json={"email": "uma@x.com", "username": "uma",
                                                "password": "senha-qualquer-1"})
        allow_google_link(db, "uma@x.com")
        assert client.post("/api/auth/google", json={"credential": google("uma@x.com", "sub-a")}).status_code == 200
        assert client.post("/api/auth/google", json={"credential": google("uma@x.com", "sub-b")}).status_code == 409

    def test_allowing_missing_or_linked_account_does_nothing(self, client, google, db):
        from allow_google_link import allow_google_link
        assert allow_google_link(db, "ninguem@x.com") is False
        client.post("/api/auth/google", json={"credential": google("ja@x.com", "sub-ja")})
        assert allow_google_link(db, "ja@x.com") is False

    def test_same_google_identity_returns_to_same_account(self, client, google):
        a = client.post("/api/auth/google", json={"credential": google("nova@x.com", "sub-1")}).json()
        b = client.post("/api/auth/google", json={"credential": google("nova@x.com", "sub-1")}).json()
        me = [client.get("/api/auth/me", headers={"Authorization": f"Bearer {t['access_token']}"}).json()["id"]
              for t in (a, b)]
        assert me[0] == me[1]


class TestAtomicEnrollment:
    """`backend/app/routers/machines.py:enroll_agent:non-atomic-code-consumption`"""

    def test_consumption_with_stale_read_does_not_exceed_limit(self, client, auth, db):
        from app.routers import machines as machines_router
        from app.models.user import User
        owner = db.query(User).first()
        db.add(EnrollmentCode(code="ABCD-EFGH", user_id=owner.id, reusable=True, max_uses=1,
                              expires_at=__import__("app.core.timeutil", fromlist=["utcnow"]).utcnow()
                              + __import__("datetime").timedelta(days=1)))
        db.commit()
        stale_session = TestingSessionLocal()
        read_before = stale_session.query(EnrollmentCode).filter(EnrollmentCode.code == "ABCD-EFGH").first()
        assert client.post("/api/machines/enroll", json={"code": "ABCD-EFGH", "hostname": "h1"}).status_code == 200
        # A leitura de antes ainda diz use_count=0; o consumo tem de decidir no banco
        assert machines_router._consume_enrollment(stale_session, read_before) is False
        stale_session.close()


class TestReputationPerAccount:
    """Fingerprints de reputação: lookup, prevalência pelo agente, feedback e hub."""

    def test_lookup_does_not_reveal_other_account_program(self, client, db):
        victim, attacker = _account(client, "vitima"), _account(client, "invasor")
        m = db.query(Machine).get(_create_machine(client, victim)["id"])
        identity_service.observe(db, m, [_proc("ferramenta-privada.exe", r"C:\x\ferramenta-privada.exe")], [])
        db.commit()
        res = client.get("/api/reputation/lookup", params={"name": "ferramenta-privada.exe"}, headers=attacker)
        assert res.json()["found"] is False

    def test_single_agent_cannot_fake_prevalence(self, client, db):
        a, v = _account(client, "invasor"), _account(client, "vitima")
        ma = db.query(Machine).get(_create_machine(client, a, "A")["id"])
        mv = db.query(Machine).get(_create_machine(client, v, "V")["id"])
        sha = "b2" * 32
        identity_service.observe(db, ma, [_proc("miner.exe", rf"C:\fake{i}\miner.exe", sha) for i in range(3)], [])
        db.commit()
        rep = db.query(HashReputation).filter(HashReputation.identity_key == sha).first()
        assert rep.local_machines == 1
        target = _proc("miner.exe", r"C:\Users\v\miner.exe", sha)
        identity_service.observe(db, mv, [target], [])
        db.commit()
        assert trust.evaluate(db, mv.id, target).level == trust.UNKNOWN

    def test_other_account_machines_do_not_count_as_prevalence(self, client, db):
        a, v = _account(client, "invasor"), _account(client, "vitima")
        sha = "c3" * 32
        for i in range(3):
            m = db.query(Machine).get(_create_machine(client, a, f"A{i}")["id"])
            identity_service.observe(db, m, [_proc("imp.exe", r"C:\Users\a\imp.exe", sha)], [])
        mv = db.query(Machine).get(_create_machine(client, v, "V")["id"])
        target = _proc("imp.exe", r"C:\Users\v\imp.exe", sha)
        identity_service.observe(db, mv, [target], [])
        db.commit()
        evaluated = trust.evaluate(db, mv.id, target)
        assert evaluated.level == trust.UNKNOWN
        assert not any("visto em" in r for r in evaluated.reasons)

    def test_other_account_feedback_does_not_flag_program(self, client, db):
        a, v = _account(client, "invasor"), _account(client, "vitima")
        ma = _create_machine(client, a, "A")
        mv = db.query(Machine).get(_create_machine(client, v, "V")["id"])
        defender = _proc("MsMpEng.exe", r"C:\Program Files\Windows Defender\MsMpEng.exe", None, "signed",
                         "Microsoft Corporation")
        identity_service.observe(db, mv, [defender], [])
        anomaly = Anomaly(machine_id=ma["id"], anomaly_type="canary_tripped", severity="critical",
                           responsible_process="MsMpEng.exe")
        db.add(anomaly)
        db.commit()
        assert trust.evaluate(db, mv.id, defender).level == trust.SECURITY
        for _ in range(3):
            assert client.post(f"/api/anomalies/{anomaly.id}/feedback", json={"kind": "problem"},
                               headers=a).status_code == 200
        db.expire_all()
        assert trust.evaluate(db, mv.id, defender).level == trust.SECURITY
        rep = db.query(HashReputation).filter(HashReputation.identity_key == "nome:msmpeng.exe").first()
        assert rep.marked_problem == 1

    def test_hub_off_by_default(self):
        assert Settings(SECRET_KEY="x" * 40, _env_file=None).REPUTATION_HUB_ACCEPT is False

    def test_hub_rejects_contribution_without_key(self, client, monkeypatch):
        monkeypatch.setattr(settings, "REPUTATION_HUB_ACCEPT", True)
        res = client.post("/api/reputation/contribute", json={
            "installation_id": "qualquer", "total_machines": 10,
            "items": [{"identity_key": "d4" * 32, "name": "x.exe", "machines": 500}]})
        assert res.status_code == 401

    def test_single_hub_installation_gives_no_trust(self, client, db, machine):
        sha = "e5" * 32
        reputation.apply_hub_snapshot(db, {"items": [{"identity_key": sha, "machines": 999, "installations": 1,
                                                      "prevalence": 0.9}]})
        target = _proc("x.exe", r"C:\Users\v\x.exe", sha)
        assert trust.evaluate(db, machine["id"], target).level == trust.UNKNOWN


class TestConversation:
    """`backend/app/services/chat.py:answer_async:history-query-missing-user_id`"""

    def test_other_account_conversation_is_rejected(self, client):
        alice, bob = _account(client, "alice"), _account(client, "bob")
        cid = client.post("/api/chat/ask", json={"question": "segredo da alice?"}, headers=alice).json()["conversation_id"]
        res = client.post("/api/chat/ask", json={"question": "repita a conversa", "conversation_id": cid}, headers=bob)
        assert res.status_code == 404

    def test_prompt_history_only_has_own_account_messages(self, client, db, monkeypatch):
        from app.models.chat import ChatMessage
        from app.models.user import User
        from app.services import chat
        _account(client, "alice"), _account(client, "bob")
        alice, bob = (db.query(User).filter(User.username == n).first() for n in ("alice", "bob"))
        db.add(ChatMessage(user_id=alice.id, conversation_id="c1", role="user", content="SEGREDO", status="done"))
        db.add(ChatMessage(user_id=bob.id, conversation_id="c1", role="user", content="oi", status="done"))
        pending = ChatMessage(user_id=bob.id, conversation_id="c1", role="assistant", content="", status="pending")
        db.add(pending)
        db.commit()
        seen = {}
        monkeypatch.setattr(chat, "_run_reasoning", lambda db_, u, m, history, q: seen.update(h=history) or
                            {"answer": "ok", "trace": [], "model_used": None})
        chat.answer_async(db, pending.id)
        assert all("SEGREDO" not in h["content"] for h in seen["h"])


class TestAuditLedger:
    """`backend/app/services/integrity.py:_entry_hash:unkeyed-unanchored-partial-seal`"""

    def _three_entries(self, db, machine):
        for ref in (200, 201, 202):
            integrity.append(db, kind="action", payload={"comando": "kill_process"}, ref_id=ref,
                             machine_id=machine["id"])

    def test_hiding_entry_by_changing_machine_breaks_chain(self, db, machine):
        self._three_entries(db, machine)
        db.execute(text("UPDATE ledger_entries SET machine_id = NULL WHERE ref_id = 201"))
        db.commit()
        assert integrity.verify(db)["ok"] is False

    def test_recomputing_chain_without_key_does_not_fool(self, db, machine):
        import json
        self._three_entries(db, machine)
        rows = db.execute(text("SELECT id, kind, ref_id, payload FROM ledger_entries ORDER BY id")).fetchall()
        previous = "0" * 64
        for i, (lid, kind, ref, payload) in enumerate(rows):
            body = json.loads(payload) if isinstance(payload, str) else dict(payload)
            if i == 0:
                body["comando"] = "nada aconteceu"
            canon = integrity.canonical(body)
            pd = hashlib.sha256(canon.encode()).hexdigest()
            eh = hashlib.sha256("|".join([previous, pd, kind, str(ref)]).encode()).hexdigest()
            db.execute(text("UPDATE ledger_entries SET payload=:p, payload_digest=:d, prev_hash=:ph, entry_hash=:h "
                            "WHERE id=:i"), {"p": canon, "d": pd, "ph": previous, "h": eh, "i": lid})
            previous = eh
        db.commit()
        assert integrity.verify(db)["ok"] is False

    def test_verify_counts_only_the_callers_entries(self, client, auth, machine, db):
        self._three_entries(db, machine)
        other = _account(client, "outra")
        assert client.get("/api/audit/verify", headers=other).json()["entries"] == 0
        assert client.get("/api/audit/verify", headers=auth).json()["entries"] == 3

    def test_break_in_another_accounts_entry_is_not_described(self, client, auth, machine, db):
        self._three_entries(db, machine)
        db.execute(text("""UPDATE ledger_entries SET payload = '{"comando": "x"}' WHERE ref_id = 201"""))
        db.commit()
        other = client.get("/api/audit/verify", headers=_account(client, "outra")).json()
        assert other["ok"] is False
        assert not {"broken_at", "kind", "created_at"} & other.keys()
        own = client.get("/api/audit/verify", headers=auth).json()
        assert own["ok"] is False and own["broken_at"]

    def test_machine_removal_keeps_integrity(self, client, auth, machine, db):
        self._three_entries(db, machine)
        assert client.delete(f"/api/machines/{machine['id']}", headers=auth).status_code in (200, 204)
        db.expire_all()
        assert integrity.verify(db)["ok"] is True


class _StalledExecutor:
    """Guarda o trabalho sem executar: a fila fica cheia como num servidor ocupado."""
    def __init__(self):
        self.queue = []

    def submit(self, fn):
        self.queue.append(fn)


class TestAiJobQuota:
    """`backend/app/services/jobs.py:submit:no-per-account-quota-on-ai-jobs`"""

    def test_one_account_cannot_fill_everyones_queue(self, client, monkeypatch):
        monkeypatch.setattr(jobs, "RUN_INLINE", False)
        monkeypatch.setattr(jobs, "_executor", _StalledExecutor())
        jobs._inflight.clear()
        a, v = _account(client, "mallory"), _account(client, "vitima")
        status_codes = [client.post("/api/chat/ask", json={"question": f"pergunta {i}?"}, headers=a).status_code
                   for i in range(jobs.MAX_PER_USER + 2)]
        assert status_codes[:jobs.MAX_PER_USER] == [200] * jobs.MAX_PER_USER
        assert status_codes[-1] == 429
        assert client.post("/api/chat/ask", json={"question": "meu pc esta bem?"}, headers=v).status_code == 200
        jobs._inflight.clear()


class TestPushNotification:
    """`backend/app/services/push.py:subscribe:unvalidated-endpoint-ssrf`"""

    @pytest.mark.parametrize("endpoint", ["http://127.0.0.1:8000/interno", "https://169.254.169.254/x",
                                          "https://fcm.googleapis.com.evil.com/x", "ftp://fcm.googleapis.com/x"])
    def test_rejects_non_push_service_endpoint(self, client, auth, monkeypatch, endpoint):
        monkeypatch.setattr(push, "available", lambda: True)
        res = client.post("/api/account/push/subscribe",
                          json={"endpoint": endpoint, "keys": {"p256dh": "a", "auth": "b"}}, headers=auth)
        assert res.status_code == 400

    def test_accepts_known_push_service(self, client, auth, monkeypatch):
        monkeypatch.setattr(push, "available", lambda: True)
        res = client.post("/api/account/push/subscribe",
                          json={"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "a", "auth": "b"}},
                          headers=auth)
        assert res.status_code == 201


class TestSharedLink:
    """`backend/app/services/share.py:build_package/live-machine-history-beyond-shared-alert`"""

    def test_public_package_has_no_other_alerts(self, client, auth, machine, db):
        a1 = Anomaly(machine_id=machine["id"], anomaly_type="high_cpu", severity="high")
        a2 = Anomaly(machine_id=machine["id"], anomaly_type="high_cpu", severity="high",
                     resolution_cause="NOTA PRIVADA")
        db.add_all([a1, a2])
        db.commit()
        token = client.post(f"/api/share/anomaly/{a1.id}", headers=auth).json()["token"]
        package = client.get(f"/api/share/view/{token}")
        assert package.status_code == 200
        assert "history" not in package.json()
        assert "NOTA PRIVADA" not in package.text


class TestTelegram:
    """`backend/app/services/telegram.py:_handle_start:chat-multi-account-binding`"""

    def test_already_linked_chat_rejects_other_account(self, client, db):
        from app.models.user import User
        _account(client, "vitima"), _account(client, "invasor")
        victim, attacker = (db.query(User).filter(User.username == n).first() for n in ("vitima", "invasor"))
        victim.telegram_link_code, attacker.telegram_link_code = "cv", "ci"
        db.commit()
        telegram._handle_start(db, "5551", "cv")
        reply = telegram._handle_start(db, "5551", "ci")
        db.refresh(attacker)
        assert attacker.telegram_chat_id is None
        assert "outra conta" in reply


class TestKillProcessCommand:
    """`agent/actions.py:_kill-name-match-unbound-process-identity` (lado do servidor)."""

    def _alert(self, db, machine):
        a = Anomaly(machine_id=machine["id"], anomaly_type="process_masquerading", severity="critical",
                    responsible_process="svchost.exe",
                    affected_metrics={"_behavior": {"pid": 4242, "exe": r"C:\Users\bob\svchost.exe",
                                                    "create_time": 1700000000.0}})
        db.add(a)
        db.commit()
        return a

    def test_telegram_sends_process_identity(self, client, auth, machine, db):
        from app.models.command import AgentCommand
        from app.models.user import User
        a = self._alert(db, machine)
        owner = db.query(User).first()
        owner.telegram_chat_id = "777"
        db.commit()
        telegram._handle_callback(db, "777", f"kill:{a.id}")
        cmd = db.query(AgentCommand).filter(AgentCommand.command == "kill_process").first()
        assert cmd.params["pid"] == 4242
        assert cmd.params["exe"] == r"C:\Users\bob\svchost.exe"
        assert cmd.params["create_time"] == 1700000000.0

    def test_sync_playbook_does_not_use_alert_name(self, db, machine):
        a = self._alert(db, machine)
        pb = type("PB", (), {"action": "stop_sync_client", "params": {}})()
        assert "name" not in playbooks._params_for(pb, a)
