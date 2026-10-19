"""
Testes das funcionalidades novas.

Poucos e escolhidos: cada um cobre a parte em que o erro seria silencioso —
um limite que não limita, uma cadeia de auditoria que aceita adulteração, uma
automação que age quando não devia, uma conta estatística trocada.
"""
import time
from datetime import timedelta

from app.core import ratelimit
from app.core.timeutil import utcnow
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.mlhealth import ExplanationOutcome
from app.models.playbook import Playbook, PlaybookRun
from app.services import drift, fidelity, hardware_risk, integrity, playbooks, study


class TestLimiteDeTentativas:
    def test_libera_ate_o_teto_e_bloqueia_depois(self):
        ratelimit.reset()
        for _ in range(3):
            assert ratelimit.check("teste", times=3, seconds=60) == 0
        # A quarta tentativa na mesma janela é recusada, com o tempo de espera
        assert ratelimit.check("teste", times=3, seconds=60) > 0

    def test_janela_desliza(self):
        ratelimit.reset()
        agora = time.monotonic()
        ratelimit.check("desliza", 1, 10, now=agora)
        assert ratelimit.check("desliza", 1, 10, now=agora + 1) > 0
        # Passada a janela, a tentativa antiga não conta mais
        assert ratelimit.check("desliza", 1, 10, now=agora + 11) == 0

    def test_login_responde_429_depois_de_muitas_tentativas(self, client):
        ratelimit.reset()
        for _ in range(10):
            client.post("/api/auth/login", data={"username": "ninguem", "password": "errada"})
        resposta = client.post("/api/auth/login", data={"username": "ninguem", "password": "errada"})
        assert resposta.status_code == 429
        assert "Retry-After" in resposta.headers


class TestLivroDeAuditoria:
    def test_cadeia_integra_e_verificavel(self, db):
        for i in range(3):
            integrity.append(db, kind="anomaly", ref_id=i, payload={"tipo": "high_cpu", "i": i})
        resultado = integrity.verify(db)
        assert resultado["ok"] is True
        assert resultado["entries"] == 3

    def test_adulteracao_quebra_a_cadeia(self, db):
        integrity.append(db, kind="anomaly", ref_id=1, payload={"tipo": "high_cpu"})
        alvo = integrity.append(db, kind="action", ref_id=2, payload={"comando": "kill_process"})
        integrity.append(db, kind="anomaly", ref_id=3, payload={"tipo": "disk_full"})

        # Alguém edita o registro do meio direto no banco
        alvo.payload = {"comando": "clean_temp"}
        db.commit()

        resultado = integrity.verify(db)
        assert resultado["ok"] is False
        assert resultado["broken_at"] == alvo.id

    def test_data_nao_entra_no_selo(self, db):
        """O selo não pode depender da coluna de data.

        PostgreSQL devolve com fuso e SQLite sem: se a data entrasse no hash,
        o mesmo livro seria íntegro num banco e adulterado no outro.
        """
        entrada = integrity.append(db, kind="anomaly", ref_id=9, payload={"tipo": "high_cpu"})
        db.expire_all()
        assert integrity.verify(db)["ok"] is True
        assert entrada.payload["_at"]  # a hora é lacrada dentro do conteúdo


class TestDeriva:
    def test_distribuicoes_iguais_nao_derivam(self):
        import numpy as np
        rng = np.random.default_rng(1)
        a = rng.normal(40, 5, 500)
        b = rng.normal(40, 5, 500)
        assert drift.jensen_shannon(a, b) < 0.1

    def test_maquina_que_mudou_de_uso_deriva(self):
        import numpy as np
        rng = np.random.default_rng(1)
        antes = rng.normal(20, 4, 500)     # máquina ociosa
        depois = rng.normal(85, 4, 500)    # virou servidor
        assert drift.jensen_shannon(antes, depois) > 0.8

    def test_niveis_seguem_os_limites_configurados(self):
        assert drift._level(0.05) == "ok"
        assert drift._level(0.25) == "warn"
        assert drift._level(0.90) == "critical"


