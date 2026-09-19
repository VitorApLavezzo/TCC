"""Nomes em português e classificações compartilhadas dos tipos de aviso."""

ANOMALY_TYPE_LABELS = {
    "high_cpu": "Consumo Excessivo de CPU",
    "high_memory": "Consumo Excessivo de Memória",
    "resource_exhaustion": "Esgotamento de Recursos (CPU + Memória)",
    "disk_full": "Disco Quase Cheio",
    "network_spike": "Pico Anormal de Rede",
    "memory_leak": "Vazamento de Memória Detectado",
    "cpu_loop": "Processo em Loop Infinito (CPU Travada)",
    "ddos_indicator": "Possível Ataque DDoS ou Flood de Rede",
    "unknown_process": "Processo Desconhecido Consumindo Recursos",
    "suspicious_process": "Processo com Nome Suspeito Detectado",
    "malware_pattern": "Padrão de Comportamento Suspeito (Possível Malware)",
    "resource_abuse": "Aplicação Consumindo Recursos Fora do Padrão Normal",
    "behavioral_change": "Mudança Brusca no Comportamento da Máquina",
    "behavioral_anomaly": "Comportamento Anormal Detectado pelo ML",
    "disk_activity": "Atividade de Disco Fora do Padrão",
    "disk_space_change": "Espaço em Disco Mudou Bruscamente",
    "process_surge": "Muitos Programas Abrindo de Uma Vez",
    "gpu_anomaly": "Placa de Vídeo Fora do Padrão",
    "unusual_time": "Atividade em Horário Incomum",
    "thermal_throttling": "Processador Reduzindo a Velocidade por Calor",
    "cooling_degradation": "Refrigeração Perdendo Eficiência",
    "unexpected_shutdown": "Desligamento Inesperado",
    "disk_health": "Disco com Sinais de Desgaste",
    "hardware_errors": "Erros de Hardware Registrados",
    "process_masquerading": "Programa Disfarçado de Arquivo do Sistema",
    "suspicious_parent": "Documento Abrindo Ferramenta do Sistema",
    "suspicious_command": "Comando Suspeito em Execução",
    "ransomware_canary": "Arquivo-Isca Alterado (Possível Sequestro de Dados)",
    "beaconing": "Programa Contatando a Internet em Intervalos Regulares",
    "disk_forecast": "Disco Vai Encher em Breve",
    "outbreak_suspected": "Mesmo Programa Surgindo em Vários Computadores",
    "unknown": "Anomalia Desconhecida",
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
    "high_cpu", "high_memory", "resource_exhaustion", "cpu_loop", "memory_leak", "resource_abuse",
    "behavioral_change", "behavioral_anomaly", "network_spike", "disk_activity", "disk_space_change",
    "process_surge", "gpu_anomaly", "unusual_time", "thermal_throttling",
}

# Avisos de segurança: nunca silenciados pelo modo atividade pesada, e o
# feedback "é normal" cria exceção só para o programa — nunca deixa o
# detector inteiro menos sensível.
SECURITY_TYPES = {
    "unknown_process", "suspicious_process", "malware_pattern", "process_masquerading",
    "suspicious_parent", "suspicious_command", "ransomware_canary", "beaconing", "ddos_indicator",
    "outbreak_suspected",
}

# Avisos cuja evidência não depende de histórico: uma isca de ransomware
# tocada é uma isca tocada também no primeiro minuto de vida da máquina.
# Estes atravessam o período de aprendizado e notificam normalmente.
LEARNING_EXEMPT = {
    "ransomware_canary", "process_masquerading", "suspicious_command",
    "suspicious_parent", "suspicious_process",
}

# Onde o cartão "e se eu fechar?" faz sentido. Ele fala de memória e
# processador liberados, então só cabe onde o problema É memória ou
# processador. Num aviso de rede ou de disco a conta está certa e a
# recomendação é irrelevante; num aviso de segurança é pior que irrelevante,
# porque enquadra uma ameaça como incômodo de desempenho.
COUNTERFACTUAL_TYPES = {
    "high_cpu", "high_memory", "resource_exhaustion", "memory_leak",
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
