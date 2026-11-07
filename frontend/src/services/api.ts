import axios from "axios";
import { reportFailure, reportSuccess } from "../lib/connection";
import { sessionExpired } from "../lib/session";
import { pararAvisosNesteAparelho } from "../lib/push";

const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
  timeout: 20000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => {
    reportSuccess();
    return res;
  },
  (err) => {
    if (err.response?.status === 401) {
      const hadToken = Boolean(err.config?.headers?.Authorization);
      localStorage.removeItem("token");
      // Sessão vencida: sem token para avisar o servidor, ao menos o
      // navegador para de receber os avisos desta conta.
      if (hadToken) void pararAvisosNesteAparelho();
      // `sessao=expirada` faz o login explicar por que a pessoa voltou pra cá,
      // em vez de simplesmente aparecer na tela de login sem motivo.
      if (sessionExpired({ hadToken, pathname: window.location.pathname })) {
        window.location.href = "/login?sessao=expirada";
      }
      return Promise.reject(err);
    }

    // Sem `err.response` = a requisição não chegou ao servidor (rede caída,
    // backend fora, timeout). Isso é o que o indicador de conexão mostra.
    if (!err.response || err.response.status >= 500) {
      reportFailure();
    } else {
      // O servidor respondeu, ainda que recusando: a conexão está de pé.
      reportSuccess();
    }
    return Promise.reject(err);
  }
);

/** Mensagem em português a partir de um erro de requisição qualquer. */
export function errorMessage(err: any, fallback = "Não foi possível concluir a ação.") {
  if (!err?.response) return "Sem conexão com o servidor.";
  const detail = err.response.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  if (err.response.status === 403) return "Você não tem permissão para isso.";
  if (err.response.status === 404) return "Este item não existe mais.";
  if (err.response.status >= 500) return "O servidor encontrou um erro.";
  return fallback;
}

export const authApi = {
  login: (username: string, password: string) => {
    const form = new FormData();
    form.append("username", username);
    form.append("password", password);
    return api.post("/auth/login", form, { headers: { "Content-Type": "multipart/form-data" } });
  },
  register: (email: string, username: string, password: string) =>
    api.post("/auth/register", { email, username, password }),
  me: () => api.get("/auth/me"),
  config: () => api.get("/auth/config"),
  googleLogin: (credential: string) => api.post("/auth/google", { credential }),
};

export const machinesApi = {
  list: () => api.get("/machines"),
  get: (id: number) => api.get(`/machines/${id}`),
  create: (data: { name: string; hostname: string; os_type?: string }) => api.post("/machines", data),
  createEnrollCode: () => api.post("/machines/enroll-code"),
  update: (id: number, data: object) => api.patch(`/machines/${id}`, data),
  delete: (id: number) => api.delete(`/machines/${id}`),
  regenerateToken: (id: number) => api.post(`/machines/${id}/regenerate-token`),
  setRealtime: (id: number, minutes: number) => api.post(`/machines/${id}/realtime`, { minutes }),
  activityLabels: (id: number, days = 7) => api.get(`/machines/${id}/activity-labels`, { params: { days } }),
  markActivity: (id: number, label: string) => api.post(`/machines/${id}/activity-label`, { label }),
};

export const bulkKeysApi = {
  list: () => api.get("/machines/enroll-keys"),
  create: (data: { label?: string; max_uses?: number | null; expires_days?: number }) =>
    api.post("/machines/enroll-keys", data),
  revoke: (id: number) => api.delete(`/machines/enroll-keys/${id}`),
};

export const metricsApi = {
  list: (machineId: number, hours = 24) => api.get(`/metrics/${machineId}?hours=${hours}`),
  latest: (machineId: number) => api.get(`/metrics/${machineId}/latest`),
  /** Progresso do aprendizado: quantas coletas já existem e se o modelo treinou. */
  learning: (machineId: number) => api.get(`/metrics/${machineId}/learning`),
  baseline: (machineId: number, days = 14) => api.get(`/metrics/${machineId}/baseline?days=${days}`),
  window: (machineId: number, center: string, minutes = 10) =>
    api.get(`/metrics/${machineId}/window`, { params: { center, minutes } }),
};

export const explanationsApi = {
  regenerate: (anomalyId: number) => api.post(`/explanations/${anomalyId}/regenerate`),
  variant: (anomalyId: number, level: string) => api.post(`/explanations/${anomalyId}/variant`, { level }),
  rate: (anomalyId: number, rating: 1 | -1, comment?: string) =>
    api.post(`/explanations/${anomalyId}/rate`, { rating, comment }),
  judge: (anomalyId: number) => api.post(`/explanations/${anomalyId}/judge`),
};