class TestRiscoDeHardware:
    def test_disco_com_setores_pendentes_vira_risco_alto(self):
        fatores = hardware_risk._disk_factors(
            {"device": "C:", "pending_sectors": 4, "reallocated_sectors": 30,
             "power_on_hours": 45000, "temperature": 56},
            erros_recentes=1,
        )
        risco = hardware_risk._risk_from_weights([f["peso"] for f in fatores])
        assert risco > 0.4
        assert hardware_risk._level(risco) in ("alto", "critico")

    def test_disco_saudavel_nao_assusta_ninguem(self):
        fatores = hardware_risk._disk_factors(
            {"device": "C:", "health": "ok", "pending_sectors": 0, "reallocated_sectors": 0,
             "power_on_hours": 4000, "temperature": 35},
            erros_recentes=0,
        )
        risco = hardware_risk._risk_from_weights([f["peso"] for f in fatores])
        assert risco == 0.0
        assert hardware_risk._level(risco) == "baixo"


class TestFidelidadeDaPrevisao:
    def _preparar(self, db, machine_id, previsto):
        from app.models.anomaly import Anomaly
        from app.models.explanation import AIExplanation

        anomaly = Anomaly(machine_id=machine_id, anomaly_type="high_memory", severity="high",
                          detected_at=utcnow(), responsible_process="chrome.exe")
        db.add(anomaly)
        db.flush()
        db.add(AIExplanation(anomaly_id=anomaly.id, summary="...", model_used="ollama",
                             counterfactual={"process": "chrome.exe", "mem_now": 91.0,
                                             "mem_after": previsto, "cpu_now": 20.0, "cpu_after": 19.0}))
        db.commit()
        return anomaly

    def test_previsao_confirmada_conta_como_acerto(self, db, machine):
        anomaly = self._preparar(db, machine["id"], previsto=48.0)
        fidelity.register_from_action(db, anomaly.id, machine["id"], "kill_process")

        # A leitura seguinte mostra a memória onde a IA disse que ficaria
        db.add(Metric(machine_id=machine["id"], timestamp=utcnow(), cpu_percent=20, mem_percent=50.0,
                      mem_used=1, mem_available=1, mem_total=2, disk_used=1, disk_free=1, disk_percent=10,
                      disk_read_bytes=0, disk_write_bytes=0, net_bytes_sent=0, net_bytes_recv=0,
                      net_connections=10, uptime_seconds=100))
        db.commit()

        outcome = db.query(ExplanationOutcome).first()
        # A medição só acontece depois de alguns minutos: envelhece o registro
        outcome.created_at = utcnow() - timedelta(minutes=10)
        db.commit()

        assert fidelity.measure_pending(db) == 1
        db.refresh(outcome)
        assert outcome.status == "measured"
        assert outcome.hit is True

    def test_previsao_muito_errada_nao_conta_como_acerto(self, db, machine):
        anomaly = self._preparar(db, machine["id"], previsto=40.0)
        fidelity.register_from_action(db, anomaly.id, machine["id"], "kill_process")
        db.add(Metric(machine_id=machine["id"], timestamp=utcnow(), cpu_percent=20, mem_percent=88.0,
                      mem_used=1, mem_available=1, mem_total=2, disk_used=1, disk_free=1, disk_percent=10,
                      disk_read_bytes=0, disk_write_bytes=0, net_bytes_sent=0, net_bytes_recv=0,
                      net_connections=10, uptime_seconds=100))
        db.commit()
        outcome = db.query(ExplanationOutcome).first()
        outcome.created_at = utcnow() - timedelta(minutes=10)
        db.commit()

        fidelity.measure_pending(db)
        db.refresh(outcome)
        assert outcome.hit is False


