"""Os testes não tocam os modelos de produção.

`docker compose exec backend python -m pytest` é o comando documentado, e o
diretório de modelos do container é o volume real. Os testes treinam modelos
para as máquinas 1 e 2 e, ao apagar a máquina efêmera, apagam o modelo junto:
numa instalação nova — a que a banca rodaria — eram os modelos de verdade.
"""
import os

from app.services import ml_service

PRODUCAO = os.path.realpath(os.path.join(os.path.dirname(ml_service.__file__), "..", "..", "ml", "models"))


def test_testes_nao_usam_o_diretorio_de_modelos_real():
    assert os.path.realpath(ml_service.MODEL_DIR) != PRODUCAO


def test_cada_teste_comeca_sem_modelos():
    """Sem isso, a máquina 1 de um teste carregava o modelo da máquina 1 do anterior."""
    assert os.listdir(ml_service.MODEL_DIR) == []
    assert not ml_service._cache