export const anomaliesApi = {
  list: (params?: {
    machine_id?: number; hours?: number; severity?: string; anomaly_type?: string; source?: string;
    unresolved_only?: boolean; security_only?: boolean; incident_id?: number; limit?: number;
  }) => api.get("/anomalies", { params }),
  get: (id: number) => api.get(`/anomalies/${id}`),
  context: (id: number) => api.get(`/anomalies/${id}/context`),
  resolve: (id: number, is_resolved: boolean, extra?: { cause?: string; category?: string; verify?: boolean }) =>
    api.patch(`/anomalies/${id}/resolve`, { is_resolved, ...extra }),
  feedback: (id: number, kind: "normal" | "problem", opts?: { scope?: string; hour_from?: number; hour_to?: number; note?: string }) =>
    api.post(`/anomalies/${id}/feedback`, { kind, scope: opts?.scope ?? "process", ...opts }),
  step: (id: number, step_index: number, status: string, extra = false) =>
    api.patch(`/anomalies/${id}/step`, { step_index, status, extra }),
  stats: (hours = 24) => api.get(`/anomalies/stats/summary?hours=${hours}`),
  resolveBulk: (ids: number[], is_resolved = true) =>
    api.post("/anomalies/resolve-bulk", { ids, is_resolved }),
  blackbox: (captureId: number) => api.get(`/anomalies/blackbox/${captureId}`),
};

export const actionsApi = {
  run: (machineId: number, command: string, params: Record<string, any> = {}, anomaly_id?: number) =>
    api.post(`/actions/machine/${machineId}/run`, { command, params, anomaly_id }),
  history: (machineId: number) => api.get(`/actions/machine/${machineId}/history`),
  command: (id: number) => api.get(`/actions/command/${id}`),
  diagnose: (machineId: number) => api.post(`/actions/machine/${machineId}/diagnose`),
  diagnostic: (id: number) => api.get(`/actions/diagnostic/${id}`),
  focusMode: (machineId: number, minutes: number, reason?: string) =>
    api.post(`/actions/machine/${machineId}/focus-mode`, { minutes, reason }),
};

export const chatApi = {
  ask: (question: string, machine_id?: number, conversation_id?: string) =>
    api.post("/chat/ask", { question, machine_id, conversation_id }),
  message: (id: number) => api.get(`/chat/message/${id}`),
  conversation: (id: string) => api.get(`/chat/conversation/${id}`),
  suggestions: (machineId?: number) => api.get("/chat/suggestions", { params: { machine_id: machineId } }),
};

export const insightsApi = {
  baseline: (machineId: number, days = 14) => api.get(`/insights/machine/${machineId}/baseline?days=${days}`),
  forecast: (machineId: number) => api.get(`/insights/machine/${machineId}/forecast`),
  cooling: (machineId: number) => api.get(`/insights/machine/${machineId}/cooling`),
  changes: (machineId: number, days = 60) => api.get(`/insights/machine/${machineId}/changes?days=${days}`),
  energy: (machineId: number, days = 30) => api.get(`/insights/machine/${machineId}/energy?days=${days}`),
  upgrade: (machineId: number) => api.get(`/insights/machine/${machineId}/upgrade`),
  compare: () => api.get("/insights/fleet/compare"),
};

export const reportsApi = {
  list: (machineId: number) => api.get(`/reports/machine/${machineId}`),
  generate: (machineId: number) => api.post(`/reports/machine/${machineId}/generate`),
};

export const reputationApi = {
  lookup: (params: { name?: string; sha256?: string; exe?: string }) => api.get("/reputation/lookup", { params }),
  programs: (machineId: number) => api.get(`/reputation/machine/${machineId}/programs`),
};

export const accountApi = {
  preferences: () => api.get("/account/preferences"),
  updatePreferences: (changes: Record<string, any>) => api.patch("/account/preferences", { changes }),
  notifications: (unread_only = false) => api.get("/account/notifications", { params: { unread_only } }),
  markRead: (ids?: number[]) => api.post("/account/notifications/read", ids ?? null),
  telegramLink: () => api.post("/account/telegram/link"),
  telegramUnlink: () => api.delete("/account/telegram"),
  privacy: (machineId: number) => api.get(`/account/privacy/machine/${machineId}`),
};

export const machinesExtraApi = {
  incidents: (machineId: number) => api.get(`/machines/${machineId}/incidents`),
  setPrivacy: (machineId: number, ai_privacy: string) => api.patch(`/machines/${machineId}`, { ai_privacy }),
};

export const shareApi = {
  create: (anomalyId: number, hours = 72) => api.post(`/share/anomaly/${anomalyId}?hours=${hours}`),
  list: (anomalyId: number) => api.get(`/share/anomaly/${anomalyId}/links`),
  revoke: (token: string) => api.delete(`/share/link/${token}`),
  view: (token: string) => api.get(`/share/view/${token}`),
};

