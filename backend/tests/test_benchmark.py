"""Benchmark de detecção: os números que vão para o capítulo de resultados.

Se esta conta estiver errada, a monografia afirma algo falso — então ela é
testada antes de qualquer coisa, inclusive nos casos degenerados que a
fórmula não cobre sozinha (nenhum ataque, nenhum acerto, divisão por zero).
"""
import pytest


def _res(nome, familia, esperado, obtidos):
    from app.services.benchmark import ScenarioResult
    return ScenarioResult(name=nome, label=nome, family=familia, expected=esperado, detected=obtidos)


class TestMatrizDeConfusao:
    def test_ataque_detectado_e_verdadeiro_positivo(self):
        from app.services.benchmark import confusion
        m = confusion([_res("mineiro", "attack", "malware_pattern", ["malware_pattern"])])
        assert m["true_positives"] == 1 and m["false_negatives"] == 0

    def test_ataque_nao_detectado_e_falso_negativo(self):
        from app.services.benchmark import confusion
        m = confusion([_res("mineiro", "attack", "malware_pattern", [])])
        assert m["false_negatives"] == 1 and m["true_positives"] == 0

    def test_ataque_detectado_com_outro_tipo_junto_ainda_conta(self):
        """O que importa é o aviso esperado ter saído, não ter saído sozinho."""
        from app.services.benchmark import confusion
        m = confusion([_res("mineiro", "attack", "malware_pattern", ["high_cpu", "malware_pattern"])])
        assert m["true_positives"] == 1

    def test_ataque_detectado_com_tipo_errado_e_falso_negativo(self):
        from app.services.benchmark import confusion
        m = confusion([_res("mineiro", "attack", "malware_pattern", ["high_cpu"])])
        assert m["false_negatives"] == 1

    def test_normal_silencioso_e_verdadeiro_negativo(self):
        from app.services.benchmark import confusion
        m = confusion([_res("antivirus", "normal", None, [])])
        assert m["true_negatives"] == 1 and m["false_positives"] == 0

    def test_normal_que_gera_qualquer_aviso_e_falso_positivo(self):
        from app.services.benchmark import confusion
        m = confusion([_res("antivirus", "normal", None, ["resource_abuse"])])
        assert m["false_positives"] == 1


class TestMetricasDerivadas:
    def _mix(self):
        return [
            _res("a1", "attack", "malware_pattern", ["malware_pattern"]),   # VP
            _res("a2", "attack", "cpu_loop", ["cpu_loop"]),                 # VP
            _res("a3", "attack", "beaconing", []),                          # FN
            _res("n1", "normal", None, []),                                 # VN
            _res("n2", "normal", None, []),                                 # VN
            _res("n3", "normal", None, ["unknown_process"]),                # FP
        ]

    def test_precisao(self):
        from app.services.benchmark import confusion
        # 2 VP / (2 VP + 1 FP)
        assert confusion(self._mix())["precision"] == pytest.approx(0.6667, abs=1e-4)

    def test_revocacao(self):
        from app.services.benchmark import confusion
        # 2 VP / (2 VP + 1 FN)
        assert confusion(self._mix())["recall"] == pytest.approx(0.6667, abs=1e-4)

    def test_f1(self):
        from app.services.benchmark import confusion
        assert confusion(self._mix())["f1"] == pytest.approx(0.6667, abs=1e-4)

    def test_taxa_de_falso_positivo(self):
        from app.services.benchmark import confusion
        # 1 FP / (1 FP + 2 VN)
        assert confusion(self._mix())["false_positive_rate"] == pytest.approx(0.3333, abs=1e-4)


class TestCasosDegenerados:
    def test_sem_cenario_nenhum_nao_divide_por_zero(self):
        from app.services.benchmark import confusion
        m = confusion([])
        assert m["precision"] is None and m["recall"] is None and m["f1"] is None

    def test_so_cenarios_normais_nao_tem_revocacao(self):
        """Sem ataque no conjunto, revocação não existe — e não pode virar 0,
        que na tabela leria como "não detectou nada"."""
        from app.services.benchmark import confusion
        m = confusion([_res("n1", "normal", None, []), _res("n2", "normal", None, [])])
        assert m["recall"] is None
        assert m["false_positive_rate"] == 0.0

    def test_nenhum_acerto_tem_precisao_zero_e_nao_nula(self):
        from app.services.benchmark import confusion
        m = confusion([_res("a1", "attack", "cpu_loop", []), _res("n1", "normal", None, ["high_cpu"])])
        assert m["precision"] == 0.0
        assert m["f1"] == 0.0


