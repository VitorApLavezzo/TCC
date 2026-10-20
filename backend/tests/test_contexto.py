"""
Contexto da leitura: o que separa um jogo de um minerador.

Os dois pesam igual no processador. A diferença está em volta: o jogo é o
programa na janela da frente (ou filho dele), é conhecido, tem dono; o
minerador roda sozinho, com carga plana, aberto por ninguém que a pessoa
esteja usando. Estas colunas são gravadas na chegada da leitura — treino e
detecção usam exatamente os mesmos números.
"""
from datetime import timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from app.core.timeutil import utcnow
from tests.test_trust import _machine


def _proc(**over):
    base = {"pid": 900, "name": "jogo.exe", "exe": "D:\\Jogos\\jogo.exe", "cpu_percent": 400.0,
            "mem_percent": 10.0, "ancestors": None, "signed": "unsigned", "publisher": None,
            "sha256": "b" * 64, "username": "user", "cmdline": "jogo.exe"}
    return SimpleNamespace(**{**base, **over})


def _leitura(db, machine_id, quando=None, **over):
    from app.models.metric import Metric
    m = Metric(machine_id=machine_id, cpu_percent=over.pop("cpu_percent", 50.0), mem_percent=40.0,
               cpu_count_logical=over.pop("cpu_count_logical", 8), timestamp=quando or utcnow(), **over)
    db.add(m)
    db.commit()
    return m


class TestConduzidoPeloUsuario:
    def test_dominante_e_a_janela_ativa(self):
        from app.services import context
        assert context.is_user_driven(_proc(pid=900), 900) is True

    def test_compilador_filho_do_editor(self):
        """O compilador não é a janela, mas descende dela."""
        from app.services import context
        assert context.is_user_driven(_proc(pid=1200, name="cl.exe", ancestors=[1100, 700, 4]), 700) is True

    def test_minerador_com_nome_de_chrome_nao_descende_do_chrome(self):
        from app.services import context
        minerador = _proc(pid=4000, name="chrome.exe", ancestors=[3000, 4])
        assert context.is_user_driven(minerador, 2500) is False

    def test_sem_janela_ativa_e_desconhecido(self):
        from app.services import context
        assert context.is_user_driven(_proc(), None) is None

    def test_dominante_sem_pais_e_pid_diferente(self):
        from app.services import context
        assert context.is_user_driven(_proc(pid=900, ancestors=None), 901) is False