class TestAutomacao:
    def _regra(self, db, user_id, machine_id, autonomia, dry_run=False):
        playbook = Playbook(user_id=user_id, machine_id=machine_id, name="Fechar o chrome",
                            anomaly_type="high_memory", action="kill_process",
                            autonomy=autonomia, dry_run=dry_run, cooldown_minutes=5, enabled=True)
        db.add(playbook)
        db.commit()
        return playbook

    def _aviso(self, db, machine_id):
        from app.models.anomaly import Anomaly
        anomaly = Anomaly(machine_id=machine_id, anomaly_type="high_memory", severity="high",
                          detected_at=utcnow(), responsible_process="chrome.exe")
        db.add(anomaly)
        db.commit()
        return anomaly

    def test_regra_timida_apenas_sugere(self, db, machine):
        maquina = db.query(Machine).filter(Machine.id == machine["id"]).first()
        self._regra(db, maquina.owner_id, maquina.id, "sugerir")
        disparos = playbooks.on_anomaly(db, maquina, self._aviso(db, maquina.id))
        assert [d.status for d in disparos] == ["sugerido"]
        # Sugerir não manda comando nenhum para a máquina
        assert db.query(PlaybookRun).first().command_id is None

    def test_regra_automatica_espera_a_janela_de_arrependimento(self, db, machine):
        maquina = db.query(Machine).filter(Machine.id == machine["id"]).first()
        self._regra(db, maquina.owner_id, maquina.id, "automatico")
        disparo = playbooks.on_anomaly(db, maquina, self._aviso(db, maquina.id))[0]
        assert disparo.status == "agendado"
        assert disparo.undo_until is not None

        # Enquanto a janela não vence, nada acontece
        assert playbooks.dispatch_due(db) == 0
        disparo.undo_until = utcnow() - timedelta(seconds=1)
        db.commit()
        assert playbooks.dispatch_due(db) == 1
        db.refresh(disparo)
        assert disparo.status == "executado"
        assert disparo.command_id is not None

    def test_cancelar_a_tempo_impede_a_acao(self, db, machine):
        maquina = db.query(Machine).filter(Machine.id == machine["id"]).first()
        self._regra(db, maquina.owner_id, maquina.id, "automatico")
        disparo = playbooks.on_anomaly(db, maquina, self._aviso(db, maquina.id))[0]
        playbooks.decide(db, disparo, aceitar=False, user_id=maquina.owner_id)
        assert disparo.status == "desfeito"
        assert disparo.command_id is None

    def test_ensaio_registra_sem_fazer(self, db, machine):
        maquina = db.query(Machine).filter(Machine.id == machine["id"]).first()
        self._regra(db, maquina.owner_id, maquina.id, "automatico", dry_run=True)
        disparo = playbooks.on_anomaly(db, maquina, self._aviso(db, maquina.id))[0]
        assert disparo.status == "ensaio"
        assert disparo.command_id is None

    def test_sem_programa_responsavel_nao_ha_o_que_encerrar(self, db, machine):
        from app.models.anomaly import Anomaly
        maquina = db.query(Machine).filter(Machine.id == machine["id"]).first()
        self._regra(db, maquina.owner_id, maquina.id, "automatico")
        anomaly = Anomaly(machine_id=maquina.id, anomaly_type="high_memory", severity="high",
                          detected_at=utcnow(), responsible_process=None)
        db.add(anomaly)
        db.commit()
        disparo = playbooks.on_anomaly(db, maquina, anomaly)[0]
        assert disparo.status == "bloqueado"


class TestEstudoComPessoas:
    def test_nota_sus_segue_a_formula_de_brooke(self):
        # Todas as respostas no melhor valor possível: 5 nas positivas (ímpares)
        # e 1 nas negativas (pares) dão 100.
        melhor = [5, 1, 5, 1, 5, 1, 5, 1, 5, 1]
        assert study.sus_score(melhor) == 100.0
        pior = [1, 5, 1, 5, 1, 5, 1, 5, 1, 5]
        assert study.sus_score(pior) == 0.0
        # Tudo no meio da escala dá exatamente a metade
        assert study.sus_score([3] * 10) == 50.0

    def test_teste_de_proporcoes_reconhece_diferenca_grande(self):
        # 90 de 100 contra 40 de 100 não é acaso
        p = study._two_proportion_p(90, 100, 40, 100)
        assert p is not None and p < 0.01
        # 51 contra 49 é empate
        assert study._two_proportion_p(51, 100, 49, 100) > 0.05