class TestRelatorio:
    def _resultado(self):
        from app.services.benchmark import BenchmarkResult, confusion
        rows = [
            _res("mineiro", "attack", "malware_pattern", ["malware_pattern"]),
            _res("antivirus_varrendo", "normal", None, []),
        ]
        return BenchmarkResult(scenarios=rows, metrics=confusion(rows), duration_ms=1234)

    def test_markdown_traz_a_matriz_e_a_linha_de_cada_cenario(self):
        from app.services.benchmark import to_markdown
        md = to_markdown(self._resultado())
        assert "| Precisão |" in md or "Precisão" in md
        assert "mineiro" in md and "antivirus_varrendo" in md

    def test_csv_tem_uma_linha_por_cenario_mais_cabecalho(self):
        from app.services.benchmark import to_csv
        linhas = [l for l in to_csv(self._resultado()).strip().splitlines() if l]
        assert len(linhas) == 3
        assert linhas[0].startswith("cenario,")

    def test_csv_mantem_o_numero_de_colunas_com_varios_tipos(self):
        """Dois tipos detectados no mesmo cenário não podem virar duas colunas.
        Conferido com o leitor de CSV de verdade, não contando vírgulas: o que
        importa é que o Excel leia as mesmas colunas em toda linha."""
        import csv as csvlib
        import io
        from app.services.benchmark import BenchmarkResult, confusion, to_csv
        rows = [_res("x", "attack", "cpu_loop", ["cpu_loop", "high_cpu"])]
        texto = to_csv(BenchmarkResult(scenarios=rows, metrics=confusion(rows), duration_ms=1))
        linhas = list(csvlib.reader(io.StringIO(texto)))
        assert len(linhas[1]) == len(linhas[0])
        assert "cpu_loop" in linhas[1][linhas[0].index("detectado")]


class TestExecucaoDeCenario:
    """O executor roda pelo pipeline real. Se ele divergir do que acontece numa
    máquina de verdade, o benchmark mede outra coisa e a monografia mente."""

    def _dono(self, db):
        from app.core.security import get_password_hash
        from app.models.user import User
        u = User(email="bench@t.com", username="bench", hashed_password=get_password_hash("x"))
        db.add(u)
        db.commit()
        return u

    def test_cenario_de_ataque_e_detectado(self, db):
        from app.services import benchmark
        r = benchmark.run_scenario(db, "cpu_loop", self._dono(db).id)
        assert r.error is None, r.error
        assert r.verdict == "acerto", f"detectado: {r.detected}"

    def test_antivirus_varrendo_nao_e_acusado_de_ameaca(self, db):
        """O que foi corrigido: a varredura deixou de ser tratada como ameaça.

        Este teste NÃO exige silêncio total — o modelo estatístico ainda marca
        a varredura como leitura fora do padrão, e isso é um falso positivo
        conhecido que o próprio benchmark mede e reporta. Afrouxar a asserção
        para "nenhum aviso" e depois relaxá-la seria esconder o número; o
        lugar do número é a tabela de resultados, não um teste verde.
        """
        from app.services import benchmark
        r = benchmark.run_scenario(db, "antivirus_varrendo", self._dono(db).id)
        assert r.error is None, r.error
        acusacoes = {"malware_pattern", "suspicious_process", "unknown_process", "resource_abuse"}
        assert not (set(r.detected) & acusacoes), f"antivírus acusado de ameaça: {r.detected}"

    def test_resultado_e_reprodutivel(self, db):
        """Sem semente fixa e sem limpar o modelo treinado do disco, a mesma
        rodada dava resultados diferentes — e resultado que muda não é
        resultado."""
        from app.services import benchmark
        dono = self._dono(db).id
        a = benchmark.run_scenario(db, "antivirus_varrendo", dono)
        b = benchmark.run_scenario(db, "antivirus_varrendo", dono)
        assert a.detected == b.detected

    def test_maquina_efemera_e_removida_ao_final(self, db):
        from app.models.machine import Machine
        from app.services import benchmark
        antes = db.query(Machine).count()
        benchmark.run_scenario(db, "antivirus_varrendo", self._dono(db).id)
        assert db.query(Machine).count() == antes

    def test_cenario_roda_fora_do_periodo_de_aprendizado(self, db):
        """Sem isto o benchmark mediria uma máquina muda por construção: durante
        o aprendizado metade dos detectores nem opina."""
        from app.services import benchmark
        assert benchmark.WARMUP_HOURS > 6
        assert benchmark.WARMUP_STEPS >= 100


