"""Os testes não tocam os modelos de produção (no container, o diretório de modelos é o volume real)."""
import os

from app.services import ml_service

PRODUCTION_DIR = os.path.realpath(os.path.join(os.path.dirname(ml_service.__file__), "..", "..", "ml", "models"))


def test_tests_do_not_use_real_model_dir():
    assert os.path.realpath(ml_service.MODEL_DIR) != PRODUCTION_DIR


def test_each_test_starts_without_models():
    """Sem isso, a máquina 1 de um teste carregava o modelo da máquina 1 do anterior."""
    assert os.listdir(ml_service.MODEL_DIR) == []
    assert not ml_service._cache
