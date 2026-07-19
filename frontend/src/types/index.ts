export interface User {
  id: number;
  email: string;
  username: string;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
}

export interface Machine {
  id: number;
  name: string;
  hostname: string;
  os_type?: string;
  os_version?: string;
  agent_token: string;
  is_active: boolean;
  last_seen?: string;
  owner_id: number;
  created_at: string;
}

export interface GPUMetric {
  id: number;
  name: string;
  load_percent?: number;
  mem_used_mb?: number;
  mem_total_mb?: number;
  mem_percent?: number;
  temperature?: number;
  driver?: string;
}

export interface DiskPartition {
  device: string;
  mountpoint: string;
  fstype: string;
  total_gb: number;
  used_gb: number;
  free_gb: number;
  percent: number;
}

export interface Metric {
  id: number;
  machine_id: number;
  timestamp: string;
  cpu_percent?: number;
  mem_percent?: number;
  disk_percent?: number;
  net_bytes_sent?: number;
  net_bytes_recv?: number;
  net_connections?: number;
  process_count?: number;
  cpu_per_core?: number[];
  cpu_freq_current?: number;
  cpu_freq_max?: number;
  cpu_count_logical?: number;
  cpu_count_physical?: number;
  mem_used?: number;
  mem_available?: number;
  mem_total?: number;
  swap_percent?: number;
  swap_used?: number;
  swap_total?: number;
  disk_used?: number;
  disk_free?: number;
  disk_read_bytes?: number;
  disk_write_bytes?: number;
  disk_partitions?: DiskPartition[];
  uptime_seconds?: number;
  load_avg_1?: number;
  load_avg_5?: number;
  load_avg_15?: number;
  gpu_metrics?: GPUMetric[];
  temperatures?: Record<string, any>;
  battery_percent?: number;
  battery_plugged?: boolean;
  battery_secs_left?: number;
}

export interface AIExplanation {
  id: number;
  summary: string;
  detailed_explanation?: string;
  possible_causes?: string[];
  recommendations?: string[];
  severity_justification?: string;
  model_used?: string;
  generated_at: string;
}

export interface Anomaly {
  id: number;
  machine_id: number;
  metric_id?: number;
  detected_at: string;
  anomaly_type: string;
  severity: "low" | "medium" | "high" | "critical";
  anomaly_score?: number;
  affected_metrics?: Record<string, number>;
  responsible_process?: string;
  is_resolved: boolean;
  resolved_at?: string;
  explanation?: AIExplanation;
}

export interface AnomalyStats {
  total: number;
  unresolved: number;
  by_severity: Record<string, number>;
  by_type: Record<string, number>;
}

export const ANOMALY_TYPE_LABELS: Record<string, string> = {
  high_cpu: "Processador Sobrecarregado",
  high_memory: "Memória Quase Esgotada",
  resource_exhaustion: "Computador no Limite (CPU + Memória)",
  disk_full: "Disco Quase Cheio",
  network_spike: "Pico Anormal de Internet",
  memory_leak: "Programa Acumulando Memória",
  cpu_loop: "Programa Travado Consumindo Processador",
  ddos_indicator: "Possível Ataque pela Rede",
  unknown_process: "Programa Desconhecido Detectado",
  suspicious_process: "Programa Suspeito Detectado",
  malware_pattern: "Comportamento Típico de Vírus",
  resource_abuse: "Programa Gastando Mais que o Normal",
  behavioral_change: "Mudança Brusca de Comportamento",
  behavioral_anomaly: "Comportamento Fora do Padrão",
  unknown: "Anomalia Desconhecida",
};

export const SEVERITY_COLORS: Record<string, string> = {
  low: "text-blue-400 bg-blue-400/10 border-blue-400/30",
  medium: "text-yellow-400 bg-yellow-400/10 border-yellow-400/30",
  high: "text-orange-400 bg-orange-400/10 border-orange-400/30",
  critical: "text-red-400 bg-red-400/10 border-red-400/30",
};

export const SEVERITY_LABELS: Record<string, string> = {
  low: "Baixa",
  medium: "Média",
  high: "Alta",
  critical: "Crítica",
};