class TestRemocaoDeMaquinaLimpaOModelo:
    """O modelo treinado vive em arquivo (`machine_<id>_bundle.pkl`) num volume
    que sobrevive ao banco. Sem apagá-lo junto com a máquina, um id reaproveitado
    carrega o modelo de outra máquina — foi o que tornou o benchmark
    irreprodutível, e em produção é arquivo acumulando para sempre."""

    def test_arquivo_do_modelo_some_com_a_maquina(self, db):
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

        caminho = ml_service._model_path(m.id)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "wb") as f:
            f.write(b"modelo de mentira")
        assert os.path.exists(caminho)

        delete_machine_cascade(m.id, db)
        db.commit()
        assert not os.path.exists(caminho)


class TestCenariosDeDadoReal:
    """O falso positivo medido em leituras de uma máquina de verdade: o
    gabarito aqui não foi escrito por quem está sendo avaliado."""

    def _maquina_com_historico(self, db, leituras=200):
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
        agora = utcnow()
        for i in range(leituras):
            met = Metric(machine_id=m.id, cpu_percent=12 + (i % 7), mem_percent=40 + (i % 5),
                         disk_percent=55.0, net_bytes_recv=1.4e5, net_bytes_sent=2.0e5,
                         net_connections=50 + (i % 10), cpu_count_logical=8,
                         timestamp=agora - timedelta(minutes=(leituras - i) * 2))
            db.add(met)
            db.flush()
            db.add(ProcessSnapshot(metric_id=met.id, pid=1, name="opera", cpu_percent=8.0, mem_percent=6.0,
                                   mem_rss=1e9, num_threads=10, status="running",
                                   exe="/usr/lib/opera/opera", signed="signed", publisher="opera-stable"))
        db.commit()
        return m

    def test_dado_real_tambem_passa_pela_reconferencia_da_previsao(self, db, monkeypatch):
        """Dado real é o único lugar onde a previsão de disco poderia dar falso
        positivo: os cenários sintéticos não chegam ao meio dia de histórico.
        Se o cenário real pulasse a reconferência, esse falso positivo não
        apareceria na conta."""
        from app.services import benchmark, forecasting
        chamadas = []
        monkeypatch.setattr(forecasting, "check_machine", lambda db, machine: chamadas.append(machine.id))
        origem = self._maquina_com_historico(db)
        r = benchmark.run_real_scenario(db, origem.id, origem.owner_id, minutes=600)
        assert r.error is None, r.error
        assert len(chamadas) == r.steps

    def test_replay_de_leituras_reais_vira_cenario(self, db):
        from app.services import benchmark
        origem = self._maquina_com_historico(db)
        r = benchmark.run_real_scenario(db, origem.id, origem.owner_id, minutes=600)
        assert r.error is None, r.error
        assert r.family == benchmark.REAL
        assert r.expected is None
        assert r.steps > 0

    def test_sem_leituras_suficientes_o_cenario_se_declara_erro(self, db):
        """Melhor um cenário marcado como erro e fora da conta do que um
        verdadeiro negativo de graça inflando a taxa de acerto."""
        from app.services import benchmark
        origem = self._maquina_com_historico(db, leituras=3)
        r = benchmark.run_real_scenario(db, origem.id, origem.owner_id, minutes=120)
        assert r.error is not None


