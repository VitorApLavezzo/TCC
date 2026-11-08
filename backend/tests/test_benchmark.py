"""Benchmark de detecção: os números do capítulo de resultados, inclusive nos casos
degenerados (nenhum ataque, nenhum acerto, divisão por zero)."""
import pytest


def _res(name, family, expected, detected):
    from app.services.benchmark import ScenarioResult
    return ScenarioResult(name=name, label=name, family=family, expected=expected, detected=detected)


class TestConfusionMatrix:
    def test_detected_attack_is_true_positive(self):
        from app.services.benchmark import confusion
        m = confusion([_res("mineiro", "attack", "malware_pattern", ["malware_pattern"])])
        assert m["true_positives"] == 1 and m["false_negatives"] == 0

    def test_undetected_attack_is_false_negative(self):
        from app.services.benchmark import confusion
        m = confusion([_res("mineiro", "attack", "malware_pattern", [])])
        assert m["false_negatives"] == 1 and m["true_positives"] == 0

    def test_detected_attack_with_extra_type_still_counts(self):
        """O que importa é o aviso esperado ter saído, não ter saído sozinho."""
        from app.services.benchmark import confusion
        m = confusion([_res("mineiro", "attack", "malware_pattern", ["high_cpu", "malware_pattern"])])
        assert m["true_positives"] == 1

    def test_attack_detected_with_wrong_type_is_false_negative(self):
        from app.services.benchmark import confusion
        m = confusion([_res("mineiro", "attack", "malware_pattern", ["high_cpu"])])
        assert m["false_negatives"] == 1

    def test_silent_normal_is_true_negative(self):
        from app.services.benchmark import confusion
        m = confusion([_res("antivirus", "normal", None, [])])
        assert m["true_negatives"] == 1 and m["false_positives"] == 0

    def test_normal_with_any_alert_is_false_positive(self):
        from app.services.benchmark import confusion
        m = confusion([_res("antivirus", "normal", None, ["resource_abuse"])])
        assert m["false_positives"] == 1


class TestDerivedMetrics:
    def _mix(self):
        return [
            _res("a1", "attack", "malware_pattern", ["malware_pattern"]),   # VP
            _res("a2", "attack", "cpu_loop", ["cpu_loop"]),                 # VP
            _res("a3", "attack", "beaconing", []),                          # FN
            _res("n1", "normal", None, []),                                 # VN
            _res("n2", "normal", None, []),                                 # VN
            _res("n3", "normal", None, ["unknown_process"]),                # FP
        ]

    def test_precision(self):
        from app.services.benchmark import confusion
        # 2 VP / (2 VP + 1 FP)
        assert confusion(self._mix())["precision"] == pytest.approx(0.6667, abs=1e-4)

    def test_recall(self):
        from app.services.benchmark import confusion
        # 2 VP / (2 VP + 1 FN)
        assert confusion(self._mix())["recall"] == pytest.approx(0.6667, abs=1e-4)

    def test_f1(self):
        from app.services.benchmark import confusion
        assert confusion(self._mix())["f1"] == pytest.approx(0.6667, abs=1e-4)

    def test_false_positive_rate(self):
        from app.services.benchmark import confusion
        # 1 FP / (1 FP + 2 VN)
        assert confusion(self._mix())["false_positive_rate"] == pytest.approx(0.3333, abs=1e-4)


class TestDegenerateCases:
    def test_no_scenarios_does_not_divide_by_zero(self):
        from app.services.benchmark import confusion
        m = confusion([])
        assert m["precision"] is None and m["recall"] is None and m["f1"] is None

    def test_only_normal_scenarios_have_no_recall(self):
        """Sem ataque, revocação não existe; 0 leria como "não detectou nada"."""
        from app.services.benchmark import confusion
        m = confusion([_res("n1", "normal", None, []), _res("n2", "normal", None, [])])
        assert m["recall"] is None
        assert m["false_positive_rate"] == 0.0

    def test_no_hits_has_zero_not_null_precision(self):
        from app.services.benchmark import confusion
        m = confusion([_res("a1", "attack", "cpu_loop", []), _res("n1", "normal", None, ["high_cpu"])])
        assert m["precision"] == 0.0
        assert m["f1"] == 0.0