class TestCompute:
    def test_cpu_do_dominante_dividida_pelos_nucleos(self, db):
        from app.services import context
        m = _machine(db)
        metric = _leitura(db, m.id, cpu_count_logical=8)
        context.compute(db, metric, [_proc(cpu_percent=400.0), _proc(pid=5, name="outro.exe", cpu_percent=20.0)], {})
        assert metric.top_proc_cpu == pytest.approx(50.0)

    def test_processo_ocioso_do_windows_nao_e_dominante(self, db):
        from app.services import context
        m = _machine(db)
        metric = _leitura(db, m.id, cpu_count_logical=4)
        ocioso = _proc(pid=0, name="System Idle Process", cpu_percent=300.0)
        context.compute(db, metric, [ocioso, _proc(cpu_percent=100.0)], {})
        assert metric.top_proc_cpu == pytest.approx(25.0)

    def test_confianca_vem_dos_niveis_da_coleta(self, db):
        from app.services import context, trust
        m = _machine(db)
        metric = _leitura(db, m.id)
        jogo = _proc()
        context.compute(db, metric, [jogo], {trust.key_of(jogo): trust.Trust(level=trust.TRUSTED)})
        assert metric.top_proc_trust == trust.TRUSTED
        outra = _leitura(db, m.id)
        context.compute(db, outra, [jogo], {})
        assert outra.top_proc_trust == trust.UNKNOWN

    def test_conhecido_pelo_baseline_de_processos(self, db):
        from app.models.process_baseline import ProcessBaseline
        from app.services import context
        m = _machine(db)
        db.add(ProcessBaseline(machine_id=m.id, process_name="jogo.exe", seen_count=40, is_known=True))
        db.add(ProcessBaseline(machine_id=m.id, process_name="marcado.exe", seen_count=2, is_known=False,
                               user_marked_normal=True))
        db.commit()
        for nome, esperado in (("jogo.exe", 1), ("marcado.exe", 1), ("novo.exe", 0)):
            metric = _leitura(db, m.id)
            context.compute(db, metric, [_proc(name=nome)], {})
            assert metric.top_proc_known == esperado, nome

    def test_conduzido_vira_1_0_ou_nulo(self, db):
        from app.services import context
        m = _machine(db)
        for fg, esperado in ((900, 1), (123, 0), (None, None)):
            metric = _leitura(db, m.id, foreground_pid=fg)
            context.compute(db, metric, [_proc(pid=900)], {})
            assert metric.top_proc_user_driven == esperado, fg

    def test_oscilacao_da_cpu_nos_ultimos_10_minutos(self, db):
        from app.services import context
        m = _machine(db)
        agora = utcnow()
        _leitura(db, m.id, agora - timedelta(minutes=20), cpu_percent=99.0)  # fora da janela
        for minutos, cpu in ((9, 10.0), (5, 50.0), (1, 30.0)):
            _leitura(db, m.id, agora - timedelta(minutes=minutos), cpu_percent=cpu)
        metric = _leitura(db, m.id, agora, cpu_percent=70.0)
        context.compute(db, metric, [_proc()], {})
        assert metric.cpu_std_10m == pytest.approx(float(np.std([10.0, 50.0, 30.0, 70.0])))

    def test_gpu_sem_placa_e_nula(self, db):
        from app.services import context
        m = _machine(db)
        agora = utcnow()
        for minutos in (6, 3):
            _leitura(db, m.id, agora - timedelta(minutes=minutos))
        metric = _leitura(db, m.id, agora)
        context.compute(db, metric, [_proc()], {})
        assert metric.gpu_std_10m is None

    def test_oscilacao_da_gpu(self, db):
        from app.services import context
        m = _machine(db)
        agora = utcnow()
        cargas = (90.0, 40.0, 95.0)
        for minutos, carga in zip((6, 3, 0), cargas):
            metric = _leitura(db, m.id, agora - timedelta(minutes=minutos),
                              gpu_metrics=[{"id": 0, "name": "GPU", "load_percent": carga}])
        context.compute(db, metric, [_proc()], {})
        assert metric.gpu_std_10m == pytest.approx(float(np.std(cargas)))

    def test_sem_processos_fica_tudo_nulo(self, db):
        from app.services import context
        m = _machine(db)
        metric = _leitura(db, m.id, foreground_pid=900)
        context.compute(db, metric, [], {})
        for coluna in context.COLUMNS:
            assert getattr(metric, coluna) is None, coluna

    def test_chave_desligada_nao_preenche_nada(self, db):
        from app.services import context
        m = _machine(db)
        metric = _leitura(db, m.id, foreground_pid=900)
        anterior = context.set_context_mode(False)
        try:
            assert anterior is True
            assert context.context_on() is False
            context.compute(db, metric, [_proc(pid=900)], {})
        finally:
            assert context.set_context_mode(anterior) is False
        for coluna in context.COLUMNS:
            assert getattr(metric, coluna) is None, coluna


def test_ingestao_grava_o_contexto(client, machine, db):
    """Pelo caminho real: a leitura chega e sai do banco com o contexto."""
    from app.models.metric import Metric
    from tests.test_pipeline import _ingest, _processo
    res = _ingest(client, machine["agent_token"], cpu_percent=80.0, foreground_pid=900,
                  processes=[_processo(pid=900, name="jogo.exe", cpu_percent=480.0, ancestors=[300, 4])])
    assert res.status_code == 202
    metric = db.query(Metric).filter(Metric.machine_id == machine["id"]).order_by(Metric.id.desc()).first()
    assert metric.top_proc_user_driven == 1
    assert metric.top_proc_cpu == pytest.approx(60.0)
    assert metric.top_proc_trust is not None
