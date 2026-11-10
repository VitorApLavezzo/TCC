"""Comparação por camada: de onde vêm os acertos a mais do sistema completo."""
from app.models.user import User
from app.services.ml_eval import _ablation_sentence, ablation

RULES = [f"ataque_{i}" for i in range(1, 9)]


def _rows(rules, ml, both):
    return [
        {"layer": "regras", "true_positives": len(rules), "hits": rules},
        {"layer": "ml", "true_positives": len(ml), "hits": ml},
        {"layer": "ambas", "true_positives": len(both), "hits": both},
    ]


def test_extra_hits_are_split_between_model_and_the_rest_of_the_system():
    sentence = _ablation_sentence(_rows(RULES, ["ataque_9"], RULES + ["ataque_9", "ataque_10"]))
    assert sentence == ("As regras sozinhas encontraram 8 dos ataques, e o sistema completo, 10. "
                        "Dos acertos a mais, 1 também aparece com o Isolation Forest sozinho e 1 vem "
                        "de outra parte do sistema, como a previsão de disco. "
                        "O Isolation Forest sozinho encontrou 1.")


def test_every_extra_hit_seen_by_the_model_alone():
    sentence = _ablation_sentence(_rows(RULES, ["ataque_9", "ataque_10"], RULES + ["ataque_9", "ataque_10"]))
    assert "2 também aparecem com o Isolation Forest sozinho e 0 vêm de outra parte" in sentence


def test_model_hit_already_found_by_rules_is_not_an_extra():
    sentence = _ablation_sentence(_rows(RULES, ["ataque_1"], RULES + ["ataque_9"]))
    assert "0 também aparecem com o Isolation Forest sozinho e 1 vem de outra parte" in sentence


def test_rows_list_which_attacks_each_layer_found(db):
    owner = User(email="camadas@example.invalid", username="camadas", hashed_password="!")
    db.add(owner)
    db.commit()
    rows = {row["layer"]: row for row in ablation(db, owner.id, names=["cpu_loop", "antivirus_varrendo"])["rows"]}
    assert rows["regras"]["hits"] == ["cpu_loop"]
    assert rows["ambas"]["hits"] == ["cpu_loop"]