class TestReport:
    def _result(self):
        from app.services.benchmark import BenchmarkResult, confusion
        rows = [
            _res("mineiro", "attack", "malware_pattern", ["malware_pattern"]),
            _res("antivirus_varrendo", "normal", None, []),
        ]
        return BenchmarkResult(scenarios=rows, metrics=confusion(rows), duration_ms=1234)

    def test_markdown_has_matrix_and_row_per_scenario(self):
        from app.services.benchmark import to_markdown
        md = to_markdown(self._result())
        assert "| Precisão |" in md or "Precisão" in md
        assert "mineiro" in md and "antivirus_varrendo" in md

    def test_csv_has_one_row_per_scenario_plus_header(self):
        from app.services.benchmark import to_csv
        lines = [l for l in to_csv(self._result()).strip().splitlines() if l]
        assert len(lines) == 3
        assert lines[0].startswith("cenario,")

    def test_csv_keeps_column_count_with_multiple_types(self):
        """Dois tipos no mesmo cenário não podem virar duas colunas (conferido com um leitor de CSV)."""
        import csv as csvlib
        import io
        from app.services.benchmark import BenchmarkResult, confusion, to_csv
        rows = [_res("x", "attack", "cpu_loop", ["cpu_loop", "high_cpu"])]
        text = to_csv(BenchmarkResult(scenarios=rows, metrics=confusion(rows), duration_ms=1))
        lines = list(csvlib.reader(io.StringIO(text)))
        assert len(lines[1]) == len(lines[0])
        assert "cpu_loop" in lines[1][lines[0].index("detectado")]


class TestScenarioExecution:
    """O executor roda pelo pipeline real; se divergir de uma máquina de verdade, o benchmark mede outra coisa."""

    def _owner(self, db):
        from app.core.security import get_password_hash
        from app.models.user import User
        u = User(email="bench@t.com", username="bench", hashed_password=get_password_hash("x"))
        db.add(u)
        db.commit()
        return u

    def test_attack_scenario_is_detected(self, db):
        from app.services import benchmark
        r = benchmark.run_scenario(db, "cpu_loop", self._owner(db).id)
        assert r.error is None, r.error
        assert r.verdict == "acerto", f"detectado: {r.detected}"

    def test_antivirus_scan_not_accused_as_threat(self, db):
        """Não exige silêncio total: o falso positivo do modelo estatístico é medido pelo próprio benchmark."""
        from app.services import benchmark
        r = benchmark.run_scenario(db, "antivirus_varrendo", self._owner(db).id)
        assert r.error is None, r.error
        accusations = {"malware_pattern", "suspicious_process", "unknown_process", "resource_abuse"}
        assert not (set(r.detected) & accusations), f"antivírus acusado de ameaça: {r.detected}"

    def test_result_is_reproducible(self, db):
        """Semente fixa e modelo limpo do disco: a mesma rodada dá o mesmo resultado."""
        from app.services import benchmark
        owner = self._owner(db).id
        a = benchmark.run_scenario(db, "antivirus_varrendo", owner)
        b = benchmark.run_scenario(db, "antivirus_varrendo", owner)
        assert a.detected == b.detected

    def test_ephemeral_machine_removed_at_end(self, db):
        from app.models.machine import Machine
        from app.services import benchmark
        before = db.query(Machine).count()
        benchmark.run_scenario(db, "antivirus_varrendo", self._owner(db).id)
        assert db.query(Machine).count() == before

    def test_scenario_runs_past_learning_period(self, db):
        """Durante o aprendizado metade dos detectores nem opina: a máquina seria muda por construção."""
        from app.services import benchmark
        assert benchmark.WARMUP_HOURS > 6
        assert benchmark.WARMUP_STEPS >= 100


class TestMachineRemovalDeletesModel:
    """O modelo vive em arquivo num volume que sobrevive ao banco; um id reaproveitado carregaria o de outra máquina."""

    def test_model_file_removed_with_machine(self, db):
        import os
        from app.core.security import get_password_hash
        from app.models.machine import Machine
        from app.models.user import User
        from app.routers.machines import delete_machine_cascade
        from app.services import ml_service

        u = User(email="mdl@t.com", username="mdl", hashed_password=get_password_hash("x"))
        db.add(u)
        db.flush()
        m = Machine(name="PC", hostname="H", agent_token="tok-mdl", owner_id=u.id)
        db.add(m)
        db.commit()

        path = ml_service._model_path(m.id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"modelo de mentira")
        assert os.path.exists(path)

        delete_machine_cascade(m.id, db)
        db.commit()
        assert not os.path.exists(path)


