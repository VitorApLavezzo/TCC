"""O cartão "e se eu fechar?" só pode falar do que tem a ver com o aviso.

Caso real que originou estes testes (anomalia #357): um aviso de possível
ataque pela rede, sem processo responsável identificado, exibia "Se você
fechar opera (6 janelas/processos), a memória deve cair de 16% para cerca de
10%" — o navegador foi escolhido por ser o maior consumidor de memória da
máquina, e a sugestão não tinha relação nenhuma com rede.
"""
from types import SimpleNamespace


def _metric(**over):
    base = {"cpu_percent": 40.0, "mem_percent": 16.0, "cpu_count_logical": 8}
    return SimpleNamespace(**{**base, **over})


def _grupos():
    return [
        {"name": "opera", "cpu": 30.0, "mem": 6.0, "rss": 2e9, "instances": 6},
        {"name": "Code.exe", "cpu": 12.0, "mem": 4.0, "rss": 1.3e9, "instances": 3},
    ]


def _anomalia(tipo, responsavel=None):
    return SimpleNamespace(anomaly_type=tipo, responsible_process=responsavel)


class TestQuandoOCartaoNaoDeveAparecer:
    def test_sem_processo_responsavel_nao_escolhe_um_qualquer(self):
        """O caso da anomalia #357: nenhum responsável identificado."""
        from app.services.ai_service import counterfactual
        assert counterfactual(_anomalia("ddos_indicator"), _metric(), _grupos()) is None

    def test_aviso_de_rede_nao_ganha_cartao_de_memoria(self):
        """Fechar o navegador não faz nada por um pico de tráfego."""
        from app.services.ai_service import counterfactual
        assert counterfactual(_anomalia("network_spike", "opera"), _metric(), _grupos()) is None

    def test_aviso_de_disco_nao_ganha_cartao_de_memoria(self):
        from app.services.ai_service import counterfactual
        assert counterfactual(_anomalia("disk_activity", "opera"), _metric(), _grupos()) is None

    def test_aviso_de_seguranca_nao_fala_em_aliviar_memoria(self):
        """"Feche o vírus e ganhe 2 GB" é a moldura errada para uma ameaça."""
        from app.services.ai_service import counterfactual
        assert counterfactual(_anomalia("malware_pattern", "opera"), _metric(), _grupos()) is None

    def test_responsavel_que_nao_esta_na_lista_nao_vira_o_maior(self):
        from app.services.ai_service import counterfactual
        assert counterfactual(_anomalia("high_memory", "sumiu.exe"), _metric(), _grupos()) is None


class TestQuandoOCartaoAjuda:
    def test_memoria_alta_mantem_o_cartao(self):
        from app.services.ai_service import counterfactual
        cf = counterfactual(_anomalia("high_memory", "opera"), _metric(), _grupos())
        assert cf is not None and cf["process"] == "opera"
        assert "memória" in cf["sentence"]

    def test_cpu_alta_mantem_o_cartao(self):
        from app.services.ai_service import counterfactual
        # 80% somados em 8 núcleos = 10% do computador: acima do limiar em que
        # vale a pena dizer que fechar alivia o processador
        pesado = [{"name": "opera", "cpu": 80.0, "mem": 6.0, "rss": 2e9, "instances": 6}]
        cf = counterfactual(_anomalia("high_cpu", "opera"), _metric(), pesado)
        assert cf is not None and "processador" in cf["sentence"]

    def test_processador_reduzindo_por_calor_tambem_alivia_fechando(self):
        from app.services.ai_service import counterfactual
        assert counterfactual(_anomalia("thermal_throttling", "opera"), _metric(), _grupos()) is not None