class TestSaida:
    def test_comando_imprime_markdown(self):
        """O comando escreve na saída padrão para você redirecionar aonde
        quiser — sem caminho configurável e sem depender de qual pasta está
        montada no contêiner."""
        from app.benchmark import render
        from app.services.benchmark import BenchmarkResult, ScenarioResult, confusion
        linhas = [ScenarioResult(name="x", label="X", family="attack", expected="cpu_loop", detected=["cpu_loop"])]
        r = BenchmarkResult(scenarios=linhas, metrics=confusion(linhas), duration_ms=10)
        assert render(r, as_csv=False).startswith("# Benchmark")
        assert render(r, as_csv=True).startswith("cenario,")


class TestEndpoint:
    def test_rodada_fica_gravada_e_pode_ser_lida(self, client, auth, db):
        from app.models.benchmark import BenchmarkRun
        from app.services.benchmark import BenchmarkResult, ScenarioResult, confusion
        from app.services import benchmark_store
        linhas = [ScenarioResult(name="x", label="X", family="normal", expected=None, detected=[])]
        r = BenchmarkResult(scenarios=linhas, metrics=confusion(linhas), duration_ms=10)
        user_id = client.get("/api/auth/me", headers=auth).json()["id"]
        benchmark_store.save(db, user_id, r)

        res = client.get("/api/evaluation/benchmark", headers=auth)
        assert res.status_code == 200
        assert res.json()["metrics"]["true_negatives"] == 1
        assert db.query(BenchmarkRun).count() == 1

    def test_sem_rodada_nenhuma_responde_vazio_e_nao_erro(self, client, auth):
        res = client.get("/api/evaluation/benchmark", headers=auth)
        assert res.status_code == 200
        assert res.json() == {"run": None}

    def test_download_devolve_markdown(self, client, auth, db):
        from app.services.benchmark import BenchmarkResult, ScenarioResult, confusion
        from app.services import benchmark_store
        linhas = [ScenarioResult(name="x", label="X", family="normal", expected=None, detected=[])]
        r = BenchmarkResult(scenarios=linhas, metrics=confusion(linhas), duration_ms=10)
        user_id = client.get("/api/auth/me", headers=auth).json()["id"]
        run = benchmark_store.save(db, user_id, r)
        res = client.get(f"/api/evaluation/benchmark/{run.id}/download?fmt=md", headers=auth)
        assert res.status_code == 200 and res.text.startswith("# Benchmark")


class TestRobustez:
    """Uma rodada interrompida (SIGKILL, contêiner reiniciado) não executa o
    `finally` e deixa a máquina efêmera para trás. Aconteceu de verdade na
    primeira rodada completa."""

    def _dono(self, db):
        from app.core.security import get_password_hash
        from app.models.user import User
        u = User(email="orf@t.com", username="orf", hashed_password=get_password_hash("x"))
        db.add(u)
        db.commit()
        return u

    def test_varre_maquinas_efemeras_orfas(self, db):
        from app.models.machine import Machine
        from app.services import benchmark
        dono = self._dono(db)
        orfa = Machine(name="[BENCH] rodada morta", hostname="bench-orfa",
                       agent_token="tok-orfa", owner_id=dono.id)
        db.add(orfa)
        db.commit()
        assert benchmark.sweep_orphans(db, dono.id) == 1
        assert db.query(Machine).filter(Machine.name.like("[BENCH]%")).count() == 0

    def test_nao_toca_nas_maquinas_de_verdade(self, db):
        from app.models.machine import Machine
        from app.services import benchmark
        dono = self._dono(db)
        real = Machine(name="PC do Vitor", hostname="real", agent_token="tok-viva", owner_id=dono.id)
        db.add(real)
        db.commit()
        assert benchmark.sweep_orphans(db, dono.id) == 0
        assert db.query(Machine).filter(Machine.id == real.id).first() is not None

    def test_cenario_real_respeita_o_limite_de_leituras(self, db):
        """Sem teto, uma janela larga vira milhares de leituras pelo pipeline —
        foi o que derrubou a primeira rodada."""
        from app.services import benchmark
        from tests.test_benchmark import TestCenariosDeDadoReal
        origem = TestCenariosDeDadoReal()._maquina_com_historico(db, leituras=300)
        r = benchmark.run_real_scenario(db, origem.id, origem.owner_id, minutes=6000, limit=140)
        assert r.error is None, r.error
        assert r.steps == 140 - benchmark.WARMUP_STEPS


