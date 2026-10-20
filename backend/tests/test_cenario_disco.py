"""Cenário "Disco enchendo": o que a demonstração e o benchmark mostram.

Estava quebrado de três jeitos. O aquecimento usava um disco de 500 GB e o
cenário recalculava com um de 100 GB, então o uso em GB caía enquanto o
percentual subia. A previsão exige meio dia de histórico e o cenário andava
30 segundos por passo — impossível por construção. E nem a demonstração nem
o benchmark chamavam a função que cria o aviso: a demonstração só escrevia
"Previsão de disco: sem tendência" no log, na frente de quem assistia.
"""
from app.core.security import get_password_hash
from app.models.anomaly import Anomaly
from app.models.user import User


def _usuario(db):
    u = User(email="disco@t.com", username="disco", hashed_password=get_password_hash("x"))
    db.add(u)
    db.commit()
    return u


class TestUnidades:
    def test_tamanho_do_disco_nao_muda_e_o_uso_so_cresce(self):
        from app.services import demo
        base = demo._base_metric(0)
        total = base["disk_used"] + base["disk_free"]
        usados = []
        for k in range(demo.SCENARIOS["disk_filling"]["attack"]):
            m = demo._base_metric(k)
            demo._scenario_step("disk_filling", "attack", k, m, [])
            assert abs((m["disk_used"] + m["disk_free"]) - total) < 1e6
            assert abs(m["disk_used"] / total * 100 - m["disk_percent"]) < 0.01
            usados.append(m["disk_used"])
        assert usados == sorted(usados) and usados[-1] > usados[0]
        assert usados[0] >= base["disk_used"]


class TestDemonstracao:
    def test_cria_o_aviso_de_previsao(self, db):
        from app.services import demo
        s = demo.start(db, _usuario(db), "disk_filling")
        while s.status != "done":
            demo.step(db, s)
            db.refresh(s)
        tipos = {a.anomaly_type for a in db.query(Anomaly).filter(
            Anomaly.machine_id == s.state["machine_id"]).all()}
        assert "disk_forecast" in tipos

    def test_log_nao_diz_sem_tendencia(self, db):
        from app.services import demo
        s = demo.start(db, _usuario(db), "disk_filling")
        while s.status != "done":
            demo.step(db, s)
            db.refresh(s)
        previsao = [l for l in s.log if l.startswith("Previsão de disco")]
        assert previsao and "sem tendência" not in previsao[-1]


class TestBenchmark:
    def test_previsao_de_disco_e_detectada_pelo_caminho_real(self, db):
        """Sem trocar o gabarito: o cenário é que passou a simular o que a
        previsão foi feita para ver, e o benchmark passou a rodar a
        reconferência que o agendador roda em produção."""
        from app.services import benchmark
        r = benchmark.run_scenario(db, "disk_filling", _usuario(db).id)
        assert r.error is None
        assert "disk_forecast" in r.detected
        assert r.verdict == "acerto"


class TestFraseDaPrevisao:
    """Aparece no log da demonstração e no aviso, na frente de quem assiste."""

    def test_um_dia_no_singular(self):
        from app.services.forecasting import frase_previsao
        frase = frase_previsao(span_dias=1.2, gb_por_dia=92.7, eta_dias=3.0)
        assert "do último dia" in frase and "1 dias" not in frase

    def test_menos_de_um_dia_sem_cerca_de(self):
        from app.services.forecasting import frase_previsao
        frase = frase_previsao(span_dias=1.2, gb_por_dia=92.7, eta_dias=0.4)
        assert "enche em menos de um dia" in frase and "cerca de menos" not in frase

    def test_varios_dias_continua_igual(self):
        from app.services.forecasting import frase_previsao
        frase = frase_previsao(span_dias=5, gb_por_dia=2.5, eta_dias=6)
        assert frase == "No ritmo dos últimos 5 dias (2,5 GB por dia), o disco enche em cerca de 6 dias."

    def test_duas_semanas(self):
        from app.services.forecasting import frase_previsao
        assert "das últimas duas semanas" in frase_previsao(span_dias=12, gb_por_dia=1.0, eta_dias=20)


class TestAblacao:
    def test_previsao_nao_e_creditada_a_uma_camada_so(self, db):
        """A previsão de disco não é regra nem Isolation Forest: na tabela de
        ablação do TCC ela só pode contar na linha do sistema completo."""
        from app.services import anomaly_service, benchmark
        u = _usuario(db)
        for camada in ("ml", "regras"):
            anterior = anomaly_service.set_detection_layer(camada)
            try:
                r = benchmark.run_scenario(db, "disk_filling", u.id)
            finally:
                anomaly_service.set_detection_layer(anterior)
            assert "disk_forecast" not in r.detected, camada
