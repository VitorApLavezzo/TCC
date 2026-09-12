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
  os_pretty?: string;
  system_info?: Record<string, any>;
  agent_version?: string;
  ai_privacy?: "any" | "local_only" | "no_ai";
  focus_mode_until?: string;
  focus_mode_reason?: string;
  network_isolated?: boolean;
  collection_interval?: number;
  is_demo?: boolean;
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
  battery_health_percent?: number;
  battery_cycle_count?: number;
}

export interface EvidenceFact {
  label: string;
  value: number;
  unit: string;
}

export interface Verification {
  claims: number;
  verified: number;
  unverified: string[];
  passed: boolean;
}

export interface Counterfactual {
  process: string;
  instances: number;
  mem_now: number;
  mem_after: number;
  cpu_now: number;
  cpu_after: number;
  mem_freed_gb: number;
  sentence: string;
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
  language_level?: LanguageLevel;
  variants?: Record<string, ExplanationVariant>;
  evidence?: Record<string, EvidenceFact>;
  verification?: Verification | null;
  counterfactual?: Counterfactual | null;
  data_destination?: "local" | "cloud" | "none";
  provider_attempts?: { provider: string; destination: string; ok: boolean; duration_ms: number; error?: string }[];
  user_rating?: number;
  judge_scores?: Record<string, number> & { comentario?: string };
}

export interface ExplanationVariant {
  summary: string;
  detailed_explanation?: string;
  possible_causes?: string[];
  recommendations?: string[];
  severity_justification?: string;
  model_used?: string;
}

export type LanguageLevel = "leigo" | "intermediario" | "tecnico";

export interface StepProgress {
  step_index: number;
  status: "done" | "not_helped" | "skipped" | "pending";
  extra?: boolean;
}

export interface ExtraStep {
  text: string;
  last_resort?: boolean;
  model_used?: string;
  after_step?: number;
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
  source?: string;
  incident_id?: number;
  related_signals?: { signals: string[]; others: any[] };
  feedback?: "normal" | "problem";
  resolution_cause?: string;
  verification_status?: "watching" | "confirmed" | "failed" | "unverifiable";
  verification_note?: string;
  verified_at?: string;
  steps_progress?: StepProgress[];
  extra_steps?: ExtraStep[];
}

export interface IncidentChainNode {
  signal: string;
  label: string;
  role: string;
}

export interface Incident {
  id: number;
  title?: string;
  severity: string;
  is_open: boolean;
  started_at: string;
  last_activity_at: string;
  chain?: { nodes: IncidentChainNode[]; edges: { from: string; to: string; because: string }[]; roots: string[] };
  narrative?: string;
}

export interface Notification {
  id: number;
  kind: string;
  severity: string;
  title: string;
  body?: string;
  link?: string;
  status: string;
  status_reason?: string;
  created_at: string;
  sent_at?: string;
  read_at?: string;
  anomaly_id?: number;
  /** Por onde saiu de fato: {"panel":"ok","telegram":"ok"}. */
  channels?: Record<string, string>;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  status: "pending" | "done" | "failed";
  tool_trace?: { tool: string; args: any; result_preview: string }[];
  model_used?: string;
  created_at: string;
  conversation_id: string;
  machine_id?: number;
}

export interface DiagnosticResult {
  id: number;
  status: "collecting" | "analyzing" | "done" | "failed";
  summary?: any;
  answer?: { headline: string; culprit?: string | null; explanation: string; actions: string[] };
  model_used?: string;
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
  disk_activity: "Disco Trabalhando Sem Parar",
  disk_space_change: "Espaço em Disco Mudou de Repente",
  process_surge: "Muitos Programas Abrindo de Uma Vez",
  gpu_anomaly: "Placa de Vídeo Fora do Padrão",
  unusual_time: "Atividade em Horário Incomum",
  thermal_throttling: "Processador Reduzindo a Velocidade por Calor",
  cooling_degradation: "Refrigeração Perdendo Eficiência",
  unexpected_shutdown: "Desligamento Inesperado",
  disk_health: "Disco com Sinais de Desgaste",
  hardware_errors: "Erros de Hardware Registrados",
  process_masquerading: "Programa Disfarçado de Arquivo do Sistema",
  suspicious_parent: "Documento Abrindo Ferramenta do Sistema",
  suspicious_command: "Comando Suspeito em Execução",
  ransomware_canary: "Arquivo-Isca Alterado (Possível Sequestro de Dados)",
  beaconing: "Programa Contatando a Internet em Intervalos Regulares",
  disk_forecast: "Disco Vai Encher em Breve",
  outbreak_suspected: "Mesmo Programa Surgindo em Vários Computadores",
  unknown: "Anomalia Desconhecida",
};

/** Tipos de segurança — recebem um selo distinto e nunca são silenciados por engano. */
export const SECURITY_TYPES = new Set([
  "unknown_process", "suspicious_process", "malware_pattern", "process_masquerading", "suspicious_parent",
  "suspicious_command", "ransomware_canary", "beaconing", "ddos_indicator", "outbreak_suspected",
]);

export const LANGUAGE_LEVEL_LABELS: Record<LanguageLevel, string> = {
  leigo: "Simples",
  intermediario: "Intermediário",
  tecnico: "Técnico",
};

/** Quanto o sistema já aprendeu sobre uma máquina. */
export interface LearningStatus {
  collected: number;
  needed: number;
  ml_ready: boolean;
  retrain_every: number;
  model?: { threshold: number; samples: number; trained_at: string } | null;
}

export interface BaselineBand {
  hour: number;
  p5: number;
  p50: number;
  p95: number;
  n: number;
  /** true = não houve leituras bastantes nesta hora; vale a faixa geral. */
  fallback: boolean;
}

/** O normal aprendido de uma máquina, por métrica e por hora do dia. */
export interface LearnedBaseline {
  ready: boolean;
  readings: number;
  days: number;
  current_hour: number;
  metrics: Record<string, { overall: BaselineBand; by_hour: BaselineBand[]; now: BaselineBand }>;
}

export const SEVERITY_LABELS: Record<string, string> = {
  low: "Baixa",
  medium: "Média",
  high: "Alta",
  critical: "Crítica",
};