class TestVarreduraHonesta:
    def test_conta_so_o_que_removeu_de_verdade(self, db, monkeypatch):
        """A varredura dizia ter removido máquinas que continuaram lá quando a
        remoção falhava. O teste original passou porque o SQLite não impõe
        chave estrangeira e nada falhava — o Postgres é que reprovou."""
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

        def falha_sempre(_db, _machine_id):
            raise RuntimeError("chave estrangeira")
        monkeypatch.setattr(benchmark, "_drop_machine", falha_sempre)

        assert benchmark.sweep_orphans(db, u.id) == 0


class TestTaxaPorHora:
    """No cenário de uso real, "qualquer aviso em 490 leituras" trata igual um
    sistema que avisa uma vez por dia e outro que avisa cem. A taxa por hora é
    o número proporcional à observação."""

    def test_cenario_real_informa_quantas_horas_cobriu(self, db):
        from app.services import benchmark
        from tests.test_benchmark import TestCenariosDeDadoReal
        origem = TestCenariosDeDadoReal()._maquina_com_historico(db, leituras=200)
        r = benchmark.run_real_scenario(db, origem.id, origem.owner_id, minutes=6000)
        assert r.error is None, r.error
        # 200 leituras de 2 em 2 min = 400 min; 110 de aquecimento saem da conta
        assert 2.5 < r.hours < 3.5

    def test_avisos_por_hora_sai_da_janela_medida(self):
        from app.services.benchmark import ScenarioResult
        r = ScenarioResult(name="x", label="X", family="real", expected=None,
                           detected=["high_cpu", "network_spike"], hours=4.0)
        assert r.alerts_per_hour == 0.5

    def test_sem_janela_a_taxa_nao_existe(self):
        """Cenário sintético não tem duração real: taxa por hora ali seria
        número inventado."""
        from app.services.benchmark import ScenarioResult
        r = ScenarioResult(name="x", label="X", family="attack", expected="cpu_loop", detected=["cpu_loop"])
        assert r.alerts_per_hour is None


class TestDuasTaxas:
    """Aviso registrado e aviso que interrompe a pessoa são coisas diferentes.
    Reportar as duas é mais informativo — e manter a antiga na tabela impede a
    acusação de ter afrouxado a régua depois de ver o resultado."""

    def _res(self, familia, detected, notified):
        from app.services.benchmark import ScenarioResult
        return ScenarioResult(name="x", label="X", family=familia, expected=None,
                              detected=detected, notified=notified)

    def test_aviso_de_baixa_severidade_conta_no_gerado_mas_nao_no_notificado(self):
        from app.services.benchmark import confusion
        m = confusion([self._res("normal", ["high_cpu"], []), self._res("normal", [], [])])
        assert m["false_positives"] == 1
        assert m["false_positive_rate"] == 0.5
        assert m["false_positives_notified"] == 0
        assert m["false_positive_rate_notified"] == 0.0

    def test_aviso_que_notifica_conta_nas_duas(self):
        from app.services.benchmark import confusion
        m = confusion([self._res("normal", ["cpu_loop"], ["cpu_loop"]), self._res("normal", [], [])])
        assert m["false_positives"] == 1 and m["false_positives_notified"] == 1

    def test_veredito_continua_baseado_no_que_foi_gerado(self):
        """Conservador de propósito: um aviso silencioso ainda é um aviso que
        o sistema não deveria ter produzido."""
        r = self._res("normal", ["high_cpu"], [])
        assert r.verdict == "falso positivo"


def test_cenarios_novos_registrados():
    from app.services.benchmark import NORMAL, scenarios
    todos = scenarios()
    for nome in ("pico_isolado", "instalacao_de_programas"):
        assert nome in todos
        assert todos[nome]["family"] == NORMAL
        assert todos[nome]["expect"] is None


