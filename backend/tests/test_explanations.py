"""
A checagem dos números que a IA escreve.

É a parte mais delicada da explicação: rigorosa demais, rejeita respostas boas
e o usuário fica sem explicação; frouxa demais, deixa passar número inventado.
Estes testes fixam o comportamento nos dois sentidos.
"""
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