class TestObservabilidade:
    def test_metrics_responde_no_formato_do_prometheus(self, client):
        from app.core import observability
        observability.inc("anomalydetect_scheduler_runs_total", {"routine": "teste", "result": "ok"})
        resposta = client.get("/metrics")
        assert resposta.status_code == 200
        assert "anomalydetect_scheduler_runs_total" in resposta.text
        assert "# TYPE" in resposta.text


class TestCamadasDeDeteccao:
    def test_troca_de_camada_e_reversivel(self):
        from app.services import anomaly_service
        anterior = anomaly_service.set_detection_layer("regras")
        try:
            assert anomaly_service.detection_layer() == "regras"
        finally:
            anomaly_service.set_detection_layer(anterior)
        assert anomaly_service.detection_layer() == "ambas"


LEITURA = {
    "cpu_percent": 12.0, "mem_used": 1.0, "mem_available": 1.0, "mem_percent": 40.0, "mem_total": 2.0,
    "disk_used": 1.0, "disk_free": 1.0, "disk_percent": 30.0, "disk_read_bytes": 0.0,
    "disk_write_bytes": 0.0, "net_bytes_sent": 0.0, "net_bytes_recv": 0.0, "net_connections": 10,
    "uptime_seconds": 1000.0, "process_count": 120,
}


class TestFilaDoAgente:
    """A fila do agente devolve leituras antigas quando a conexão volta."""

    def test_leitura_atrasada_entra_com_a_hora_em_que_foi_feita(self, client, machine, db):
        # Uma leitura guardada enquanto o servidor estava fora não pode chegar
        # com o horário da reconexão: isso inventaria um pico que nunca houve.
        feita_em = utcnow() - timedelta(hours=2)
        resposta = client.post("/api/metrics/ingest",
                               json={**LEITURA, "collected_at": feita_em.timestamp()},
                               headers={"X-Agent-Token": machine["agent_token"]})
        assert resposta.status_code == 202

        gravada = db.query(Metric).order_by(Metric.id.desc()).first()
        assert abs((gravada.timestamp.replace(tzinfo=None) - feita_em.replace(tzinfo=None)).total_seconds()) < 5

    def test_data_absurda_e_ignorada(self, client, machine, db):
        # Relógio errado na máquina monitorada não pode reescrever o histórico
        antiga = utcnow() - timedelta(days=400)
        client.post("/api/metrics/ingest",
                    json={**LEITURA, "collected_at": antiga.timestamp()},
                    headers={"X-Agent-Token": machine["agent_token"]})
        gravada = db.query(Metric).order_by(Metric.id.desc()).first()
        assert gravada.timestamp.replace(tzinfo=None) > (utcnow() - timedelta(hours=1)).replace(tzinfo=None)


class TestGuardaLocalDoAgente:
    """O agente não fica cego quando o servidor cai (agent/localguard.py)."""

    def _guard(self):
        import os
        import sys
        from tests._caminhos import AGENT_DIR
        sys.path.insert(0, AGENT_DIR)
        from localguard import LocalGuard
        return LocalGuard()

    def test_pico_sustentado_vira_achado_local(self):
        guard = self._guard()
        for _ in range(60):
            guard.observe({"cpu_percent": 10.0, "mem_percent": 30.0, "disk_percent": 40.0})
        achados = []
        for _ in range(3):
            achados = guard.check({"cpu_percent": 99.0, "mem_percent": 30.0, "disk_percent": 40.0})
        assert any(a["metric"] == "cpu_percent" for a in achados)

    def test_leitura_normal_nao_alarma(self):
        guard = self._guard()
        for _ in range(60):
            guard.observe({"cpu_percent": 10.0, "mem_percent": 30.0, "disk_percent": 40.0})
        assert guard.check({"cpu_percent": 12.0, "mem_percent": 31.0, "disk_percent": 40.0}) == []