def test_chave_de_ablacao_restaura_o_valor_anterior():
    from app.services.anomaly_service import apply_confidence, set_confidence_mode
    anterior = set_confidence_mode(False)
    try:
        assert apply_confidence("medium", 0.1) == "medium"  # desligada, não rebaixa
    finally:
        set_confidence_mode(anterior)
    assert apply_confidence("medium", 0.1) == "low"


class TestRelogioReproduzivel:
    """O modelo usa hora do dia e dia da semana como atributos, e o relógio
    virtual do benchmark era ancorado em "agora": o mesmo código dava número
    diferente às 23h40 e às 00h05. Resultado de TCC tem que sair igual quando
    a banca pedir para rodar de novo."""

    def test_ancora_sempre_na_quarta_as_15h_locais(self):
        from datetime import datetime, timedelta, timezone
        from app.services.benchmark import _virtual_clock
        for agora in (datetime(2026, 10, 19, 3, 5, tzinfo=timezone.utc),
                      datetime(2026, 10, 23, 22, 45, tzinfo=timezone.utc),
                      datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)):
            ancora = _virtual_clock(agora)
            local = ancora + timedelta(minutes=-180)
            assert (local.weekday(), local.hour, local.minute) == (2, 15, 0)
            assert agora - timedelta(days=7) < ancora <= agora

    def test_mesmo_resultado_em_horarios_diferentes(self, db):
        from datetime import datetime, timezone
        from app.core.security import get_password_hash
        from app.models.user import User
        from app.services import benchmark
        u = User(email="rel@t.com", username="rel", hashed_password=get_password_hash("x"))
        db.add(u)
        db.commit()
        madrugada = datetime(2026, 10, 19, 3, 10, tzinfo=timezone.utc)
        sexta_noite = datetime(2026, 10, 16, 23, 50, tzinfo=timezone.utc)
        a = benchmark.run_scenario(db, "compilacao", u.id, now=madrugada)
        b = benchmark.run_scenario(db, "compilacao", u.id, now=sexta_noite)
        assert a.detected == b.detected and a.notified == b.notified


def _dono_bench(db, sufixo="ctx"):
    from app.core.security import get_password_hash
    from app.models.user import User
    u = User(email=f"bench{sufixo}@t.com", username=f"bench{sufixo}", hashed_password=get_password_hash("x"))
    db.add(u)
    db.commit()
    return u.id


def _na_camada(camada):
    from app.services import anomaly_service
    return anomaly_service.set_detection_layer(camada)


class TestAblacaoHonesta:
    """Eventos do agente (isca, contato periódico) são regra, não Isolation Forest."""

    @pytest.mark.parametrize("cenario", ["ransomware", "beaconing"])
    def test_so_ml_nao_ve_os_eventos_do_agente(self, db, cenario):
        from app.services import benchmark
        anterior = _na_camada("ml")
        try:
            r = benchmark.run_scenario(db, cenario, _dono_bench(db))
        finally:
            _na_camada(anterior)
        assert r.error is None, r.error
        assert r.expected not in r.detected

    def test_regras_continuam_vendo_os_eventos(self, db):
        from app.services import benchmark
        anterior = _na_camada("regras")
        try:
            r = benchmark.run_scenario(db, "ransomware", _dono_bench(db))
        finally:
            _na_camada(anterior)
        assert r.verdict == "acerto", r.detected

    def test_so_ml_continua_aprendendo_os_programas(self, db):
        """O cadastro de programas conhecidos é aprendizado, não detector: sem ele,
        "programa conhecido" seria sempre 0 na camada do modelo."""
        from app.core.timeutil import utcnow
        from app.models.process_baseline import ProcessBaseline
        from app.services import benchmark, demo
        from tests.test_trust import _machine
        m = _machine(db)
        anterior = _na_camada("ml")
        try:
            benchmark._feed(db, m, demo._base_metric(0), demo._normal_processes(),
                            benchmark._virtual_clock(utcnow()), {})
        finally:
            _na_camada(anterior)
        assert db.query(ProcessBaseline).filter(ProcessBaseline.machine_id == m.id).count() > 0


