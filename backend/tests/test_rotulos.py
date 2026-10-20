"""
Rótulos de sessão: o gabarito da avaliação em dado real.

A pessoa marca na bandeja o que está fazendo ("jogando", "teste: minerador").
Depois, a avaliação cruza esses intervalos com os avisos para medir acerto e
erro no uso de verdade. O rótulo é só gabarito: se a detecção pudesse lê-lo,
a medida estaria medindo a própria resposta.
"""
import os
import re
from datetime import timedelta

import pytest

from app.core.timeutil import aware, utcnow


def _maquina(db, machine):
    from app.models.machine import Machine
    return db.query(Machine).filter(Machine.id == machine["id"]).one()


def test_marcar_abre_sessao(db, machine):
    from app.services import activity_labels
    sessao = activity_labels.mark(db, _maquina(db, machine), "jogando", "tray")
    assert sessao.label == "jogando"
    assert sessao.source == "tray"
    assert sessao.started_at is not None and sessao.ended_at is None


def test_trocar_de_rotulo_fecha_a_anterior_no_mesmo_horario(db, machine):
    from app.models.activity_label import ActivityLabel
    from app.services import activity_labels
    m = _maquina(db, machine)
    inicio = utcnow() - timedelta(minutes=30)
    activity_labels.mark(db, m, "jogando", "tray", now=inicio)
    troca = inicio + timedelta(minutes=20)
    nova = activity_labels.mark(db, m, "teste_minerador", "tray", now=troca)
    antiga = db.query(ActivityLabel).filter(ActivityLabel.label == "jogando").one()
    assert aware(antiga.ended_at) == troca
    assert aware(nova.started_at) == troca and nova.ended_at is None


def test_parar_so_fecha(db, machine):
    from app.models.activity_label import ActivityLabel
    from app.services import activity_labels
    m = _maquina(db, machine)
    activity_labels.mark(db, m, "uso_normal", "tray")
    assert activity_labels.mark(db, m, "parar", "tray") is None
    rows = db.query(ActivityLabel).all()
    assert len(rows) == 1 and rows[0].ended_at is not None


def test_mesmo_rotulo_de_novo_nao_parte_a_sessao(db, machine):
    """Clique duplo na bandeja não pode virar duas sessões."""
    from app.models.activity_label import ActivityLabel
    from app.services import activity_labels
    m = _maquina(db, machine)
    primeira = activity_labels.mark(db, m, "jogando", "tray")
    segunda = activity_labels.mark(db, m, "jogando", "tray")
    assert primeira.id == segunda.id
    assert db.query(ActivityLabel).count() == 1


def test_rotulo_desconhecido_e_recusado(db, machine):
    from app.services import activity_labels
    with pytest.raises(ValueError):
        activity_labels.mark(db, _maquina(db, machine), "minerando_de_verdade", "tray")


def test_sessoes_que_cruzam_a_janela(db, machine):
    from app.services import activity_labels
    m = _maquina(db, machine)
    agora = utcnow()
    activity_labels.mark(db, m, "uso_normal", "tray", now=agora - timedelta(hours=10))
    activity_labels.mark(db, m, "parar", "tray", now=agora - timedelta(hours=9))
    activity_labels.mark(db, m, "jogando", "tray", now=agora - timedelta(hours=2))
    achadas = activity_labels.sessions(db, m.id, agora - timedelta(hours=3), agora)
    assert [s.label for s in achadas] == ["jogando"]


def test_os_ids_do_catalogo():
    from app.services import activity_labels
    assert set(activity_labels.LABELS) == {
        "jogando", "trabalho_pesado", "uso_normal", "teste_minerador",
        "teste_minerador_em_uso", "teste_disfarce", "teste_isca", "teste_periodico",
    }
    assert activity_labels.BENIGN == {"jogando", "trabalho_pesado", "uso_normal"}


def test_endpoint_do_agente_exige_token(client):
    res = client.post("/api/agent/activity-label", json={"label": "jogando"},
                      headers={"X-Agent-Token": "token-que-nao-existe"})
    assert res.status_code == 401


def test_endpoint_do_agente_marca(client, machine):
    res = client.post("/api/agent/activity-label", json={"label": "jogando"},
                      headers={"X-Agent-Token": machine["agent_token"]})
    assert res.status_code == 200
    assert res.json()["open"]["label"] == "jogando"


def test_endpoint_recusa_rotulo_desconhecido(client, machine):
    res = client.post("/api/agent/activity-label", json={"label": "xyz"},
                      headers={"X-Agent-Token": machine["agent_token"]})
    assert res.status_code == 422


def test_painel_marca_e_lista(client, machine, auth):
    res = client.post(f"/api/machines/{machine['id']}/activity-label", json={"label": "trabalho_pesado"},
                      headers=auth)
    assert res.status_code == 200
    lista = client.get(f"/api/machines/{machine['id']}/activity-labels?days=7", headers=auth).json()
    assert lista["open"]["label"] == "trabalho_pesado"
    assert lista["open"]["source"] == "panel"
    assert [s["label"] for s in lista["sessions"]] == ["trabalho_pesado"]
    assert {c["id"] for c in lista["catalog"]} >= {"jogando", "teste_minerador"}


def test_painel_exige_ser_o_dono(client, machine):
    client.post("/api/auth/register", json={"email": "o@o.com", "username": "outro", "password": "outrasenha123"})
    tok = client.post("/api/auth/login", data={"username": "outro", "password": "outrasenha123"}).json()["access_token"]
    outro = {"Authorization": f"Bearer {tok}"}
    res = client.post(f"/api/machines/{machine['id']}/activity-label", json={"label": "jogando"}, headers=outro)
    assert res.status_code == 404
    res = client.get(f"/api/machines/{machine['id']}/activity-labels", headers=outro)
    assert res.status_code == 404


PERMITIDOS = {
    "models/activity_label.py", "models/__init__.py", "services/activity_labels.py",
    "services/real_eval.py", "routers/agent_api.py", "routers/machines.py", "routers/evaluation.py",
}


def test_deteccao_nunca_le_rotulos():
    """Só o cadastro e a avaliação conhecem os rótulos. Se a detecção os lesse,
    a avaliação em dado real mediria a própria resposta."""
    app_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
    invasores = []
    for raiz, _, arquivos in os.walk(app_dir):
        for nome in arquivos:
            if not nome.endswith(".py"):
                continue
            caminho = os.path.join(raiz, nome)
            rel = os.path.relpath(caminho, app_dir).replace(os.sep, "/")
            with open(caminho, encoding="utf-8") as f:
                if re.search(r"activity_label|ActivityLabel", f.read()) and rel not in PERMITIDOS:
                    invasores.append(rel)
    assert invasores == []
