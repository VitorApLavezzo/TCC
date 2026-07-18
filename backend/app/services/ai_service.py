import json
import httpx
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.config import settings
from app.models.metric import Metric
from app.models.anomaly import Anomaly
from app.models.machine import Machine

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
    "unknown": "Anomalia Desconhecida",
}

SEVERITY_LABELS = {
    "low": "Baixa",
    "medium": "Média",
    "high": "Alta",
    "critical": "Crítica",
}


def _call_ollama(prompt: str) -> str:
    """Chama Ollama diretamente via API nativa (sem dependência do openai SDK)."""
    url = f"{settings.OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3},
    }
    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        return response.json()["response"]


def generate_explanation(anomaly: Anomaly, metric: Metric, machine: Machine, db: Session) -> Optional[Dict[str, Any]]:
    recent_metrics = (
        db.query(Metric)
        .filter(Metric.machine_id == machine.id)
        .order_by(Metric.timestamp.desc())
        .limit(10)
        .all()
    )

    history_summary = []
    for m in reversed(recent_metrics):
        history_summary.append({
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
            "cpu_percent": m.cpu_percent,
            "mem_percent": m.mem_percent,
            "disk_percent": m.disk_percent,
            "net_connections": m.net_connections,
        })

    # Busca top processos desta coleta
    from app.models.process import ProcessSnapshot
    top_procs = (
        db.query(ProcessSnapshot)
        .filter(ProcessSnapshot.metric_id == metric.id)
        .order_by(ProcessSnapshot.cpu_percent.desc())
        .limit(5)
        .all()
    )
    proc_list = [
        {
            "name": p.name,
            "pid": p.pid,
            "cpu_percent": p.cpu_percent,
            "mem_percent": p.mem_percent,
            "username": p.username,
            "cmdline": p.cmdline[:100] if p.cmdline else None,
        }
        for p in top_procs
    ]

    # Extrai detalhes comportamentais do campo affected_metrics
    affected = anomaly.affected_metrics or {}
    behavior_details = affected.pop("_behavior", None) if isinstance(affected, dict) else None

    context = {
        "machine": {
            "name": machine.name,
            "hostname": machine.hostname,
            "os": f"{machine.os_type} {machine.os_version or ''}".strip(),
        },
        "anomaly": {
            "type": ANOMALY_TYPE_LABELS.get(anomaly.anomaly_type, anomaly.anomaly_type),
            "severity": SEVERITY_LABELS.get(anomaly.severity, anomaly.severity),
            "isolation_forest_score": anomaly.anomaly_score,
            "affected_metrics": affected,
            "responsible_process": anomaly.responsible_process,
            "behavior_details": behavior_details,
        },
        "current_metrics": {
            "cpu_percent": metric.cpu_percent,
            "mem_percent": metric.mem_percent,
            "swap_percent": metric.swap_percent,
            "disk_percent": metric.disk_percent,
            "net_bytes_sent_kb": round((metric.net_bytes_sent or 0) / 1024, 1),
            "net_bytes_recv_kb": round((metric.net_bytes_recv or 0) / 1024, 1),
            "net_connections": metric.net_connections,
            "load_avg_1": metric.load_avg_1,
            "process_count": metric.process_count,
        },
        "top_processes": proc_list,
        "recent_history": history_summary,
    }

    # Prompt compacto para melhor performance em modelos locais
    anomaly_info = context["anomaly"]
    metrics_info = context["current_metrics"]
    top_proc = context["top_processes"][0] if context["top_processes"] else None

    prompt = f"""Analise esta anomalia em um computador e responda em JSON.

ANOMALIA: {anomaly_info["type"]} | Severidade: {anomaly_info["severity"]}
PROCESSO: {anomaly_info["responsible_process"] or "desconhecido"}
CPU: {metrics_info["cpu_percent"]}% | RAM: {metrics_info["mem_percent"]}% | Disco: {metrics_info["disk_percent"]}% | Conexões: {metrics_info["net_connections"]}
{"PROCESSO TOP: " + top_proc["name"] + " CPU:" + str(top_proc["cpu_percent"]) + "% MEM:" + str(top_proc["mem_percent"]) + "%" if top_proc else ""}
DETALHES: {json.dumps(anomaly_info.get("behavior_details") or anomaly_info.get("affected_metrics", {}), ensure_ascii=False)}

Responda APENAS com JSON válido:
{{"summary":"frase curta resumindo o problema","detailed_explanation":"explicação em 2 parágrafos","possible_causes":["causa 1","causa 2","causa 3"],"recommendations":["ação 1","ação 2","ação 3"],"severity_justification":"justificativa breve"}}"""

    try:
        raw = _call_ollama(prompt)

        # Extrai JSON mesmo se o modelo retornar texto antes/depois
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON found in response")

        result = json.loads(raw[start:end])
        result["model_used"] = settings.OLLAMA_MODEL
        return result

    except Exception as e:
        print(f"Ollama error: {e}")
        return _generate_fallback_explanation(anomaly, metric)