class TestRealDataScenarios:
    """Falso positivo medido em leituras reais, com gabarito não escrito por quem é avaliado."""

    def _machine_with_history(self, db, readings=200):
        from datetime import timedelta
        from app.core.security import get_password_hash
        from app.core.timeutil import utcnow
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.models.process import ProcessSnapshot
        from app.models.user import User
        u = User(email="real@t.com", username="real", hashed_password=get_password_hash("x"))
        db.add(u)
        db.flush()
        m = Machine(name="PC real", hostname="real", agent_token="tok-real", owner_id=u.id, os_type="Linux")
        db.add(m)
        db.flush()
        now = utcnow()
        for i in range(readings):
            met = Metric(machine_id=m.id, cpu_percent=12 + (i % 7), mem_percent=40 + (i % 5),
                         disk_percent=55.0, net_bytes_recv=1.4e5, net_bytes_sent=2.0e5,
                         net_connections=50 + (i % 10), cpu_count_logical=8,
                         timestamp=now - timedelta(minutes=(readings - i) * 2))
            db.add(met)
            db.flush()
            db.add(ProcessSnapshot(metric_id=met.id, pid=1, name="opera", cpu_percent=8.0, mem_percent=6.0,
                                   mem_rss=1e9, num_threads=10, status="running",
                                   exe="/usr/lib/opera/opera", signed="signed", publisher="opera-stable"))
        db.commit()
        return m

    def test_real_data_also_goes_through_forecast_recheck(self, db, monkeypatch):
        """Só dado real alcança o histórico que a previsão de disco exige; sem reconferir, o falso positivo sumiria."""
        from app.services import benchmark, forecasting
        calls = []
        monkeypatch.setattr(forecasting, "check_machine", lambda db, machine: calls.append(machine.id))
        origin = self._machine_with_history(db)
        r = benchmark.run_real_scenario(db, origin.id, origin.owner_id, minutes=600)
        assert r.error is None, r.error
        assert len(calls) == r.steps

    def test_replay_of_real_readings_becomes_scenario(self, db):
        from app.services import benchmark
        origin = self._machine_with_history(db)
        r = benchmark.run_real_scenario(db, origin.id, origin.owner_id, minutes=600)
        assert r.error is None, r.error
        assert r.family == benchmark.REAL
        assert r.expected is None
        assert r.steps > 0

    def test_without_enough_readings_scenario_reports_error(self, db):
        """Melhor erro fora da conta que um verdadeiro negativo de graça inflando a taxa de acerto."""
        from app.services import benchmark
        origin = self._machine_with_history(db, readings=3)
        r = benchmark.run_real_scenario(db, origin.id, origin.owner_id, minutes=120)
        assert r.error is not None


class TestOutput:
    def test_command_prints_markdown(self):
        """O comando escreve na saída padrão, sem depender de pasta montada no contêiner."""
        from app.benchmark import render
        from app.services.benchmark import BenchmarkResult, ScenarioResult, confusion
        lines = [ScenarioResult(name="x", label="X", family="attack", expected="cpu_loop", detected=["cpu_loop"])]
        r = BenchmarkResult(scenarios=lines, metrics=confusion(lines), duration_ms=10)
        assert render(r, as_csv=False).startswith("# Benchmark")
        assert render(r, as_csv=True).startswith("cenario,")


class TestEndpoint:
    def test_run_is_stored_and_readable(self, client, auth, db):
        from app.models.benchmark import BenchmarkRun
        from app.services.benchmark import BenchmarkResult, ScenarioResult, confusion
        from app.services import benchmark_store
        lines = [ScenarioResult(name="x", label="X", family="normal", expected=None, detected=[])]
        r = BenchmarkResult(scenarios=lines, metrics=confusion(lines), duration_ms=10)
        user_id = client.get("/api/auth/me", headers=auth).json()["id"]
        benchmark_store.save(db, user_id, r)

        res = client.get("/api/evaluation/benchmark", headers=auth)
        assert res.status_code == 200
        assert res.json()["metrics"]["true_negatives"] == 1
        assert db.query(BenchmarkRun).count() == 1

    def test_no_runs_returns_empty_not_error(self, client, auth):
        res = client.get("/api/evaluation/benchmark", headers=auth)
        assert res.status_code == 200
        assert res.json() == {"run": None}

    def test_download_returns_markdown(self, client, auth, db):
        from app.services.benchmark import BenchmarkResult, ScenarioResult, confusion
        from app.services import benchmark_store
        lines = [ScenarioResult(name="x", label="X", family="normal", expected=None, detected=[])]
        r = BenchmarkResult(scenarios=lines, metrics=confusion(lines), duration_ms=10)
        user_id = client.get("/api/auth/me", headers=auth).json()["id"]
        run = benchmark_store.save(db, user_id, r)
        res = client.get(f"/api/evaluation/benchmark/{run.id}/download?fmt=md", headers=auth)
        assert res.status_code == 200 and res.text.startswith("# Benchmark")


