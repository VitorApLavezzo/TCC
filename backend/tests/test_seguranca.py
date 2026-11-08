"""
Regressões da auditoria de segurança (run-1, ~/security-audit-skill/TCC/run-1).

Cada classe fixa uma falha confirmada pela auditoria: o teste falhava antes da
correção e descreve a fronteira que precisa continuar valendo. Os nomes entre
crases são os fingerprints do relatório, para achar o registro completo.
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


def _conta(client, nome: str) -> dict:
    client.post("/api/auth/register", json={"email": f"{nome}@x.com", "username": nome, "password": "senha-boa-123"})
    res = client.post("/api/auth/login", data={"username": nome, "password": "senha-boa-123"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _maquina(client, headers, nome="PC") -> dict:
    res = client.post("/api/machines", json={"name": nome, "hostname": nome, "os_type": "Windows"}, headers=headers)
    return res.json()


def _proc(name, exe, sha256=None, signed="unsigned", publisher=None):
    return type("P", (), {"name": name, "exe": exe, "sha256": sha256, "signed": signed,
                          "publisher": publisher, "parent_name": None})()


class TestChaveDeSessao:
    """`backend/app/config.py:Settings.SECRET_KEY:public-default-accepted`"""

    @pytest.mark.parametrize("chave", ["change-this-in-production", "dev-secret-key-change-in-production", "curta"])
    def test_recusa_chave_publica_ou_curta(self, chave):
        with pytest.raises(ValidationError):
            Settings(SECRET_KEY=chave, _env_file=None)

    def test_sem_chave_nao_sobe(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_aceita_chave_forte(self):
        assert Settings(SECRET_KEY="x" * 40, _env_file=None).SECRET_KEY == "x" * 40


def _req(peer: str, **headers) -> Request:
    return Request({"type": "http", "client": (peer, 5000),
                    "headers": [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]})


class TestLimiteDeTentativasPorIp:
    """`backend/app/core/ratelimit.py:_client_ip:client-supplied-x-forwarded-for` e vizinhos."""

    def test_cliente_nao_escolhe_o_proprio_balde(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "172.16.0.0/12")
        assert ratelimit._client_ip(_req("203.0.113.5", x_forwarded_for="1.2.3.4")) == "203.0.113.5"

    def test_atras_do_nginx_usa_o_ip_que_ele_escreve(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "172.16.0.0/12")
        assert ratelimit._client_ip(_req("172.18.0.3", x_real_ip="198.51.100.7")) == "198.51.100.7"

    def test_numero_de_chaves_tem_teto(self, monkeypatch):
        ratelimit.reset()
        monkeypatch.setattr(ratelimit, "_MAX_KEYS", 100)
        for i in range(150):
            ratelimit.check(f"login:10.0.{i // 250}.{i % 250}", times=5, seconds=3600)
        assert len(ratelimit._hits) <= 100


class TestInstaladorHeadless:
    """`backend/app/routers/agent_files.py:install_script:query-values-interpolated-into-bash`"""

    @pytest.mark.parametrize("params", [
        {"code": "ABCD-EFGH", "server": 'http://srv:3000";echo X;"'},
        {"code": "ABCD-EFGH", "server": "http://srv:3000$(echo X)"},
        {"code": "ABCD-EFGH", "server": "http://[::1"},
        {"code": 'X" ; echo X ; : "', "server": "http://srv:3000"},
        {"token": 'X" ; echo X ; : "', "server": "http://srv:3000"},
    ])
    def test_recusa_metacaracteres(self, client, params):
        assert client.get("/api/agent/install.sh", params=params).status_code == 400

    def test_valores_legitimos_continuam_funcionando(self, client):
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
        agora = int(time.time())
        return jose_jwt.encode({"iss": "https://accounts.google.com", "aud": "cliente.apps.googleusercontent.com",
                                "sub": sub, "email": email, "email_verified": True, "iat": agora,
                                "exp": agora + 3600}, pem, algorithm="RS256", headers={"kid": "k1"})
    return token


class TestLoginGoogle:
    """`backend/app/routers/auth.py:google_login:links-unverified-register-email`"""

    def test_nao_entra_em_conta_de_senha_com_o_mesmo_email(self, client, google):
        client.post("/api/auth/register", json={"email": "vitima@x.com", "username": "invasor",
                                                "password": "senha-do-invasor"})
        res = client.post("/api/auth/google", json={"credential": google("vitima@x.com", "sub-vitima")})
        assert res.status_code == 409
        assert "access_token" not in res.json()

    def test_conta_antiga_liberada_pelo_administrador_entra_com_google(self, client, google, db):
        # Conta criada pelo Google antes do vínculo por sub: tem senha
        # aleatória que ninguém sabe, então "entre com senha" não serve.
        from liberar_google import liberar
        client.post("/api/auth/register", json={"email": "Antiga@x.com", "username": "antiga",
                                                "password": "senha-qualquer-1"})
        assert liberar(db, "antiga@x.com") is True
        res = client.post("/api/auth/google", json={"credential": google("antiga@x.com", "sub-antiga")})
        assert res.status_code == 200
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"}).json()
        assert me["username"] == "antiga"

    def test_liberacao_vale_so_para_a_primeira_identidade_google(self, client, google, db):
        from liberar_google import liberar
        client.post("/api/auth/register", json={"email": "uma@x.com", "username": "uma",
                                                "password": "senha-qualquer-1"})
        liberar(db, "uma@x.com")
        assert client.post("/api/auth/google", json={"credential": google("uma@x.com", "sub-a")}).status_code == 200
        assert client.post("/api/auth/google", json={"credential": google("uma@x.com", "sub-b")}).status_code == 409

    def test_liberar_conta_inexistente_ou_ja_vinculada_nao_faz_nada(self, client, google, db):
        from liberar_google import liberar
        assert liberar(db, "ninguem@x.com") is False
        client.post("/api/auth/google", json={"credential": google("ja@x.com", "sub-ja")})
        assert liberar(db, "ja@x.com") is False

    def test_mesma_identidade_google_volta_para_a_mesma_conta(self, client, google):
        a = client.post("/api/auth/google", json={"credential": google("nova@x.com", "sub-1")}).json()
        b = client.post("/api/auth/google", json={"credential": google("nova@x.com", "sub-1")}).json()
        me = [client.get("/api/auth/me", headers={"Authorization": f"Bearer {t['access_token']}"}).json()["id"]
              for t in (a, b)]
        assert me[0] == me[1]


class TestPareamentoAtomico:
    """`backend/app/routers/machines.py:enroll_agent:non-atomic-code-consumption`"""

    def test_consumo_com_leitura_velha_nao_passa_do_limite(self, client, auth, db):
        from app.routers import machines as rota
        from app.models.user import User
        dono = db.query(User).first()
        db.add(EnrollmentCode(code="ABCD-EFGH", user_id=dono.id, reusable=True, max_uses=1,
                              expires_at=__import__("app.core.timeutil", fromlist=["utcnow"]).utcnow()
                              + __import__("datetime").timedelta(days=1)))
        db.commit()
        velha = TestingSessionLocal()
        lida_antes = velha.query(EnrollmentCode).filter(EnrollmentCode.code == "ABCD-EFGH").first()
        assert client.post("/api/machines/enroll", json={"code": "ABCD-EFGH", "hostname": "h1"}).status_code == 200
        # A leitura de antes ainda diz use_count=0; o consumo tem de decidir no banco
        assert rota._consume_enrollment(velha, lida_antes) is False
        velha.close()


class TestReputacaoPorConta:
    """Fingerprints de reputação: lookup, prevalência pelo agente, feedback e hub."""

    def test_consulta_nao_revela_programa_de_outra_conta(self, client, db):
        vitima, invasor = _conta(client, "vitima"), _conta(client, "invasor")
        m = db.query(Machine).get(_maquina(client, vitima)["id"])
        identity_service.observe(db, m, [_proc("ferramenta-privada.exe", r"C:\x\ferramenta-privada.exe")], [])
        db.commit()
        res = client.get("/api/reputation/lookup", params={"name": "ferramenta-privada.exe"}, headers=invasor)
        assert res.json()["found"] is False

    def test_um_agente_nao_inventa_prevalencia(self, client, db):
        a, v = _conta(client, "invasor"), _conta(client, "vitima")
        ma = db.query(Machine).get(_maquina(client, a, "A")["id"])
        mv = db.query(Machine).get(_maquina(client, v, "V")["id"])
        sha = "b2" * 32
        identity_service.observe(db, ma, [_proc("miner.exe", rf"C:\fake{i}\miner.exe", sha) for i in range(3)], [])
        db.commit()
        rep = db.query(HashReputation).filter(HashReputation.identity_key == sha).first()
        assert rep.local_machines == 1
        alvo = _proc("miner.exe", r"C:\Users\v\miner.exe", sha)
        identity_service.observe(db, mv, [alvo], [])
        db.commit()
        assert trust.evaluate(db, mv.id, alvo).level == trust.UNKNOWN

    def test_maquinas_de_outra_conta_nao_contam_como_prevalencia(self, client, db):
        a, v = _conta(client, "invasor"), _conta(client, "vitima")
        sha = "c3" * 32
        for i in range(3):
            m = db.query(Machine).get(_maquina(client, a, f"A{i}")["id"])
            identity_service.observe(db, m, [_proc("imp.exe", r"C:\Users\a\imp.exe", sha)], [])
        mv = db.query(Machine).get(_maquina(client, v, "V")["id"])
        alvo = _proc("imp.exe", r"C:\Users\v\imp.exe", sha)
        identity_service.observe(db, mv, [alvo], [])
        db.commit()
        avaliado = trust.evaluate(db, mv.id, alvo)
        assert avaliado.level == trust.UNKNOWN
        assert not any("visto em" in r for r in avaliado.reasons)

    def test_feedback_de_outra_conta_nao_reprova_o_programa(self, client, db):
        a, v = _conta(client, "invasor"), _conta(client, "vitima")
        ma = _maquina(client, a, "A")
        mv = db.query(Machine).get(_maquina(client, v, "V")["id"])
        defender = _proc("MsMpEng.exe", r"C:\Program Files\Windows Defender\MsMpEng.exe", None, "signed",
                         "Microsoft Corporation")
        identity_service.observe(db, mv, [defender], [])
        anomalia = Anomaly(machine_id=ma["id"], anomaly_type="canary_tripped", severity="critical",
                           responsible_process="MsMpEng.exe")
        db.add(anomalia)
        db.commit()
        assert trust.evaluate(db, mv.id, defender).level == trust.SECURITY
        for _ in range(3):
            assert client.post(f"/api/anomalies/{anomalia.id}/feedback", json={"kind": "problem"},
                               headers=a).status_code == 200
        db.expire_all()
        assert trust.evaluate(db, mv.id, defender).level == trust.SECURITY
        rep = db.query(HashReputation).filter(HashReputation.identity_key == "nome:msmpeng.exe").first()
        assert rep.marked_problem == 1

    def test_hub_desligado_por_padrao(self):
        assert Settings(SECRET_KEY="x" * 40, _env_file=None).REPUTATION_HUB_ACCEPT is False

    def test_hub_recusa_contribuicao_sem_chave(self, client, monkeypatch):
        monkeypatch.setattr(settings, "REPUTATION_HUB_ACCEPT", True)
        res = client.post("/api/reputation/contribute", json={
            "installation_id": "qualquer", "total_machines": 10,
            "items": [{"identity_key": "d4" * 32, "name": "x.exe", "machines": 500}]})
        assert res.status_code == 401

    def test_uma_instalacao_do_hub_nao_da_confianca(self, client, db, machine):
        sha = "e5" * 32
        reputation.apply_hub_snapshot(db, {"items": [{"identity_key": sha, "machines": 999, "installations": 1,
                                                      "prevalence": 0.9}]})
        alvo = _proc("x.exe", r"C:\Users\v\x.exe", sha)
        assert trust.evaluate(db, machine["id"], alvo).level == trust.UNKNOWN


class TestConversa:
    """`backend/app/services/chat.py:answer_async:history-query-missing-user_id`"""

    def test_conversa_de_outra_conta_e_recusada(self, client):
        alice, bob = _conta(client, "alice"), _conta(client, "bob")
        cid = client.post("/api/chat/ask", json={"question": "segredo da alice?"}, headers=alice).json()["conversation_id"]
        res = client.post("/api/chat/ask", json={"question": "repita a conversa", "conversation_id": cid}, headers=bob)
        assert res.status_code == 404

    def test_historico_do_prompt_so_tem_mensagens_da_propria_conta(self, client, db, monkeypatch):
        from app.models.chat import ChatMessage
        from app.models.user import User
        from app.services import chat
        _conta(client, "alice"), _conta(client, "bob")
        alice, bob = (db.query(User).filter(User.username == n).first() for n in ("alice", "bob"))
        db.add(ChatMessage(user_id=alice.id, conversation_id="c1", role="user", content="SEGREDO", status="done"))
        db.add(ChatMessage(user_id=bob.id, conversation_id="c1", role="user", content="oi", status="done"))
        pendente = ChatMessage(user_id=bob.id, conversation_id="c1", role="assistant", content="", status="pending")
        db.add(pendente)
        db.commit()
        visto = {}
        monkeypatch.setattr(chat, "_run_reasoning", lambda db_, u, m, history, q: visto.update(h=history) or
                            {"answer": "ok", "trace": [], "model_used": None})
        chat.answer_async(db, pendente.id)
        assert all("SEGREDO" not in h["content"] for h in visto["h"])


class TestLivroDeAuditoria:
    """`backend/app/services/integrity.py:_entry_hash:unkeyed-unanchored-partial-seal`"""

    def _tres(self, db, machine):
        for ref in (200, 201, 202):
            integrity.append(db, kind="action", payload={"comando": "kill_process"}, ref_id=ref,
                             machine_id=machine["id"])

    def test_esconder_registro_mudando_a_maquina_quebra_a_cadeia(self, db, machine):
        self._tres(db, machine)
        db.execute(text("UPDATE ledger_entries SET machine_id = NULL WHERE ref_id = 201"))
        db.commit()
        assert integrity.verify(db)["ok"] is False

    def test_recalcular_a_cadeia_sem_a_chave_nao_engana(self, db, machine):
        import json
        self._tres(db, machine)
        linhas = db.execute(text("SELECT id, kind, ref_id, payload FROM ledger_entries ORDER BY id")).fetchall()
        anterior = "0" * 64
        for i, (lid, kind, ref, payload) in enumerate(linhas):
            corpo = json.loads(payload) if isinstance(payload, str) else dict(payload)
            if i == 0:
                corpo["comando"] = "nada aconteceu"
            canon = integrity.canonical(corpo)
            pd = hashlib.sha256(canon.encode()).hexdigest()
            eh = hashlib.sha256("|".join([anterior, pd, kind, str(ref)]).encode()).hexdigest()
            db.execute(text("UPDATE ledger_entries SET payload=:p, payload_digest=:d, prev_hash=:ph, entry_hash=:h "
                            "WHERE id=:i"), {"p": canon, "d": pd, "ph": anterior, "h": eh, "i": lid})
            anterior = eh
        db.commit()
        assert integrity.verify(db)["ok"] is False

    def test_remocao_de_maquina_continua_integra(self, client, auth, machine, db):
        self._tres(db, machine)
        assert client.delete(f"/api/machines/{machine['id']}", headers=auth).status_code in (200, 204)
        db.expire_all()
        assert integrity.verify(db)["ok"] is True


class _ExecutorParado:
    """Guarda o trabalho sem executar: a fila fica cheia como num servidor ocupado."""
    def __init__(self):
        self.fila = []

    def submit(self, fn):
        self.fila.append(fn)


class TestCotaDeTrabalhosDeIa:
    """`backend/app/services/jobs.py:submit:no-per-account-quota-on-ai-jobs`"""

    def test_uma_conta_nao_enche_a_fila_de_todos(self, client, monkeypatch):
        monkeypatch.setattr(jobs, "RUN_INLINE", False)
        monkeypatch.setattr(jobs, "_executor", _ExecutorParado())
        jobs._inflight.clear()
        a, v = _conta(client, "mallory"), _conta(client, "vitima")
        codigos = [client.post("/api/chat/ask", json={"question": f"pergunta {i}?"}, headers=a).status_code
                   for i in range(jobs.MAX_PER_USER + 2)]
        assert codigos[:jobs.MAX_PER_USER] == [200] * jobs.MAX_PER_USER
        assert codigos[-1] == 429
        assert client.post("/api/chat/ask", json={"question": "meu pc esta bem?"}, headers=v).status_code == 200
        jobs._inflight.clear()


class TestNotificacaoNoCelular:
    """`backend/app/services/push.py:subscribe:unvalidated-endpoint-ssrf`"""

    @pytest.mark.parametrize("endpoint", ["http://127.0.0.1:8000/interno", "https://169.254.169.254/x",
                                          "https://fcm.googleapis.com.evil.com/x", "ftp://fcm.googleapis.com/x"])
    def test_recusa_endereco_que_nao_e_servico_de_push(self, client, auth, monkeypatch, endpoint):
        monkeypatch.setattr(push, "available", lambda: True)
        res = client.post("/api/account/push/subscribe",
                          json={"endpoint": endpoint, "keys": {"p256dh": "a", "auth": "b"}}, headers=auth)
        assert res.status_code == 400

    def test_aceita_servico_de_push_conhecido(self, client, auth, monkeypatch):
        monkeypatch.setattr(push, "available", lambda: True)
        res = client.post("/api/account/push/subscribe",
                          json={"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "a", "auth": "b"}},
                          headers=auth)
        assert res.status_code == 201


class TestLinkCompartilhado:
    """`backend/app/services/share.py:build_package/live-machine-history-beyond-shared-alert`"""

    def test_pacote_publico_nao_traz_outros_avisos(self, client, auth, machine, db):
        a1 = Anomaly(machine_id=machine["id"], anomaly_type="high_cpu", severity="high")
        a2 = Anomaly(machine_id=machine["id"], anomaly_type="high_cpu", severity="high",
                     resolution_cause="NOTA PRIVADA")
        db.add_all([a1, a2])
        db.commit()
        token = client.post(f"/api/share/anomaly/{a1.id}", headers=auth).json()["token"]
        pacote = client.get(f"/api/share/view/{token}")
        assert pacote.status_code == 200
        assert "history" not in pacote.json()
        assert "NOTA PRIVADA" not in pacote.text


class TestTelegram:
    """`backend/app/services/telegram.py:_handle_start:chat-multi-account-binding`"""

    def test_chat_ja_vinculado_nao_aceita_outra_conta(self, client, db):
        from app.models.user import User
        _conta(client, "vitima"), _conta(client, "invasor")
        vitima, invasor = (db.query(User).filter(User.username == n).first() for n in ("vitima", "invasor"))
        vitima.telegram_link_code, invasor.telegram_link_code = "cv", "ci"
        db.commit()
        telegram._handle_start(db, "5551", "cv")
        resposta = telegram._handle_start(db, "5551", "ci")
        db.refresh(invasor)
        assert invasor.telegram_chat_id is None
        assert "outra conta" in resposta


class TestOrdemDeEncerrarProcesso:
    """`agent/actions.py:_kill-name-match-unbound-process-identity` (lado do servidor)."""

    def _aviso(self, db, machine):
        a = Anomaly(machine_id=machine["id"], anomaly_type="process_masquerading", severity="critical",
                    responsible_process="svchost.exe",
                    affected_metrics={"_behavior": {"pid": 4242, "exe": r"C:\Users\bob\svchost.exe",
                                                    "create_time": 1700000000.0}})
        db.add(a)
        db.commit()
        return a

    def test_telegram_manda_a_identidade_do_processo(self, client, auth, machine, db):
        from app.models.command import AgentCommand
        from app.models.user import User
        a = self._aviso(db, machine)
        dono = db.query(User).first()
        dono.telegram_chat_id = "777"
        db.commit()
        telegram._handle_callback(db, "777", f"kill:{a.id}")
        cmd = db.query(AgentCommand).filter(AgentCommand.command == "kill_process").first()
        assert cmd.params["pid"] == 4242
        assert cmd.params["exe"] == r"C:\Users\bob\svchost.exe"
        assert cmd.params["create_time"] == 1700000000.0

    def test_playbook_de_sincronizacao_nao_usa_o_nome_do_aviso(self, db, machine):
        a = self._aviso(db, machine)
        pb = type("PB", (), {"action": "stop_sync_client", "params": {}})()
        assert "name" not in playbooks._params_for(pb, a)