class TestRemocaoDeMaquina:
    """A remoção precisa dar conta das tabelas novas.

    O benchmark cria uma máquina efêmera por cenário e a apaga no fim. Quando
    uma tabela nova aponta para a máquina (ou para os avisos dela) e a remoção
    não solta a referência, o Postgres recusa o delete, a máquina fica para
    trás e o painel enche de computadores "[BENCH]" com avisos sintéticos.
    """

    def test_apaga_tudo_e_preserva_o_livro(self, db, machine):
        from app.models.anomaly import Anomaly
        from app.models.hardware import HardwareRisk
        from app.models.ledger import LedgerEntry
        from app.models.mlhealth import DriftCheck
        from app.routers.machines import delete_machine_cascade

        maquina = db.query(Machine).filter(Machine.id == machine["id"]).first()
        anomaly = Anomaly(machine_id=maquina.id, anomaly_type="high_cpu", severity="medium",
                          detected_at=utcnow())
        db.add(anomaly)
        db.add(DriftCheck(machine_id=maquina.id, distance=0.1, level="ok"))
        db.add(HardwareRisk(machine_id=maquina.id, component="disk:C", risk_pct=5.0, level="baixo"))
        db.commit()
        integrity.append(db, kind="anomaly", ref_id=anomaly.id, machine_id=maquina.id,
                         payload={"tipo": "high_cpu"})

        delete_machine_cascade(maquina.id, db)

        assert db.query(Machine).filter(Machine.id == machine["id"]).first() is None
        assert db.query(Anomaly).filter(Anomaly.machine_id == machine["id"]).count() == 0
        assert db.query(DriftCheck).count() == 0
        assert db.query(HardwareRisk).count() == 0

        # O registro lacrado sobrevive, sem o ponteiro para a máquina que já
        # não existe — e a cadeia continua conferindo.
        entrada = db.query(LedgerEntry).first()
        assert entrada is not None and entrada.machine_id is None
        assert integrity.verify(db)["ok"] is True

        # E a própria remoção fica registrada: sem isso, apagar um computador
        # levava junto qualquer rastro de que ele existiu.
        remocao = db.query(LedgerEntry).filter(LedgerEntry.kind == "machine_removed").first()
        assert remocao is not None
        assert remocao.payload["avisos_apagados"] == 1

    def test_maquina_de_benchmark_nao_entra_no_livro(self, db, machine):
        maquina = db.query(Machine).filter(Machine.id == machine["id"]).first()
        assert integrity.is_auditable(maquina) is True
        maquina.name = "[BENCH] Cenário sintético"
        assert integrity.is_auditable(maquina) is False


class TestLimpezaDoBenchmark:
    """A máquina efêmera some mesmo quando o cenário quebra no meio."""

    def test_cenario_interrompido_nao_deixa_maquina_no_painel(self, db, machine, monkeypatch):
        from app.services import benchmark

        dono = db.query(Machine).filter(Machine.id == machine["id"]).first().owner_id

        def some_e_explode(db_, maquina, *args, **kwargs):
            # Reproduz o caso real: a linha da máquina já não está lá quando o
            # `finally` roda. Antes, ler `maquina.id` ali levantava
            # ObjectDeletedError, a rodada inteira morria e as máquinas
            # efêmeras ficavam no painel.
            db_.query(Machine).filter(Machine.id == maquina.id).delete(synchronize_session=False)
            db_.commit()
            raise RuntimeError("falha simulada no meio do cenário")

        monkeypatch.setattr(benchmark, "_feed", some_e_explode)
        nome = next(iter(benchmark.scenarios()))

        resultado = benchmark.run_scenario(db, nome, dono)

        assert resultado.error  # o cenário falhou, e isso fica registrado
        # ... mas nada sobrou para o usuário ver
        assert db.query(Machine).filter(Machine.name.like(f"{benchmark.BENCH_PREFIX}%")).count() == 0