class TestRobustness:
    """Rodada interrompida (SIGKILL, contêiner reiniciado) não executa o `finally` e deixa a máquina efêmera."""

    def _owner(self, db):
        from app.core.security import get_password_hash
        from app.models.user import User
        u = User(email="orf@t.com", username="orf", hashed_password=get_password_hash("x"))
        db.add(u)
        db.commit()
        return u

    def test_sweeps_orphan_ephemeral_machines(self, db):
        from app.models.machine import Machine
        from app.services import benchmark
        owner = self._owner(db)
        orphan = Machine(name="[BENCH] rodada morta", hostname="bench-orfa",
                       agent_token="tok-orfa", owner_id=owner.id)
        db.add(orphan)
        db.commit()
        assert benchmark.sweep_orphans(db, owner.id) == 1
        assert db.query(Machine).filter(Machine.name.like("[BENCH]%")).count() == 0

    def test_does_not_touch_real_machines(self, db):
        from app.models.machine import Machine
        from app.services import benchmark
        owner = self._owner(db)
        real = Machine(name="PC do Vitor", hostname="real", agent_token="tok-viva", owner_id=owner.id)
        db.add(real)
        db.commit()
        assert benchmark.sweep_orphans(db, owner.id) == 0
        assert db.query(Machine).filter(Machine.id == real.id).first() is not None

    def test_real_scenario_respects_reading_limit(self, db):
        """Sem teto, uma janela larga vira milhares de leituras pelo pipeline."""
        from app.services import benchmark
        from tests.test_benchmark import TestRealDataScenarios
        origin = TestRealDataScenarios()._machine_with_history(db, readings=300)
        r = benchmark.run_real_scenario(db, origin.id, origin.owner_id, minutes=6000, limit=140)
        assert r.error is None, r.error
        assert r.steps == 140 - benchmark.WARMUP_STEPS


class TestHonestSweep:
    def test_counts_only_actually_removed(self, db, monkeypatch):
        """Remoção que falha não conta como removida (o SQLite não impõe chave estrangeira; o Postgres sim)."""
        from app.core.security import get_password_hash
        from app.models.machine import Machine
        from app.models.user import User
        from app.services import benchmark
        u = User(email="sw@t.com", username="sw", hashed_password=get_password_hash("x"))
        db.add(u)
        db.flush()
        for i in range(2):
            db.add(Machine(name=f"[BENCH] x{i}", hostname=f"h{i}", agent_token=f"tk-sw{i}", owner_id=u.id))
        db.commit()

        def always_fail(_db, _machine_id):
            raise RuntimeError("chave estrangeira")
        monkeypatch.setattr(benchmark, "_drop_machine", always_fail)

        assert benchmark.sweep_orphans(db, u.id) == 0


class TestHourlyRate:
    """No cenário real, a taxa por hora é o número proporcional à observação."""

    def test_real_scenario_reports_hours_covered(self, db):
        from app.services import benchmark
        from tests.test_benchmark import TestRealDataScenarios
        origin = TestRealDataScenarios()._machine_with_history(db, readings=200)
        r = benchmark.run_real_scenario(db, origin.id, origin.owner_id, minutes=6000)
        assert r.error is None, r.error
        # 200 leituras de 2 em 2 min = 400 min; 110 de aquecimento saem da conta
        assert 2.5 < r.hours < 3.5

    def test_alerts_per_hour_comes_from_measured_window(self):
        from app.services.benchmark import ScenarioResult
        r = ScenarioResult(name="x", label="X", family="real", expected=None,
                           detected=["high_cpu", "network_spike"], hours=4.0)
        assert r.alerts_per_hour == 0.5

    def test_without_window_rate_does_not_exist(self):
        """Cenário sintético não tem duração real: a taxa seria inventada."""
        from app.services.benchmark import ScenarioResult
        r = ScenarioResult(name="x", label="X", family="attack", expected="cpu_loop", detected=["cpu_loop"])
        assert r.alerts_per_hour is None