class TestViu:
    def test_viu_conta_ataque_com_qualquer_aviso(self):
        from app.services.benchmark import ATTACK, NORMAL, confusion
        r = confusion([
            _res("a", ATTACK, "cpu_loop", ["high_cpu"]),
            _res("b", ATTACK, "cpu_loop", ["cpu_loop"]),
            _res("c", ATTACK, "beaconing", []),
            _res("d", NORMAL, None, ["high_cpu"]),
        ])
        assert r["seen"] == 2
        assert r["true_positives"] == 1


class TestLeituraComContexto:
    def test_leitura_base_tem_presenca_e_janela_ativa(self):
        from app.services import demo
        base = demo._base_metric(0)
        procs = {p["name"]: p for p in demo._normal_processes()}
        assert base["user_idle_seconds"] < 120
        assert base["foreground_pid"] == procs["chrome.exe"]["pid"]
        assert base["foreground_name"] == "chrome.exe"

    def test_snapshot_guarda_pid_e_pais(self):
        from app.services import benchmark
        rows = list(benchmark._snapshot_rows(1, [{"name": "a.exe", "pid": 77, "ancestors": [5, 4]}], None))
        assert rows[0].pid == 77 and rows[0].ancestors == [5, 4]

    def test_jogo_pesado_esta_na_tela(self):
        from app.services import benchmark, demo
        data, procs = demo._base_metric(0), demo._normal_processes()
        benchmark._heavy_game(0, data, procs)
        jogo = next(p for p in procs if p["name"] == "jogo.exe")
        assert data["foreground_pid"] == jogo["pid"]
        assert data["user_idle_seconds"] < 120

    def test_minerador_roda_por_tras_do_navegador(self):
        from app.services import benchmark, demo
        data, procs = demo._base_metric(0), demo._normal_processes()
        benchmark._miner(0, data, procs)
        minerador = next(p for p in procs if p["name"] == "xmrig.exe")
        assert data["foreground_name"] == "chrome.exe"
        assert data["foreground_pid"] not in [minerador["pid"]] + minerador["ancestors"]

    def test_programas_conhecidos_sao_semeados(self, db):
        from app.models.process_baseline import ProcessBaseline
        from app.services import benchmark
        from tests.test_trust import _machine
        m = _machine(db)
        benchmark._seed_known(db, m, ["jogo.exe"])
        b = db.query(ProcessBaseline).filter(ProcessBaseline.machine_id == m.id).one()
        assert b.process_name == "jogo.exe" and b.is_known


class TestCasosDificeis:
    """Jogo × minerador: a distinção que o contexto de uso existe para fazer."""

    def _rodar(self, db, nome):
        from app.services import benchmark
        r = benchmark.run_scenario(db, nome, _dono_bench(db, nome))
        assert r.error is None, r.error
        return r

    def test_jogo_sem_assinatura_ja_jogado_nao_interrompe(self, db):
        r = self._rodar(db, "jogo_sem_assinatura")
        assert r.notified == [], r.detected

    def test_compilacao_filha_do_editor_nao_interrompe(self, db):
        r = self._rodar(db, "compilacao_do_editor")
        assert r.notified == [], r.detected

    def test_minerador_com_a_pessoa_navegando_interrompe(self, db):
        r = self._rodar(db, "minerador_com_pessoa_navegando")
        assert r.notified, r.detected

    def test_minerador_no_rundll32_interrompe(self, db):
        r = self._rodar(db, "minerador_no_rundll32")
        assert r.notified, r.detected


def test_relatorio_conta_os_ataques_que_o_sistema_viu():
    from app.services.benchmark import ATTACK, BenchmarkResult, confusion, to_markdown
    cenarios = [_res("a", ATTACK, "cpu_loop", ["high_cpu"]), _res("b", ATTACK, "beaconing", [])]
    md = to_markdown(BenchmarkResult(scenarios=cenarios, metrics=confusion(cenarios)))
    assert "| Ataques percebidos (qualquer aviso) | 1 de 2 |" in md