export const evaluationApi = {
  compare: (anomalyId: number) => api.post(`/evaluation/anomaly/${anomalyId}/compare`),
  summary: (days = 30) => api.get(`/evaluation/summary?days=${days}`),
  benchmark: () => api.get(`/evaluation/benchmark`),
  runBenchmark: (realMachineId?: number) =>
    api.post(`/evaluation/benchmark${realMachineId ? `?real_machine_id=${realMachineId}` : ""}`),
  benchmarkDownload: (runId: number, fmt: "md" | "csv") =>
    api.get(`/evaluation/benchmark/${runId}/download?fmt=${fmt}`, { responseType: "text" }),
  // A IA previu um efeito; isto diz se o efeito aconteceu
  fidelity: (days = 90) => api.get(`/evaluation/fidelity?days=${days}`),
  fidelityForAnomaly: (anomalyId: number) => api.get(`/evaluation/anomaly/${anomalyId}/fidelity`),
  // Validação por retenção temporal e ablação das camadas de detecção
  holdout: (machineId: number) => api.get(`/evaluation/holdout/${machineId}`),
  ablation: () => api.get("/evaluation/ablation"),
  runAblation: () => api.post("/evaluation/ablation"),
  // Dado real: sessões marcadas × avisos, e a reprodução com e sem contexto
  real: (machineId: number, days = 14) => api.get(`/evaluation/real/${machineId}`, { params: { days } }),
  runRealReplay: (machineId: number, days = 14) =>
    api.post(`/evaluation/real/${machineId}/replay`, null, { params: { days } }),
};

/** Deriva do modelo, risco de hardware e correlação de atualizações na frota. */
export const reliabilityApi = {
  /** Todos os computadores com veredito, vitais e o pior aviso em aberto. */
  fleetOverview: () => api.get("/insights/fleet/overview"),
  /** Avisos, mudanças, ações e automações de uma máquina, num eixo só. */
  timeline: (machineId: number, days = 30) =>
    api.get(`/insights/machine/${machineId}/timeline`, { params: { days } }),
  drift: (machineId: number, history = false) =>
    api.get(`/insights/machine/${machineId}/drift`, { params: { history } }),
  hardwareRisk: (machineId: number) => api.get(`/insights/machine/${machineId}/hardware-risk`),
  fleetChanges: (days = 45) => api.get("/insights/fleet/changes", { params: { days } }),
};

/** Automação com autonomia graduada. */
export const playbooksApi = {
  list: () => api.get("/playbooks"),
  create: (data: object) => api.post("/playbooks", data),
  update: (id: number, data: object) => api.patch(`/playbooks/${id}`, data),
  remove: (id: number) => api.delete(`/playbooks/${id}`),
  runs: (params?: { limit?: number; anomaly_id?: number }) => api.get("/playbooks/runs", { params }),
  decide: (runId: number, approve: boolean) =>
    api.post(`/playbooks/runs/${runId}/decide`, { approve }),
};

/** Livro de auditoria encadeado por hash. */
export const auditApi = {
  entries: (params?: { limit?: number; kind?: string }) => api.get("/audit/entries", { params }),
  verify: () => api.get("/audit/verify"),
  report: () => api.get("/audit/report", { responseType: "text" }),
};

/** Estudo de compreensão com participantes. */
export const studyApi = {
  config: () => api.get("/study/config"),
  sessions: () => api.get("/study/sessions"),
  create: (data: { participant_code: string; expertise: string; items: number }) =>
    api.post("/study/sessions", data),
  next: (sessionId: number) => api.get(`/study/sessions/${sessionId}/next`),
  answer: (sessionId: number, data: object) => api.post(`/study/sessions/${sessionId}/answer`, data),
  finish: (sessionId: number, data: { sus_answers: number[]; notes?: string }) =>
    api.post(`/study/sessions/${sessionId}/finish`, data),
  results: () => api.get("/study/results"),
  exportCsv: () => api.get("/study/export", { responseType: "text" }),
};

/** Notificação no celular (Web Push). */
export const pushApi = {
  config: () => api.get("/account/push/config"),
  devices: () => api.get("/account/push/devices"),
  subscribe: (subscription: object) => api.post("/account/push/subscribe", subscription),
  unsubscribe: (endpoint: string, token?: string | null) =>
    api.delete("/account/push/subscribe", {
      params: { endpoint },
      ...(token ? { headers: { Authorization: `Bearer ${token}` } } : {}),
    }),
  test: () => api.post("/account/push/test"),
};

export const demoApi = {
  scenarios: () => api.get("/demo/scenarios"),
  start: (scenario: string, auto_run = true) => api.post("/demo/start", { scenario, auto_run }),
  step: (id: number) => api.post(`/demo/${id}/step`),
  status: (id: number) => api.get(`/demo/${id}`),
  list: () => api.get("/demo"),
  cleanup: (id: number) => api.delete(`/demo/${id}`),
};

export const metaApi = {
  policy: () => api.get("/meta/policy"),
};

export default api;
