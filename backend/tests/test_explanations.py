"""Checagem dos números que a IA escreve: rigorosa demais rejeita respostas boas,
frouxa demais deixa passar número inventado."""
from app.services.ai_service import strip_citations, verify_numbers

FACTS = {
    "cpu_agora": {"label": "Processador agora", "value": 94.0, "unit": "%"},
    "cpu_normal": {"label": "Processador normal", "value": 18.0, "unit": "%"},
    "ram_agora": {"label": "Memória agora", "value": 91.0, "unit": "%"},
    "conexoes_agora": {"label": "Conexões agora", "value": 240.0, "unit": ""},
    "temp_agora": {"label": "Temperatura", "value": 88.0, "unit": "°C"},
}


def fields(summary="", detail="", causes=None, recs=None):
    return {
        "summary": summary,
        "detailed_explanation": detail,
        "possible_causes": causes or [],
        "recommendations": recs or [],
        "severity_justification": "",
    }


class TestVerifyNumbers:
    def test_cited_and_correct_passes(self):
        v = verify_numbers(
            fields(summary="O processador está em 94% [[cpu_agora]], contra 18% [[cpu_normal]] do normal."),
            FACTS,
        )
        assert v["passed"] is True
        assert v["claims"] == 2 and v["verified"] == 2
        assert v["unverified"] == []

    def test_invented_number_fails(self):
        v = verify_numbers(fields(summary="A memória chegou a 67% e o disco a 45%."), FACTS)
        assert v["passed"] is False
        assert len(v["unverified"]) >= 2

    def test_uncited_but_real_number_passes(self):
        """A IA pode esquecer a chave; se o número existe nos dados, vale."""
        v = verify_numbers(fields(summary="A memória está em 91%."), FACTS)
        assert v["passed"] is True and v["verified"] == 1

    def test_ratio_between_facts_passes(self):
        """"5 vezes o normal" = 94/18, uma conta legítima sobre dois fatos."""
        v = verify_numbers(fields(summary="O processador está 5 vezes acima do normal."), FACTS)
        assert v["passed"] is True

    def test_text_without_numbers_passes(self):
        v = verify_numbers(fields(summary="O computador está lento por causa de um programa travado."), FACTS)
        assert v["claims"] == 0 and v["passed"] is True

    def test_tolerates_one_slip(self):
        """Um número solto errado no meio de vários certos não descarta a resposta."""
        v = verify_numbers(
            fields(
                summary="Processador em 94% [[cpu_agora]].",
                detail="A memória está em 91% [[ram_agora]] e há 240 conexões [[conexoes_agora]]. A temperatura beira 77 °C.",
            ),
            FACTS,
        )
        assert v["passed"] is True
        assert len(v["unverified"]) == 1

    def test_rounding_is_accepted(self):
        """A IA arredonda: 88 °C vira 88, 94% vira 94 — e 91,4% ainda é a memória."""
        v = verify_numbers(fields(summary="Memória em 91,4% [[ram_agora]] e 88 °C [[temp_agora]]."), FACTS)
        assert v["passed"] is True and v["verified"] == 2

    def test_invalid_citation_is_reported(self):
        v = verify_numbers(fields(summary="Disco em 94% [[disco_inexistente]]."), FACTS)
        assert "disco_inexistente" in v["invalid_citations"]

    def test_steps_with_shortcuts_are_not_claims(self):
        """"Ctrl+Shift+Esc" e "Windows 11" não são afirmações numéricas."""
        v = verify_numbers(
            fields(recs=["Aperte Ctrl+Shift+Esc para abrir o Gerenciador de Tarefas no Windows 11"]),
            FACTS,
        )
        assert v["claims"] == 0 and v["passed"] is True


class TestStripCitations:
    def test_removes_markers(self):
        assert strip_citations("Memória em 91% [[ram_agora]] agora.") == "Memória em 91% agora."

    def test_keeps_plain_text(self):
        assert strip_citations("Nada a remover.") == "Nada a remover."

    def test_handles_none(self):
        assert strip_citations(None) is None


def _context_scenario(db, suffix, **context):
    from app.core.security import get_password_hash
    from app.models.anomaly import Anomaly
    from app.models.machine import Machine
    from app.models.metric import Metric
    from app.models.user import User
    u = User(email=f"ctx{suffix}@t.com", username=f"ctx{suffix}", hashed_password=get_password_hash("x"))
    db.add(u)
    db.flush()
    m = Machine(name="PC", hostname="H", agent_token=f"tok-ctx-{suffix}", owner_id=u.id, os_type="Windows")
    db.add(m)
    db.flush()
    met = Metric(machine_id=m.id, cpu_percent=97, mem_percent=40, cpu_count_logical=8, **context)
    db.add(met)
    db.flush()
    a = Anomaly(machine_id=m.id, metric_id=met.id, anomaly_type="background_load", severity="high",
                responsible_process="svc_update.exe")
    db.add(a)
    db.commit()
    return a, met, m


class TestContextInExplanation:
    """A IA precisa saber se a pessoa estava usando o computador e se o programa pesado era o da tela."""

    def _prompt(self, db, suffix, **context):
        from app.services.ai_service import build_context, build_prompt
        a, met, m = _context_scenario(db, suffix, **context)
        return build_prompt(a, m, build_context(db, a, met, m), "leigo")

    def test_background_with_nobody_using(self, db):
        prompt = self._prompt(db, "a", user_idle_seconds=900.0, top_proc_user_driven=0, top_proc_trust=0,
                              top_proc_known=0)
        line = next(l for l in prompt.splitlines() if l.startswith("CONTEXTO DE USO:"))
        assert "ninguém" in line
        assert "não era o que estava na tela" in line
        assert "nunca visto" in line and "sem assinatura" in line

    def test_game_on_screen_with_someone_using(self, db):
        prompt = self._prompt(db, "b", user_idle_seconds=4.0, top_proc_user_driven=1, top_proc_trust=2,
                              top_proc_known=1)
        line = next(l for l in prompt.splitlines() if l.startswith("CONTEXTO DE USO:"))
        assert "alguém estava usando" in line
        assert "era o que estava na tela" in line and "não era" not in line
        assert "confiável" in line and "já conhecido" in line

    def test_idle_minutes_become_citable_fact(self, db):
        """Sem a chave, a verificação de números trataria '15 minutos' como invenção."""
        from app.services.ai_service import build_context
        a, met, m = _context_scenario(db, "c", user_idle_seconds=900.0)
        facts = build_context(db, a, met, m)["facts"]
        assert facts["parado_min"]["value"] == 15.0

    def test_without_context_line_is_absent(self, db):
        assert "CONTEXTO DE USO" not in self._prompt(db, "d")