class TestBenchmarkNaoDeixaSobra:
    """A limpeza da máquina efêmera não pode depender do objeto em memória."""

    def test_cenario_que_falha_no_meio_ainda_limpa(self, db, monkeypatch, client, auth):
        from app.models.user import User
        from app.services import benchmark

        user_id = db.query(User.id).first()[0]
        nome = list(benchmark.scenarios().keys())[0]

        def _feed_que_apaga_a_maquina(db_, machine, *args, **kwargs):
            # Reproduz o caso real: a linha some (contêiner reiniciado,
            # varredura concorrente) e o cenário quebra logo depois. Ler
            # `machine.id` no finally levantava ObjectDeletedError e a rodada
            # inteira morria, deixando as máquinas efêmeras no painel.
            db_.query(Machine).filter(Machine.id == machine.id).delete(synchronize_session=False)
            db_.commit()
            raise RuntimeError("cenário quebrou no meio")

        monkeypatch.setattr(benchmark, "_feed", _feed_que_apaga_a_maquina)
        resultado = benchmark.run_scenario(db, nome, user_id)

        assert resultado.error is not None          # o cenário falhou, e isso fica registrado
        assert resultado.verdict == "erro"          # sem contaminar as métricas da rodada
        assert db.query(Machine).filter(Machine.name.like("[BENCH]%")).count() == 0


class TestAcoesEmLote:
    def test_resolve_varios_e_ignora_o_que_nao_e_seu(self, client, auth, machine, db):
        from app.models.anomaly import Anomaly
        from app.models.user import User

        meus = []
        for _ in range(3):
            a = Anomaly(machine_id=machine["id"], anomaly_type="high_cpu", severity="medium",
                        detected_at=utcnow())
            db.add(a)
            meus.append(a)
        # Máquina de outra conta: os avisos dela não podem ser tocados
        outro = User(email="o@o.com", username="outro", hashed_password="x")
        db.add(outro)
        db.flush()
        alheia = Machine(name="Alheia", hostname="h", agent_token="tok-alheio", owner_id=outro.id)
        db.add(alheia)
        db.flush()
        dela = Anomaly(machine_id=alheia.id, anomaly_type="high_cpu", severity="medium",
                       detected_at=utcnow())
        db.add(dela)
        db.commit()

        ids = [a.id for a in meus] + [dela.id]
        resposta = client.post("/api/anomalies/resolve-bulk", json={"ids": ids}, headers=auth)
        assert resposta.status_code == 200
        assert resposta.json()["changed"] == 3

        db.expire_all()
        assert all(db.query(Anomaly).filter(Anomaly.id == a.id).first().is_resolved for a in meus)
        assert not db.query(Anomaly).filter(Anomaly.id == dela.id).first().is_resolved


class TestVisaoDeFrota:
    def test_overview_traz_vitais_e_pior_aviso(self, client, auth, machine, db):
        from app.models.anomaly import Anomaly

        db.add(Metric(machine_id=machine["id"], timestamp=utcnow(), cpu_percent=91.0, mem_percent=70.0,
                      mem_used=1, mem_available=1, mem_total=2, disk_used=1, disk_free=1, disk_percent=55.0,
                      disk_read_bytes=0, disk_write_bytes=0, net_bytes_sent=0, net_bytes_recv=0,
                      net_connections=10, uptime_seconds=100, process_count=100))
        db.add(Anomaly(machine_id=machine["id"], anomaly_type="high_cpu", severity="critical",
                       detected_at=utcnow()))
        db.commit()

        dados = client.get("/api/insights/fleet/overview", headers=auth).json()["machines"]
        assert len(dados) == 1
        linha = dados[0]
        assert linha["cpu"] == 91.0 and linha["disk"] == 55.0
        assert linha["open_count"] == 1
        assert linha["worst_severity"] == "critical"