def _generate_fallback_explanation(anomaly: Anomaly, metric: Metric) -> Dict[str, Any]:
    type_label = ANOMALY_TYPE_LABELS.get(anomaly.anomaly_type, anomaly.anomaly_type)
    affected = anomaly.affected_metrics or {}

    causes_map = {
        "high_cpu": [
            "Processo intensivo em execução (compilação, renderização, encoding de vídeo)",
            "Malware ou minerador de criptomoedas consumindo CPU em background",
            "Atualização do sistema operacional ou antivírus rodando em segundo plano",
            "Aplicação com bug ou travada em loop de processamento",
        ],
        "high_memory": [
            "Muitas aplicações abertas simultaneamente esgotando a RAM disponível",
            "Vazamento de memória em alguma aplicação que não libera o que alocou",
            "Cache do sistema crescendo sem ser liberado",
            "Aplicação carregando arquivos muito grandes na memória",
        ],
        "memory_leak": [
            "Aplicação com bug no gerenciamento de memória — aloca mas nunca libera",
            "Plugin, extensão ou biblioteca de terceiros com vazamento",
            "Serviço em background que acumula dados na RAM ao longo do tempo",
            "Framework ou runtime com vazamento em versão desatualizada",
        ],
        "cpu_loop": [
            "Aplicação travada em um laço infinito sem condição de saída",
            "Thread bloqueada esperando por um recurso que nunca será liberado (deadlock)",
            "Bug de lógica que impede a conclusão de uma operação",
            "Processo consumindo 100% de um núcleo de CPU continuamente",
        ],
        "ddos_indicator": [
            "Ataque de negação de serviço (DDoS) direcionado a esta máquina ou rede",
            "Flood de conexões TCP/UDP por bot ou script malicioso",
            "Amplification attack usando esta máquina como vetor ou alvo",
            "Varredura de portas agressiva por scanner externo",
        ],
        "unknown_process": [
            "Software instalado recentemente que ainda não estava no histórico desta máquina",
            "Script ou executável rodando pela primeira vez após uma atualização",
            "Processo iniciado por outro software sem conhecimento do usuário",
            "Possível software não autorizado instalado no sistema",
        ],
        "suspicious_process": [
            "Ferramenta de mineração de criptomoedas (cryptominer) detectada pelo nome",
            "Ferramenta de ataque ou exploit conhecida em execução",
            "Malware que usa nomes de processos conhecidos da lista de ameaças",
            "Software instalado por terceiros sem consentimento explícito",
        ],
        "malware_pattern": [
            "Malware ou ransomware em execução — combinação de comportamentos suspeitos detectada",
            "Processo executando a partir de pasta temporária (técnica comum de evasão)",
            "Processo sem linha de comando visível consumindo CPU e rede simultaneamente",
            "Processo privilegiado com comportamento anômalo indicando possível comprometimento",
        ],
        "resource_abuse": [
            "Aplicação com comportamento diferente do normal — possível bug ou atualização problemática",
            "Plugin ou extensão instalada recentemente alterando o desempenho da aplicação",
            "Arquivo corrupto sendo processado repetidamente pela aplicação",
            "Configuração alterada que aumentou a carga de trabalho da aplicação",
        ],
        "behavioral_change": [
            "Novo software instalado alterando o padrão de uso de recursos do sistema",
            "Atualização do sistema operacional ou de drivers modificando o comportamento",
            "Mudança no padrão de uso do usuário (novas tarefas, mais abas abertas, etc.)",
            "Evento externo como sincronização de nuvem, backup automático ou indexação",
            "Possível comprometimento do sistema alterando o comportamento geral",
        ],
        "disk_full": [
            "Logs de sistema ou de aplicações acumulados sem rotação ou limpeza",
            "Arquivos temporários e de cache ocupando espaço crescente",
            "Downloads, backups locais ou snapshots consumindo o espaço disponível",
            "Banco de dados ou arquivo de log crescendo sem limite configurado",
        ],
        "network_spike": [
            "Download ou upload de arquivo grande em andamento",
            "Sincronização de serviço de nuvem (OneDrive, Google Drive, Dropbox)",
            "Atualização de sistema ou aplicação baixando pacotes grandes",
            "Possível exfiltração de dados ou tráfego malicioso",
        ],
        "resource_exhaustion": [
            "Múltiplas aplicações pesadas abertas simultaneamente esgotando CPU e RAM",
            "Processo sem controle consumindo todos os recursos disponíveis",
            "Sistema subdimensionado para a carga de trabalho atual",
            "Combinação de alta demanda + possível vazamento ou loop em algum processo",
        ],
    }

    recs_map = {
        "high_cpu": [
            "Abra o Gerenciador de Tarefas (Ctrl+Shift+Esc) e identifique o processo com maior CPU",
            "Encerre o processo suspeito se não for essencial",
            "Execute um antivírus atualizado para descartar malware",
            "Reinicie o computador se o problema persistir após encerrar o processo",
        ],
        "high_memory": [
            "Feche abas e aplicações desnecessárias para liberar RAM",
            "Reinicie o navegador ou aplicação com maior consumo de memória",
            "Verifique se há processo com crescimento contínuo de memória",
            "Considere adicionar mais RAM se o problema for recorrente com uso normal",
        ],
        "memory_leak": [
            "Reinicie imediatamente a aplicação identificada com crescimento contínuo de memória",
            "Verifique se há atualização disponível para a aplicação — bugs de leak costumam ser corrigidos",
            "Reporte o comportamento ao desenvolvedor ou suporte da aplicação",
            "Configure um reinício agendado da aplicação como solução temporária",
        ],
        "cpu_loop": [
            "Force o encerramento do processo travado no Gerenciador de Tarefas",
            "Reinicie a aplicação e evite a operação que causou o travamento",
            "Verifique os logs da aplicação para identificar a causa do loop",
            "Atualize a aplicação — loops infinitos frequentemente são bugs conhecidos",
        ],
        "ddos_indicator": [
            "Verifique as conexões ativas com: netstat -an | findstr ESTABLISHED",
            "Contate seu provedor de internet para ativar proteção anti-DDoS",
            "Configure o firewall para bloquear IPs com excesso de conexões",
            "Considere mover o serviço para uma CDN com proteção DDoS integrada",
        ],
        "unknown_process": [
            "Pesquise o nome do processo na internet para verificar se é legítimo",
            "Verifique o caminho completo do executável no Gerenciador de Tarefas",
            "Execute um escaneamento completo com antivírus atualizado",
            "Se não reconhecer o processo, encerre-o e monitore se reaparece",
        ],
        "suspicious_process": [
            "Encerre o processo imediatamente e quarentene o arquivo executável",
            "Execute uma varredura completa com antivírus e anti-malware (Malwarebytes)",
            "Verifique programas instalados recentemente e remova os desconhecidos",
            "Considere fazer backup dos dados importantes e reinstalar o sistema se confirmado",
        ],
        "malware_pattern": [
            "Desconecte a máquina da rede imediatamente para conter possível propagação",
            "Execute varredura com antivírus em modo seguro (Safe Mode)",
            "Verifique e altere senhas de contas acessadas nesta máquina",
            "Considere formatar e reinstalar o sistema operacional se a ameaça for confirmada",
        ],
        "resource_abuse": [
            "Reinicie a aplicação identificada para restaurar o comportamento normal",
            "Verifique se houve atualização recente da aplicação que possa ter introduzido um bug",
            "Desative plugins ou extensões recentemente instalados na aplicação",
            "Monitore o consumo após reiniciar para confirmar se o problema foi resolvido",
        ],
        "behavioral_change": [
            "Verifique o que mudou no sistema recentemente (instalações, atualizações, novos arquivos)",
            "Revise processos em execução em busca de algo novo ou desconhecido",
            "Execute um antivírus para descartar comprometimento por malware",
            "Monitore as métricas nas próximas horas para avaliar se é comportamento temporário",
        ],
        "disk_full": [
            "Execute a Limpeza de Disco do Windows ou 'df -h' no Linux para ver o uso",
            "Remova arquivos temporários: %TEMP% no Windows ou /tmp no Linux",
            "Verifique logs de sistema e configure rotação automática",
            "Mova arquivos grandes para HD externo ou armazenamento em nuvem",
        ],
        "network_spike": [
            "Verifique qual processo está gerando tráfego no Resource Monitor ou iftop",
            "Pause sincronizações de nuvem temporariamente para confirmar a causa",
            "Monitore conexões ativas com netstat para identificar destinos suspeitos",
            "Execute um antivírus se nenhuma causa legítima for identificada",
        ],
        "resource_exhaustion": [
            "Reinicie o computador imediatamente para liberar todos os recursos",
            "Feche todas as aplicações não essenciais antes de reiniciar",
            "Após reiniciar, identifique quais aplicações são realmente necessárias",
            "Avalie upgrade de hardware (mais RAM, SSD mais rápido) se o problema for frequente",
        ],
    }

    causes = []
    recs = []

    process_text = f" O processo **{anomaly.responsible_process}** foi identificado como responsável." if anomaly.responsible_process else ""
    sev_label = SEVERITY_LABELS.get(anomaly.severity, anomaly.severity)

    return {
        "summary": f"{type_label} detectado com severidade {sev_label}.{process_text}",
        "detailed_explanation": (
            f"O sistema identificou um comportamento fora do padrão normal desta máquina. "
            f"A análise foi realizada combinando o modelo Isolation Forest — treinado com o histórico "
            f"desta máquina específica — e detectores de padrões comportamentais. "
            f"No momento da detecção: CPU {metric.cpu_percent:.0f}%, "
            f"Memória {metric.mem_percent:.0f}%, Disco {metric.disk_percent:.0f}%."
        ),
        "possible_causes": causes,
        "recommendations": recs,
        "severity_justification": f"Classificado como severidade {sev_label} com base nos valores das métricas e no desvio em relação ao comportamento histórico desta máquina.",
        "model_used": "análise local",
    }
