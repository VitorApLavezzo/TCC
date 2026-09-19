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
