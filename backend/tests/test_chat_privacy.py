"""O chat não pode levar dado de máquina "só IA local" ou "sem IA" para a nuvem.

Sem foco ele consulta todas as máquinas da pessoa; com foco, ferramentas e histórico
não podem alcançar outra máquina.
"""
import pytest

from app.core.security import get_password_hash
from app.core.timeutil import utcnow
from app.models.chat import ChatMessage
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.user import User
from app.services import chat, chat_tools, llm


@pytest.fixture
def machine_fleet(db):
    u = User(email="priv@t.com", username="priv", hashed_password=get_password_hash("x"))
    db.add(u)
    db.flush()
    machines = {}
    for name, privacy, cpu in (("PC-Aberto", "any", 11.1), ("PC-Privado", "local_only", 77.7),
                                   ("PC-Sem-IA", "no_ai", 55.5)):
        m = Machine(name=name, hostname=name, agent_token=f"tk-{name}", owner_id=u.id, ai_privacy=privacy)
        db.add(m)
        db.flush()
        db.add(Metric(machine_id=m.id, timestamp=utcnow(), cpu_percent=cpu, mem_percent=40.0, disk_percent=50.0))
        machines[name] = m
    db.commit()
    return u, machines


@pytest.fixture
def ai_spy(monkeypatch):
    """Substitui a cadeia de IA: guarda o que seria enviado e responde direto."""
    calls = []

    def complete(prompt, *, privacy=llm.PRIVACY_ANY, parse=None, **_):
        calls.append({"prompt": prompt, "privacy": privacy})
        return llm.LLMResult(ok=True, text="", value={"action": "answer", "text": "ok"}, provider="espiao")

    monkeypatch.setattr(llm, "complete", complete)
    return calls


class TestConversationPrivacy:
    def test_without_focus_local_only_machine_keeps_conversation_local(self, db, machine_fleet, ai_spy):
        u, _ = machine_fleet
        chat._run_reasoning(db, u, None, [], "como estão meus computadores?")
        assert ai_spy[0]["privacy"] == llm.PRIVACY_LOCAL_ONLY

    def test_focus_on_no_ai_machine_calls_nobody(self, db, machine_fleet, ai_spy):
        u, m = machine_fleet
        chat._run_reasoning(db, u, m["PC-Sem-IA"], [], "e aí?")
        assert ai_spy[0]["privacy"] == llm.PRIVACY_NO_AI

    def test_no_ai_machine_not_in_prompt(self, db, machine_fleet, ai_spy):
        u, _ = machine_fleet
        chat._run_reasoning(db, u, None, [], "como estão?")
        assert "PC-Sem-IA" not in ai_spy[0]["prompt"]

    def test_focus_on_machine_lists_only_it(self, db, machine_fleet, ai_spy):
        u, m = machine_fleet
        chat._run_reasoning(db, u, m["PC-Aberto"], [], "como está?")
        assert "PC-Privado" not in ai_spy[0]["prompt"]
        assert ai_spy[0]["privacy"] == llm.PRIVACY_ANY


class TestToolsRespectScope:
    def test_focus_on_machine_does_not_reach_another(self, db, machine_fleet):
        """Era por aqui que a máquina só local vazava mesmo com outra em foco."""
        u, m = machine_fleet
        r = chat_tools.run(db, u, m["PC-Aberto"], "metric_stats", {"machine_id": m["PC-Privado"].id})
        assert "error" in r
        assert "77.7" not in str(r)

    def test_no_ai_machine_never_queried(self, db, machine_fleet):
        u, m = machine_fleet
        r = chat_tools.run(db, u, None, "metric_stats", {"machine_id": m["PC-Sem-IA"].id})
        assert "error" in r and "55.5" not in str(r)

    def test_list_machines(self, db, machine_fleet):
        u, m = machine_fleet
        without_focus = {x["name"] for x in chat_tools.run(db, u, None, "list_machines", {})}
        assert without_focus == {"PC-Aberto", "PC-Privado"}
        with_focus = {x["name"] for x in chat_tools.run(db, u, m["PC-Aberto"], "list_machines", {})}
        assert with_focus == {"PC-Aberto"}

    def test_compare_machines_only_among_reachable(self, db, machine_fleet, monkeypatch):
        from app.services import fleet
        u, m = machine_fleet
        seen = {}
        monkeypatch.setattr(fleet, "peer_insights",
                            lambda db, owner_id, days=7, machine_ids=None: seen.update(ids=machine_ids) or {})
        chat_tools.run(db, u, None, "compare_machines", {})
        assert set(seen["ids"]) == {m["PC-Aberto"].id, m["PC-Privado"].id}


class TestHistory:
    def test_answer_about_other_machine_not_in_prompt(self, db, machine_fleet, ai_spy):
        """A tela não reinicia a conversa ao trocar de máquina."""
        u, m = machine_fleet
        conversation = "c1"
        for role, text, machine in (("user", "e o privado?", m["PC-Privado"]),
                                      ("assistant", "O PC-Privado está com 77.7% de processador.", m["PC-Privado"]),
                                      ("user", "e o aberto?", m["PC-Aberto"])):
            db.add(ChatMessage(user_id=u.id, machine_id=machine.id, conversation_id=conversation, role=role,
                               content=text, status="done"))
        pending = ChatMessage(user_id=u.id, machine_id=m["PC-Aberto"].id, conversation_id=conversation,
                               role="assistant", content="", status="pending")
        db.add(pending)
        db.commit()
        chat.answer_async(db, pending.id)
        assert "77.7" not in ai_spy[0]["prompt"]
        assert "e o aberto?" in ai_spy[0]["prompt"]
