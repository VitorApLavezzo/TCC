"""Política do produto servida ao frontend.

Os números que aparecem na tela ("100 leituras e 1 hora", "a cada 10 a 60
segundos") estavam escritos à mão no frontend e divergiam do servidor — quatro
telas diziam "a cada 30 segundos" quando a coleta é adaptativa. Aqui a fonte é
uma só, e estes testes existem para que mudar a constante mude o que a pessoa lê.
"""


class TestPolitica:
    def test_reflete_as_constantes(self, client, auth):
        from app.routers import machines as machines_router
        from app.services import adaptive, learning

        res = client.get("/api/meta/policy", headers=auth)
        assert res.status_code == 200
        p = res.json()
        assert p["aprendizado"]["leituras"] == learning.NEEDED_SAMPLES
        assert p["aprendizado"]["horas"] == learning.NEEDED_HOURS
        assert p["coleta"]["rapido_segundos"] == adaptive.FAST
        assert p["coleta"]["normal_segundos"] == adaptive.BASE
        assert p["coleta"]["lento_segundos"] == adaptive.SLOW
        assert p["codigo_pareamento"]["minutos"] == machines_router.ENROLL_CODE_TTL_MINUTES

    def test_mudar_a_constante_muda_o_que_a_tela_escreve(self, client, auth, monkeypatch):
        """O motivo de o endpoint existir."""
        from app.services import learning
        monkeypatch.setattr(learning, "NEEDED_HOURS", 2)
        p = client.get("/api/meta/policy", headers=auth).json()
        assert p["aprendizado"]["rotulo"] == "100 leituras e 2 horas"

    def test_singular_quando_e_uma_hora_so(self, client, auth):
        """Plural é formatação, e formatação mora num lugar só."""
        from app.services import learning
        assert learning.NEEDED_HOURS == 1
        p = client.get("/api/meta/policy", headers=auth).json()
        assert p["aprendizado"]["rotulo"] == "100 leituras e 1 hora"

    def test_rotulo_da_coleta_vem_da_faixa_adaptativa(self, client, auth):
        p = client.get("/api/meta/policy", headers=auth).json()
        assert p["coleta"]["rotulo"] == "a cada 10 a 60 segundos"

    def test_exige_login(self, client):
        """São constantes de política, não segredo — mas num sistema de
        detecção, saber a janela de aprendizado ajuda quem quer se esconder."""
        assert client.get("/api/meta/policy").status_code in (401, 403)
