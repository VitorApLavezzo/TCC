"""Período de aprendizado: o que o sistema faz antes de conhecer a máquina.

Uma máquina recém-instalada não tem normal. Tudo que roda nela é "novo", todo
pico é "fora do padrão" — e era assim que as primeiras horas de monitoramento
enchiam a pessoa de avisos sobre programas que sempre estiveram ali.

O que aprende continua sendo detectado e registrado; o que não acontece é o
incômodo. A exceção são os avisos cuja evidência não depende de histórico
nenhum: uma isca de ransomware tocada é uma isca tocada no primeiro minuto.
"""
from datetime import timedelta

from app.core.security import get_password_hash
from app.core.timeutil import utcnow
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.user import User

_seq = iter(range(1, 10_000))


def _machine(db, **over):
    n = next(_seq)
    u = User(email=f"a{n}@t.com", username=f"u{n}", hashed_password=get_password_hash("x"))
    db.add(u)
    db.flush()
    m = Machine(name="PC", hostname="H", agent_token=f"tk-{n}", owner_id=u.id, **over)
    db.add(m)
    db.flush()
    db.commit()
    return m


def _leituras(db, machine_id, quantas, span_horas):
    """`quantas` leituras espalhadas pelas últimas `span_horas`."""
    agora = utcnow()
    passo = timedelta(hours=span_horas) / max(quantas - 1, 1)
    for i in range(quantas):
        db.add(Metric(machine_id=machine_id, cpu_percent=20, mem_percent=40,
                      timestamp=agora - timedelta(hours=span_horas) + passo * i))
    db.commit()


class TestQuandoTerminaOAprendizado:
    def test_maquina_sem_nenhuma_leitura_esta_aprendendo(self, db):
        from app.services import learning
        m = _machine(db)
        assert learning.is_learning(db, m) is True

    def test_muitas_leituras_em_pouco_tempo_ainda_e_aprendizado(self, db):
        """A régua de tempo existe para isto: no intervalo acelerado de 10 s,
        100 leituras fecham em 17 minutos, e 17 minutos não são o normal de
        ninguém. As leituras já bastam; a hora de relógio não."""
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 150, span_horas=0.3)
        assert learning.is_learning(db, m) is True

    def test_oito_horas_com_poucas_leituras_ainda_e_aprendizado(self, db):
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 12, span_horas=8)
        assert learning.is_learning(db, m) is True

    def test_leituras_e_tempo_completos_encerram_o_aprendizado(self, db):
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 150, span_horas=2)
        assert learning.is_learning(db, m) is False

    def test_conta_da_primeira_leitura_e_nao_do_cadastro(self, db):
        """Máquina cadastrada na sexta cujo agente só sobe na segunda não pode
        'se formar' com zero dado só porque o relógio andou."""
        from app.services import learning
        m = _machine(db)
        m.created_at = utcnow() - timedelta(days=3)
        db.commit()
        _leituras(db, m.id, 150, span_horas=0.3)
        assert learning.is_learning(db, m) is True

    def test_maquina_de_demonstracao_nunca_esta_aprendendo(self, db):
        """A demonstração tem 8 a 20 passos de aquecimento e precisa detectar."""
        from app.services import learning
        m = _machine(db, is_demo=True)
        assert learning.is_learning(db, m) is False

    def test_status_informa_o_progresso_das_duas_reguas(self, db):
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 40, span_horas=2)
        s = learning.status(db, m)
        assert s.collected == 40
        assert s.needed == learning.NEEDED_SAMPLES
        assert 1.5 < s.hours < 2.5
        assert s.learning is True


class TestAvisosDuranteOAprendizado:
    def _candidato(self, tipo="unknown_process", severidade="medium"):
        from app.services.anomaly_service import Candidate
        return Candidate(anomaly_type=tipo, severity=severidade, responsible="algo.exe")

    def test_anomalia_e_registrada_mas_marcada(self, db):
        from app.services.anomaly_service import persist_candidate
        m = _machine(db)
        a = persist_candidate(db, m, self._candidato())
        assert a is not None
        assert a.during_learning is True

    def test_anomalia_durante_aprendizado_nao_notifica(self, db):
        from app.models.notification import Notification
        from app.services.anomaly_service import persist_candidate
        m = _machine(db)
        a = persist_candidate(db, m, self._candidato())
        n = db.query(Notification).filter(Notification.anomaly_id == a.id).first()
        assert n is not None
        assert n.status == "suppressed"
        assert "aprend" in (n.status_reason or "")

    def test_isca_de_ransomware_notifica_mesmo_aprendendo(self, db):
        from app.models.notification import Notification
        from app.services.anomaly_service import persist_candidate
        m = _machine(db)
        a = persist_candidate(db, m, self._candidato("ransomware_canary", "critical"))
        n = db.query(Notification).filter(Notification.anomaly_id == a.id).first()
        assert a.during_learning is False
        assert n.status == "pending"

    def test_maquina_formada_notifica_normalmente(self, db):
        from app.models.notification import Notification
        from app.services.anomaly_service import persist_candidate
        m = _machine(db)
        _leituras(db, m.id, 150, span_horas=7)
        a = persist_candidate(db, m, self._candidato(severidade="high"))
        n = db.query(Notification).filter(Notification.anomaly_id == a.id).first()
        assert a.during_learning is False
        assert n.status == "pending"


