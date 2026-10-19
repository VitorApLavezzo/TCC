"""O chat não pode levar dado de máquina "só IA local" ou "sem IA" para a nuvem.

Todas as outras chamadas de IA são de uma máquina só e usam a privacidade dela.
O chat é a exceção: sem foco ele consulta todas as máquinas da pessoa, e
assumia privacidade "qualquer" — então uma máquina "só local" chegava ao
Claude. Com foco, uma ferramenta chamada com `machine_id` de outra máquina
escapava do foco. E o histórico era carregado pela conversa inteira, sem olhar
de qual máquina era cada resposta.
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
def frota(db):
    u = User(email="priv@t.com", username="priv", hashed_password=get_password_hash("x"))
    db.add(u)
    db.flush()
    maquinas = {}
    for nome, privacidade, cpu in (("PC-Aberto", "any", 11.1), ("PC-Privado", "local_only", 77.7),
                                   ("PC-Sem-IA", "no_ai", 55.5)):
        m = Machine(name=nome, hostname=nome, agent_token=f"tk-{nome}", owner_id=u.id, ai_privacy=privacidade)
        db.add(m)
        db.flush()
        db.add(Metric(machine_id=m.id, timestamp=utcnow(), cpu_percent=cpu, mem_percent=40.0, disk_percent=50.0))
        maquinas[nome] = m
    db.commit()
    return u, maquinas


@pytest.fixture
def ia_espiao(monkeypatch):
    """Substitui a cadeia de IA: guarda o que seria enviado e responde direto."""
    chamadas = []

    def complete(prompt, *, privacy=llm.PRIVACY_ANY, parse=None, **_):
        chamadas.append({"prompt": prompt, "privacy": privacy})
        return llm.LLMResult(ok=True, text="", value={"action": "answer", "text": "ok"}, provider="espiao")

    monkeypatch.setattr(llm, "complete", complete)
    return chamadas


class TestPrivacidadeDaConversa:
    def test_sem_foco_com_maquina_so_local_a_conversa_inteira_fica_local(self, db, frota, ia_espiao):
        u, _ = frota
        chat._run_reasoning(db, u, None, [], "como estão meus computadores?")
        assert ia_espiao[0]["privacy"] == llm.PRIVACY_LOCAL_ONLY

    def test_foco_numa_maquina_sem_ia_nao_chama_ninguem(self, db, frota, ia_espiao):
        u, m = frota
        chat._run_reasoning(db, u, m["PC-Sem-IA"], [], "e aí?")
        assert ia_espiao[0]["privacy"] == llm.PRIVACY_NO_AI

    def test_maquina_sem_ia_nao_aparece_no_prompt(self, db, frota, ia_espiao):
        u, _ = frota
        chat._run_reasoning(db, u, None, [], "como estão?")
        assert "PC-Sem-IA" not in ia_espiao[0]["prompt"]

    def test_foco_numa_maquina_lista_so_ela(self, db, frota, ia_espiao):
        u, m = frota
        chat._run_reasoning(db, u, m["PC-Aberto"], [], "como está?")
        assert "PC-Privado" not in ia_espiao[0]["prompt"]
        assert ia_espiao[0]["privacy"] == llm.PRIVACY_ANY


class TestFerramentasRespeitamOAlcance:
    def test_foco_numa_maquina_nao_alcanca_outra(self, db, frota):
        """Era por aqui que a máquina só local vazava mesmo com outra em foco."""
        u, m = frota
        r = chat_tools.run(db, u, m["PC-Aberto"], "metric_stats", {"machine_id": m["PC-Privado"].id})
        assert "error" in r
        assert "77.7" not in str(r)

    def test_maquina_sem_ia_nunca_e_consultada(self, db, frota):
        u, m = frota
        r = chat_tools.run(db, u, None, "metric_stats", {"machine_id": m["PC-Sem-IA"].id})
        assert "error" in r and "55.5" not in str(r)

    def test_listar_maquinas(self, db, frota):
        u, m = frota
        sem_foco = {x["name"] for x in chat_tools.run(db, u, None, "list_machines", {})}
        assert sem_foco == {"PC-Aberto", "PC-Privado"}
        com_foco = {x["name"] for x in chat_tools.run(db, u, m["PC-Aberto"], "list_machines", {})}
        assert com_foco == {"PC-Aberto"}

    def test_comparar_maquinas_so_entre_as_alcancaveis(self, db, frota, monkeypatch):
        from app.services import fleet
        u, m = frota
        visto = {}
        monkeypatch.setattr(fleet, "peer_insights",
                            lambda db, owner_id, days=7, machine_ids=None: visto.update(ids=machine_ids) or {})
        chat_tools.run(db, u, None, "compare_machines", {})
        assert set(visto["ids"]) == {m["PC-Aberto"].id, m["PC-Privado"].id}


class TestHistorico:
    def test_resposta_sobre_outra_maquina_nao_entra_no_prompt(self, db, frota, ia_espiao):
        """A tela não reinicia a conversa ao trocar de máquina."""
        u, m = frota
        conversa = "c1"
        for papel, texto, maquina in (("user", "e o privado?", m["PC-Privado"]),
                                      ("assistant", "O PC-Privado está com 77.7% de processador.", m["PC-Privado"]),
                                      ("user", "e o aberto?", m["PC-Aberto"])):
            db.add(ChatMessage(user_id=u.id, machine_id=maquina.id, conversation_id=conversa, role=papel,
                               content=texto, status="done"))
        pendente = ChatMessage(user_id=u.id, machine_id=m["PC-Aberto"].id, conversation_id=conversa,
                               role="assistant", content="", status="pending")
        db.add(pendente)
        db.commit()
        chat.answer_async(db, pendente.id)
        assert "77.7" not in ia_espiao[0]["prompt"]
        assert "e o aberto?" in ia_espiao[0]["prompt"]
