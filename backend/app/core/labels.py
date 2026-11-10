"""Nomes em português e classificações compartilhadas dos tipos de aviso.

Os nomes são os mesmos de `frontend/src/types/index.ts` — um teste do frontend compara os dois.
"""

ANOMALY_TYPE_LABELS = {
    "high_cpu": "Processador sobrecarregado",
    "background_load": "Programa pesado rodando em segundo plano",
    "high_memory": "Memória quase esgotada",
    "resource_exhaustion": "Computador no limite (processador e memória)",
    "disk_full": "Disco quase cheio",
    "network_spike": "Pico anormal de internet",
    "memory_leak": "Programa acumulando memória",
    "cpu_loop": "Programa travado consumindo o processador",
    "ddos_indicator": "Possível ataque pela rede",
    "unknown_process": "Programa desconhecido detectado",
    "suspicious_process": "Programa suspeito detectado",
    "malware_pattern": "Comportamento típico de vírus",
    "resource_abuse": "Programa gastando mais que o normal",
    "behavioral_change": "Mudança brusca de comportamento",
    "behavioral_anomaly": "Comportamento fora do padrão",
    "disk_activity": "Disco trabalhando sem parar",
    "disk_space_change": "Espaço em disco mudou de repente",
    "process_surge": "Muitos programas abrindo de uma vez",
    "gpu_anomaly": "Placa de vídeo fora do padrão",
    "unusual_time": "Atividade em horário incomum",
    "thermal_throttling": "Processador reduzindo a velocidade por calor",
    "cooling_degradation": "Refrigeração perdendo eficiência",
    "unexpected_shutdown": "Desligamento inesperado",
    "disk_health": "Disco com sinais de desgaste",
    "hardware_errors": "Erros de hardware registrados",
    "process_masquerading": "Programa disfarçado de arquivo do sistema",
    "suspicious_parent": "Documento abrindo ferramenta do sistema",
    "suspicious_command": "Comando suspeito em execução",
    "ransomware_canary": "Arquivo-isca alterado (possível sequestro de dados)",
    "beaconing": "Programa contatando a internet em intervalos regulares",
    "login_failures": "Várias tentativas de senha erradas",
    "out_of_memory": "Computador ficou sem memória",
    "disk_forecast": "Disco vai encher em breve",
    "outbreak_suspected": "Mesmo programa surgindo em vários computadores",
    "model_drift": "O normal deste computador mudou",
    "hardware_failure_risk": "Risco de falha de peça",
    "change_regression": "Piora depois de uma atualização",
    "unknown": "Aviso de tipo desconhecido",
}

SEVERITY_LABELS = {
    "low": "Baixa",
    "medium": "Média",
    "high": "Alta",
    "critical": "Crítica",
}

SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}

# Avisos de desempenho: silenciados no "modo atividade pesada" e ajustáveis
# pelo feedback. Uma pessoa jogando espera processador alto.
PERFORMANCE_TYPES = {
    "high_cpu", "background_load", "high_memory", "resource_exhaustion", "cpu_loop", "memory_leak", "resource_abuse",
    "behavioral_change", "behavioral_anomaly", "network_spike", "disk_activity", "disk_space_change",
    "process_surge", "gpu_anomaly", "unusual_time", "thermal_throttling",
}

# Avisos de segurança: nunca silenciados pelo modo atividade pesada, e o
# feedback "é normal" cria exceção só para o programa — nunca deixa o
# detector inteiro menos sensível.
SECURITY_TYPES = {
    "unknown_process", "suspicious_process", "malware_pattern", "process_masquerading",
    "suspicious_parent", "suspicious_command", "ransomware_canary", "beaconing", "ddos_indicator",
    "outbreak_suspected", "login_failures",
}

# Avisos cuja evidência não depende de histórico: atravessam o período de
# aprendizado e notificam normalmente.
LEARNING_EXEMPT = {
    "ransomware_canary", "process_masquerading", "suspicious_command",
    "suspicious_parent", "suspicious_process",
    "hardware_failure_risk", "change_regression", "login_failures", "out_of_memory",
}

# Onde o cartão "e se eu fechar?" faz sentido: só onde o problema é memória ou
# processador. Num aviso de segurança enquadraria uma ameaça como incômodo.
COUNTERFACTUAL_TYPES = {
    "high_cpu", "background_load", "high_memory", "resource_exhaustion", "memory_leak",
    "cpu_loop", "resource_abuse", "thermal_throttling",
}

# Qual detector produziu cada tipo — é a unidade de calibração
DETECTOR_OF_TYPE = {
    "memory_leak": "memory_leak",
    "cpu_loop": "cpu_loop",
    "ddos_indicator": "ddos_indicators",
    "unknown_process": "new_suspicious_process",
    "suspicious_process": "new_suspicious_process",
    "malware_pattern": "malware_pattern",
    "resource_abuse": "resource_abuse",
    "behavioral_change": "behavioral_change",
    "thermal_throttling": "thermal_throttling",
    "process_masquerading": "process_masquerading",
    "suspicious_parent": "suspicious_parent",
    "suspicious_command": "suspicious_parent",
    "high_cpu": "ml",
    "background_load": "ml",
    "high_memory": "ml",
    "resource_exhaustion": "ml",
    "disk_full": "ml",
    "network_spike": "ml",
    "disk_activity": "ml",
    "disk_space_change": "ml",
    "process_surge": "ml",
    "gpu_anomaly": "ml",
    "unusual_time": "ml",
    "behavioral_anomaly": "ml",
}

# Tipos em que o programa responsável identifica o aviso: dois programas
# desconhecidos diferentes são dois avisos, não um repetido.
PROCESS_SPECIFIC_TYPES = {
    "memory_leak", "cpu_loop", "unknown_process", "suspicious_process", "malware_pattern",
    "resource_abuse", "process_masquerading", "suspicious_parent", "suspicious_command", "beaconing",
}
