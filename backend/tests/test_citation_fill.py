"""Quando o modelo escreve só o marcador, sem o número ("CPU ([[cpu_agora]])"), a frase
mostrada não pode ficar com um buraco: entra o valor medido gravado com a explicação."""
from datetime import datetime, timezone

from app.schemas.anomaly import ExplanationOut
from app.services.ai_service import sanitize_explanation, strip_citations

FACTS = {
    "cpu_agora": {"label": "Processador agora", "value": 2.7, "unit": "%"},
    "ram_agora": {"label": "Memória agora", "value": 38.2, "unit": "%"},
    "parado_min": {"label": "Minutos sem teclado e mouse", "value": 12.0, "unit": "min"},
    "conexoes_agora": {"label": "Conexões de rede agora", "value": 213.0, "unit": ""},
    "liberaria_gb": {"label": "Memória liberada", "value": 1.25, "unit": "GB"},
}


def test_bare_marker_gets_the_measured_value():
    text = "consumindo CPU ([[cpu_agora]]) e memória ([[ram_agora]])"
    assert strip_citations(text, FACTS) == "consumindo CPU (2,7%) e memória (38,2%)"


def test_units_other_than_percent_are_spaced():
    assert strip_citations("ninguém usava o teclado havia [[parado_min]].", FACTS) == \
        "ninguém usava o teclado havia 12 min."
    assert strip_citations("liberando aproximadamente [[liberaria_gb]]", FACTS) == "liberando aproximadamente 1,25 GB"


def test_marker_after_a_number_is_only_removed():
    assert strip_citations("a memória está em 91% [[ram_agora]]", FACTS) == "a memória está em 91%"
    assert strip_citations("213 conexões de rede simultâneas [[conexoes_agora]]", FACTS) == \
        "213 conexões de rede simultâneas"
    assert strip_citations("um número 2.5x acima do normal deste computador [[conexoes_agora]]", FACTS) == \
        "um número 2.5x acima do normal deste computador"


def test_same_marker_twice_in_a_sentence_is_filled_once():
    assert strip_citations("ficou parado por [[parado_min]] seguidos [[parado_min]] hoje", FACTS) == \
        "ficou parado por 12 min seguidos hoje"
    assert strip_citations("parado por 12 min [[parado_min]] seguidos [[parado_min]]", FACTS) == \
        "parado por 12 min seguidos"


def test_number_of_the_previous_sentence_or_citation_does_not_count():
    assert strip_citations("Processador em 50% [[cpu_agora]], sem uso de memória ([[ram_agora]])", FACTS) == \
        "Processador em 50%, sem uso de memória (38,2%)"
    assert strip_citations("A CPU estava em 50%. A memória ([[ram_agora]]) subiu.", FACTS) == \
        "A CPU estava em 50%. A memória (38,2%) subiu."


def test_unknown_key_and_no_facts_keep_the_old_behaviour():
    assert strip_citations("CPU [[nao_existe]] alta", FACTS) == "CPU alta"
    assert strip_citations("CPU ([[cpu_agora]]) alta") == "CPU alta"
    assert strip_citations("rode Get-Process() [[cpu_agora]]") == "rode Get-Process()"


def test_unit_already_written_after_the_marker_is_not_repeated():
    assert strip_citations("parados há [[parado_min]] minutos", FACTS) == "parados há 12 minutos"
    assert strip_citations("liberando [[liberaria_gb]] GB", FACTS) == "liberando 1,25 GB"


def test_sanitize_uses_the_stored_evidence_also_in_variants():
    data = {"summary": "CPU em [[cpu_agora]]", "possible_causes": ["memória ([[ram_agora]])"],
            "evidence": FACTS, "variants": {"leigo": {"summary": "parado havia [[parado_min]]"}}}
    out = sanitize_explanation(data)
    assert out["summary"] == "CPU em 2,7%"
    assert out["possible_causes"] == ["memória (38,2%)"]
    assert out["variants"]["leigo"]["summary"] == "parado havia 12 min"


def test_api_schema_fills_the_gaps():
    out = ExplanationOut(id=1, summary="CPU em [[cpu_agora]]", detailed_explanation=None, possible_causes=None,
                         recommendations=["feche o que usa ([[ram_agora]])"], severity_justification=None,
                         model_used="x", generated_at=datetime.now(timezone.utc), evidence=FACTS)
    assert out.summary == "CPU em 2,7%"
    assert out.recommendations == ["feche o que usa (38,2%)"]