class TestDetectoresDuranteOAprendizado:
    def test_processo_desconhecido_nao_dispara_enquanto_tudo_e_desconhecido(self, db):
        from app.models.process_baseline import ProcessBaseline
        from app.services.behavior_analyzer import DetectionContext, detect_new_suspicious_process
        from types import SimpleNamespace
        m = _machine(db)
        db.add(ProcessBaseline(machine_id=m.id, process_name="explorer.exe", seen_count=30, is_known=True))
        met = Metric(machine_id=m.id, cpu_percent=30, mem_percent=40)
        db.add(met)
        db.commit()
        proc = SimpleNamespace(name="jogo.exe", exe="C:\\Games\\jogo.exe", signed="unsigned", publisher=None,
                               sha256=None, cpu_percent=50.0, mem_percent=8.0, username="x",
                               cmdline="jogo.exe", pid=7, ppid=4, parent_name="explorer.exe")
        assert detect_new_suspicious_process(met, [proc], [], db, DetectionContext(learning=True)) is None

    def test_minerador_dispara_mesmo_durante_o_aprendizado(self, db):
        from app.models.process_baseline import ProcessBaseline
        from app.services.behavior_analyzer import DetectionContext, detect_new_suspicious_process
        from types import SimpleNamespace
        m = _machine(db)
        db.add(ProcessBaseline(machine_id=m.id, process_name="explorer.exe", seen_count=30, is_known=True))
        met = Metric(machine_id=m.id, cpu_percent=30, mem_percent=40)
        db.add(met)
        db.commit()
        proc = SimpleNamespace(name="xmrig.exe", exe="C:\\Users\\x\\xmrig.exe", signed="unsigned", publisher=None,
                               sha256=None, cpu_percent=95.0, mem_percent=8.0, username="x",
                               cmdline="xmrig.exe", pid=7, ppid=4, parent_name="explorer.exe")
        r = detect_new_suspicious_process(met, [proc], [], db, DetectionContext(learning=True))
        assert r is not None and r.anomaly_type == "suspicious_process"


class TestComoOProgressoEDito:
    """Uma barra de progresso que passa de 100% não informa, assusta."""

    def test_nao_anuncia_mais_leituras_do_que_a_meta(self, db):
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 186, span_horas=0.28)  # coleta a cada 5s
        frase = learning.status(db, m).phrase
        assert "186 de 100" not in frase
        assert "100" not in frase

    def test_diz_quanto_tempo_falta_quando_as_leituras_ja_bastam(self, db):
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 186, span_horas=0.28)
        frase = learning.status(db, m).phrase
        assert "falta" in frase and "min" in frase
        assert "leituras" not in frase

    def test_diz_quantas_leituras_faltam_quando_o_tempo_ja_basta(self, db):
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 30, span_horas=8)
        frase = learning.status(db, m).phrase
        assert "70 leituras" in frase
        assert "h" not in frase.replace("leituras", "")

    def test_menciona_os_dois_quando_os_dois_faltam(self, db):
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 40, span_horas=0.5)
        frase = learning.status(db, m).phrase
        assert "60 leituras" in frase and "30 min" in frase

    def test_menos_de_uma_hora_aparece_em_minutos(self, db):
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 200, span_horas=0.9)
        frase = learning.status(db, m).phrase
        assert "min" in frase and "0h" not in frase

    def test_maquina_formada_nao_tem_frase(self, db):
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 150, span_horas=2)
        assert learning.status(db, m).phrase == ""


class TestCriteriosSeparados:
    """A tela mostra os dois critérios como itens que se completam, então
    cada um precisa saber sozinho se já bateu e quanto ainda falta."""

    def test_leituras_completas_e_tempo_pendente(self, db):
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 209, span_horas=0.3)
        d = learning.status(db, m).as_dict()
        assert d["samples_done"] is True
        assert d["hours_done"] is False
        assert d["remaining_hours_label"] == "45 min"

    def test_tempo_completo_e_leituras_pendentes(self, db):
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 30, span_horas=8)
        d = learning.status(db, m).as_dict()
        assert d["samples_done"] is False
        assert d["hours_done"] is True
        assert d["remaining_samples"] == 70

    def test_rotulo_de_tempo_em_minutos_perto_do_fim(self, db):
        from app.services import learning
        m = _machine(db)
        _leituras(db, m.id, 200, span_horas=0.9)
        assert "min" in learning.status(db, m).as_dict()["remaining_hours_label"]