class TestTwoRates:
    """Aviso registrado e aviso que interrompe são diferentes; manter a taxa antiga evita afrouxar a régua."""

    def _res(self, family, detected, notified):
        from app.services.benchmark import ScenarioResult
        return ScenarioResult(name="x", label="X", family=family, expected=None,
                              detected=detected, notified=notified)

    def test_low_severity_alert_counts_generated_not_notified(self):
        from app.services.benchmark import confusion
        m = confusion([self._res("normal", ["high_cpu"], []), self._res("normal", [], [])])
        assert m["false_positives"] == 1
        assert m["false_positive_rate"] == 0.5
        assert m["false_positives_notified"] == 0
        assert m["false_positive_rate_notified"] == 0.0

    def test_notifying_alert_counts_in_both(self):
        from app.services.benchmark import confusion
        m = confusion([self._res("normal", ["cpu_loop"], ["cpu_loop"]), self._res("normal", [], [])])
        assert m["false_positives"] == 1 and m["false_positives_notified"] == 1

    def test_verdict_still_based_on_generated(self):
        """Conservador: um aviso silencioso ainda é um aviso que não deveria existir."""
        r = self._res("normal", ["high_cpu"], [])
        assert r.verdict == "falso positivo"


def test_new_scenarios_registered():
    from app.services.benchmark import NORMAL, scenarios
    all_scenarios = scenarios()
    for name in ("pico_isolado", "instalacao_de_programas"):
        assert name in all_scenarios
        assert all_scenarios[name]["family"] == NORMAL
        assert all_scenarios[name]["expect"] is None


def test_ablation_switch_restores_previous_value():
    from app.services.anomaly_service import apply_confidence, set_confidence_mode
    previous = set_confidence_mode(False)
    try:
        assert apply_confidence("medium", 0.1) == "medium"  # desligada, não rebaixa
    finally:
        set_confidence_mode(previous)
    assert apply_confidence("medium", 0.1) == "low"


class TestReproducibleClock:
    """O modelo usa hora e dia da semana: o relógio virtual não pode depender de "agora"."""

    def test_anchor_always_wednesday_15h_local(self):
        from datetime import datetime, timedelta, timezone
        from app.services.benchmark import _virtual_clock
        for now in (datetime(2026, 10, 19, 3, 5, tzinfo=timezone.utc),
                      datetime(2026, 10, 23, 22, 45, tzinfo=timezone.utc),
                      datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)):
            anchor = _virtual_clock(now)
            local = anchor + timedelta(minutes=-180)
            assert (local.weekday(), local.hour, local.minute) == (2, 15, 0)
            assert now - timedelta(days=7) < anchor <= now

    def test_same_result_at_different_times(self, db):
        from datetime import datetime, timezone
        from app.core.security import get_password_hash
        from app.models.user import User
        from app.services import benchmark
        u = User(email="rel@t.com", username="rel", hashed_password=get_password_hash("x"))
        db.add(u)
        db.commit()
        early_morning = datetime(2026, 10, 19, 3, 10, tzinfo=timezone.utc)
        friday_night = datetime(2026, 10, 16, 23, 50, tzinfo=timezone.utc)
        a = benchmark.run_scenario(db, "compilacao", u.id, now=early_morning)
        b = benchmark.run_scenario(db, "compilacao", u.id, now=friday_night)
        assert a.detected == b.detected and a.notified == b.notified


def _bench_owner(db, suffix="ctx"):
    from app.core.security import get_password_hash
    from app.models.user import User
    u = User(email=f"bench{suffix}@t.com", username=f"bench{suffix}", hashed_password=get_password_hash("x"))
    db.add(u)
    db.commit()
    return u.id


def _set_layer(layer):
    from app.services import anomaly_service
    return anomaly_service.set_detection_layer(layer)


class TestHonestAblation:
    """Eventos do agente (isca, contato periódico) são regra, não Isolation Forest."""

    @pytest.mark.parametrize("scenario", ["ransomware", "beaconing"])
    def test_ml_only_does_not_see_agent_events(self, db, scenario):
        from app.services import benchmark
        previous = _set_layer("ml")
        try:
            r = benchmark.run_scenario(db, scenario, _bench_owner(db))
        finally:
            _set_layer(previous)
        assert r.error is None, r.error
        assert r.expected not in r.detected

    def test_rules_still_see_events(self, db):
        from app.services import benchmark
        previous = _set_layer("regras")
        try:
            r = benchmark.run_scenario(db, "ransomware", _bench_owner(db))
        finally:
            _set_layer(previous)
        assert r.verdict == "acerto", r.detected

    def test_ml_only_still_learns_programs(self, db):
        """O cadastro de programas conhecidos é aprendizado, não detector."""
        from app.core.timeutil import utcnow
        from app.models.process_baseline import ProcessBaseline
        from app.services import benchmark, demo
        from tests.test_trust import _machine
        m = _machine(db)
        previous = _set_layer("ml")
        try:
            benchmark._feed(db, m, demo._base_metric(0), demo._normal_processes(),
                            benchmark._virtual_clock(utcnow()), {})
        finally:
            _set_layer(previous)
        assert db.query(ProcessBaseline).filter(ProcessBaseline.machine_id == m.id).count() > 0


