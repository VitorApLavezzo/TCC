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


class TestJanelaDoShell:
    """Quase tudo descende do explorer.exe — inclusive o que roda sozinho desde o login."""

    def test_filho_do_explorer_nao_e_conduzido_quando_a_janela_e_o_explorer(self):
        from app.services import context
        minerador = _proc(pid=4000, name="svc_update.exe", ancestors=[1500, 4])
        assert context.is_user_driven(minerador, 1500, "explorer.exe") is False

    def test_o_proprio_explorer_na_frente_e_conduzido(self):
        from app.services import context
        assert context.is_user_driven(_proc(pid=1500, name="explorer.exe"), 1500, "Explorer.EXE") is True

    def test_compute_usa_o_nome_da_janela(self, db):
        from app.services import context
        m = _machine(db)
        metric = _leitura(db, m.id, foreground_pid=1500, foreground_name="explorer.exe")
        context.compute(db, metric, [_proc(pid=4000, name="svc_update.exe", ancestors=[1500, 4])], {})
        assert metric.top_proc_user_driven == 0


def _ctx_leitura(idle=None, fg=None, fg_name=None):
    return SimpleNamespace(user_idle_seconds=idle, foreground_pid=fg, foreground_name=fg_name)


class TestGravidadePeloContexto:
    """Uma linha da tabela da spec por teste."""

    def test_presente_e_conduzido_vira_baixa(self):
        from app.services import anomaly_service as a
        assert a.context_severity("high_cpu", "high", _ctx_leitura(idle=10, fg=900), _proc(pid=900), 0) == ("low", True)

    def test_presente_mas_ausente_ha_mais_de_dois_minutos_mantem(self):
        from app.services import anomaly_service as a
        assert a.context_severity("high_cpu", "high", _ctx_leitura(idle=600, fg=900), _proc(pid=900), 0) == ("high", False)

    def test_segundo_plano_confiavel_ou_de_seguranca_vira_baixa(self):
        from app.services import anomaly_service as a
        for nivel in (2, 3):
            r = a.context_severity("background_load", "high", _ctx_leitura(idle=10, fg=1), _proc(pid=900), nivel)
            assert r == ("low", False), nivel

    def test_segundo_plano_comum_no_maximo_media(self):
        from app.services import anomaly_service as a
        leitura = _ctx_leitura(idle=10, fg=1)
        assert a.context_severity("background_load", "high", leitura, _proc(pid=900), 1) == ("medium", False)
        assert a.context_severity("background_load", "low", leitura, _proc(pid=900), 1) == ("low", False)

    def test_segundo_plano_desconhecido_mantem(self):
        from app.services import anomaly_service as a
        r = a.context_severity("background_load", "high", _ctx_leitura(idle=10, fg=1), _proc(pid=900), 0)
        assert r == ("high", False)

    def test_sem_contexto_mantem(self):
        from app.services import anomaly_service as a
        assert a.context_severity("high_cpu", "high", _ctx_leitura(), _proc(pid=900), 2) == ("high", False)
        assert a.context_severity("high_cpu", "high", _ctx_leitura(idle=10, fg=900), None, 2) == ("high", False)

    def test_ferramenta_do_windows_usada_por_ataque_nao_e_rebaixada_por_confianca(self):
        from app.services import anomaly_service as a
        rundll = _proc(pid=900, name="rundll32.exe", exe="C:\\Windows\\System32\\rundll32.exe")
        r = a.context_severity("background_load", "high", _ctx_leitura(idle=10, fg=1), rundll, 2)
        assert r == ("high", False)

    def test_seguranca_e_vazamento_ficam_intocados(self):
        from app.services import anomaly_service as a
        leitura = _ctx_leitura(idle=10, fg=900)
        for tipo in ("unknown_process", "memory_leak", "process_masquerading"):
            assert a.context_severity(tipo, "high", leitura, _proc(pid=900), 3) == ("high", False), tipo

    def test_contexto_desligado_e_identidade(self):
        from app.services import anomaly_service as a
        from app.services import context
        anterior = context.set_context_mode(False)
        try:
            r = a.context_severity("high_cpu", "high", _ctx_leitura(idle=10, fg=900), _proc(pid=900), 3)
            assert r == ("high", False)
        finally:
            context.set_context_mode(anterior)

    def test_tipos_de_carga(self):
        from app.services import anomaly_service as a
        assert a.LOAD_TYPES == {"high_cpu", "background_load", "gpu_anomaly", "resource_abuse",
                                "resource_exhaustion", "cpu_loop", "thermal_throttling", "behavioral_anomaly"}


def _jogo_na_tela(client, machine):
    from tests.test_pipeline import _ingest, _processo
    jogo = _processo(pid=900, name="jogo.exe", cpu_percent=760.0, signed="unsigned", publisher=None,
                     exe="D:\\Jogos\\jogo.exe", ancestors=[300, 4])
    res = _ingest(client, machine["agent_token"], cpu_percent=97.0, user_idle_seconds=5.0,
                  foreground_pid=900, foreground_name="jogo.exe", processes=[jogo])
    assert res.status_code == 202


def test_ponta_a_ponta_detector_com_o_jogo_na_tela(client, machine, db, monkeypatch):
    """O candidato de um detector passa pelo contexto antes de virar aviso."""
    from app.models.anomaly import Anomaly
    from app.services import anomaly_service, behavior_analyzer
    achado = behavior_analyzer.BehaviorAnalysis()
    achado.anomaly_type, achado.severity, achado.confidence = "cpu_loop", "high", 0.9
    achado.responsible_process = "jogo.exe"
    achado.detector = "cpu_loop"
    monkeypatch.setattr(anomaly_service, "analyze_behavior", lambda *a, **k: [achado])
    monkeypatch.setattr(anomaly_service.learning, "is_learning", lambda *a, **k: False)
    _jogo_na_tela(client, machine)
    aviso = db.query(Anomaly).filter(Anomaly.machine_id == machine["id"]).one()
    assert (aviso.anomaly_type, aviso.severity, aviso.user_driven) == ("cpu_loop", "low", True)


def test_ponta_a_ponta_modelo_com_o_jogo_na_tela(client, machine, db, monkeypatch):
    """O candidato do modelo também: duas leituras fora do padrão com o jogo na frente."""
    from app.models.anomaly import Anomaly
    from app.services import anomaly_service, ml_service
    monkeypatch.setattr(anomaly_service, "analyze_behavior", lambda *a, **k: [])
    monkeypatch.setattr(anomaly_service.learning, "is_learning", lambda *a, **k: False)
    monkeypatch.setattr(ml_service, "predict_anomaly", lambda *a, **k: (True, -0.4))
    monkeypatch.setattr(ml_service, "alert_threshold", lambda *a, **k: -0.1)
    _jogo_na_tela(client, machine)
    _jogo_na_tela(client, machine)
    aviso = db.query(Anomaly).filter(Anomaly.machine_id == machine["id"]).one()
    assert (aviso.anomaly_type, aviso.severity, aviso.user_driven) == ("high_cpu", "low", True)
