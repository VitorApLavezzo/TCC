"""O cartão "e se eu fechar?" só pode falar do que tem a ver com o aviso.

Caso real (anomalia #357): um aviso de rede sem processo responsável sugeria
fechar o navegador, só por ser o maior consumidor de memória.
"""
from types import SimpleNamespace


def _metric(**over):
    base = {"cpu_percent": 40.0, "mem_percent": 16.0, "cpu_count_logical": 8}
    return SimpleNamespace(**{**base, **over})


def _groups():
    return [
        {"name": "opera", "cpu": 30.0, "mem": 6.0, "rss": 2e9, "instances": 6},
        {"name": "Code.exe", "cpu": 12.0, "mem": 4.0, "rss": 1.3e9, "instances": 3},
    ]


def _anomaly(kind, responsible=None):
    return SimpleNamespace(anomaly_type=kind, responsible_process=responsible)


class TestWhenCardShouldNotAppear:
    def test_no_responsible_process_does_not_pick_any(self):
        """O caso da anomalia #357: nenhum responsável identificado."""
        from app.services.ai_service import counterfactual
        assert counterfactual(_anomaly("ddos_indicator"), _metric(), _groups()) is None

    def test_network_alert_gets_no_memory_card(self):
        """Fechar o navegador não faz nada por um pico de tráfego."""
        from app.services.ai_service import counterfactual
        assert counterfactual(_anomaly("network_spike", "opera"), _metric(), _groups()) is None

    def test_disk_alert_gets_no_memory_card(self):
        from app.services.ai_service import counterfactual
        assert counterfactual(_anomaly("disk_activity", "opera"), _metric(), _groups()) is None

    def test_security_alert_does_not_suggest_freeing_memory(self):
        """"Feche o vírus e ganhe 2 GB" é a moldura errada para uma ameaça."""
        from app.services.ai_service import counterfactual
        assert counterfactual(_anomaly("malware_pattern", "opera"), _metric(), _groups()) is None

    def test_responsible_not_in_list_does_not_become_largest(self):
        from app.services.ai_service import counterfactual
        assert counterfactual(_anomaly("high_memory", "sumiu.exe"), _metric(), _groups()) is None


class TestWhenCardHelps:
    def test_high_memory_keeps_card(self):
        from app.services.ai_service import counterfactual
        cf = counterfactual(_anomaly("high_memory", "opera"), _metric(), _groups())
        assert cf is not None and cf["process"] == "opera"
        assert "memória" in cf["sentence"]

    def test_high_cpu_keeps_card(self):
        from app.services.ai_service import counterfactual
        # 80% somados em 8 núcleos = 10% do computador: acima do limiar em que
        # vale a pena dizer que fechar alivia o processador
        heavy = [{"name": "opera", "cpu": 80.0, "mem": 6.0, "rss": 2e9, "instances": 6}]
        cf = counterfactual(_anomaly("high_cpu", "opera"), _metric(), heavy)
        assert cf is not None and "processador" in cf["sentence"]

    def test_thermal_throttling_also_relieved_by_closing(self):
        from app.services.ai_service import counterfactual
        assert counterfactual(_anomaly("thermal_throttling", "opera"), _metric(), _groups()) is not None


class TestThroughRealPath:
    """O que chega na tela é o que `build_context` monta; aqui apareceria um erro de fiação."""

    def _scenario(self, db, kind, responsible=None):
        from app.core.security import get_password_hash
        from app.models.anomaly import Anomaly
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.models.process import ProcessSnapshot
        from app.models.user import User

        u = User(email=f"cf{kind}@t.com", username=f"cf{kind}", hashed_password=get_password_hash("x"))
        db.add(u)
        db.flush()
        m = Machine(name="PC", hostname="H", agent_token=f"tok-cf-{kind}", owner_id=u.id, os_type="Windows")
        db.add(m)
        db.flush()
        met = Metric(machine_id=m.id, cpu_percent=40, mem_percent=16, cpu_count_logical=8)
        db.add(met)
        db.flush()
        # Opera é o maior consumidor de memória — o isco do bug original
        for i in range(6):
            db.add(ProcessSnapshot(metric_id=met.id, pid=100 + i, name="opera", cpu_percent=5.0,
                                   mem_percent=1.0, mem_rss=3.3e8, num_threads=10, status="running"))
        a = Anomaly(machine_id=m.id, metric_id=met.id, anomaly_type=kind, severity="high",
                    responsible_process=responsible)
        db.add(a)
        db.commit()
        return a, met, m

    def test_network_alert_without_responsible_gets_no_card(self, db):
        from app.services.ai_service import build_context
        a, met, m = self._scenario(db, "ddos_indicator")
        assert build_context(db, a, met, m)["counterfactual"] is None

    def test_memory_alert_gets_card_for_right_program(self, db):
        from app.services.ai_service import build_context
        a, met, m = self._scenario(db, "high_memory", responsible="opera")
        cf = build_context(db, a, met, m)["counterfactual"]
        assert cf is not None and cf["process"] == "opera"
