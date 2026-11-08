"""Política do produto servida ao frontend: mudar a constante muda o que a tela mostra."""


class TestPolicy:
    def test_reflects_constants(self, client, auth):
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

    def test_changing_constant_changes_screen_text(self, client, auth, monkeypatch):
        """O motivo de o endpoint existir."""
        from app.services import learning
        monkeypatch.setattr(learning, "NEEDED_HOURS", 2)
        p = client.get("/api/meta/policy", headers=auth).json()
        assert p["aprendizado"]["rotulo"] == "100 leituras e 2 horas"

    def test_singular_when_one_hour(self, client, auth):
        """Plural é formatação, e formatação mora num lugar só."""
        from app.services import learning
        assert learning.NEEDED_HOURS == 1
        p = client.get("/api/meta/policy", headers=auth).json()
        assert p["aprendizado"]["rotulo"] == "100 leituras e 1 hora"

    def test_collection_label_comes_from_adaptive_range(self, client, auth):
        p = client.get("/api/meta/policy", headers=auth).json()
        assert p["coleta"]["rotulo"] == "a cada 10 a 60 segundos"

    def test_requires_login(self, client):
        """Não é segredo, mas saber a janela de aprendizado ajuda quem quer se esconder."""
        assert client.get("/api/meta/policy").status_code in (401, 403)