class TestSeen:
    def test_seen_counts_attack_with_any_alert(self):
        from app.services.benchmark import ATTACK, NORMAL, confusion
        r = confusion([
            _res("a", ATTACK, "cpu_loop", ["high_cpu"]),
            _res("b", ATTACK, "cpu_loop", ["cpu_loop"]),
            _res("c", ATTACK, "beaconing", []),
            _res("d", NORMAL, None, ["high_cpu"]),
        ])
        assert r["seen"] == 2
        assert r["true_positives"] == 1


class TestReadingWithContext:
    def test_base_reading_has_presence_and_foreground_window(self):
        from app.services import demo
        base = demo._base_metric(0)
        procs = {p["name"]: p for p in demo._normal_processes()}
        assert base["user_idle_seconds"] < 120
        assert base["foreground_pid"] == procs["chrome.exe"]["pid"]
        assert base["foreground_name"] == "chrome.exe"

    def test_snapshot_stores_pid_and_ancestors(self):
        from app.services import benchmark
        rows = list(benchmark._snapshot_rows(1, [{"name": "a.exe", "pid": 77, "ancestors": [5, 4]}], None))
        assert rows[0].pid == 77 and rows[0].ancestors == [5, 4]

    def test_heavy_game_is_on_screen(self):
        from app.services import benchmark, demo
        data, procs = demo._base_metric(0), demo._normal_processes()
        benchmark._heavy_game(0, data, procs)
        game = next(p for p in procs if p["name"] == "jogo.exe")
        assert data["foreground_pid"] == game["pid"]
        assert data["user_idle_seconds"] < 120

    def test_miner_runs_behind_browser(self):
        from app.services import benchmark, demo
        data, procs = demo._base_metric(0), demo._normal_processes()
        benchmark._miner(0, data, procs)
        miner = next(p for p in procs if p["name"] == "xmrig.exe")
        assert data["foreground_name"] == "chrome.exe"
        assert data["foreground_pid"] not in [miner["pid"]] + miner["ancestors"]

    def test_known_programs_are_seeded(self, db):
        from app.models.process_baseline import ProcessBaseline
        from app.services import benchmark
        from tests.test_trust import _machine
        m = _machine(db)
        benchmark._seed_known(db, m, ["jogo.exe"])
        b = db.query(ProcessBaseline).filter(ProcessBaseline.machine_id == m.id).one()
        assert b.process_name == "jogo.exe" and b.is_known


class TestHardCases:
    """Jogo × minerador: a distinção que o contexto de uso existe para fazer."""

    def _run(self, db, name):
        from app.services import benchmark
        r = benchmark.run_scenario(db, name, _bench_owner(db, name))
        assert r.error is None, r.error
        return r

    def test_unsigned_already_played_game_does_not_interrupt(self, db):
        r = self._run(db, "jogo_sem_assinatura")
        assert r.notified == [], r.detected

    def test_editor_child_compilation_does_not_interrupt(self, db):
        r = self._run(db, "compilacao_do_editor")
        assert r.notified == [], r.detected

    def test_miner_while_user_browses_interrupts(self, db):
        r = self._run(db, "minerador_com_pessoa_navegando")
        assert r.notified, r.detected

    def test_miner_in_rundll32_interrupts(self, db):
        r = self._run(db, "minerador_no_rundll32")
        assert r.notified, r.detected


def test_report_counts_attacks_seen():
    from app.services.benchmark import ATTACK, BenchmarkResult, confusion, to_markdown
    scenarios = [_res("a", ATTACK, "cpu_loop", ["high_cpu"]), _res("b", ATTACK, "beaconing", [])]
    md = to_markdown(BenchmarkResult(scenarios=scenarios, metrics=confusion(scenarios)))
    assert "| Ataques percebidos (qualquer aviso) | 1 de 2 |" in md
