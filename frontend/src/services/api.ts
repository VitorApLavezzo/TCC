import axios from "axios";
import { reportFailure, reportSuccess } from "../lib/connection";

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
      localStorage.removeItem("token");
      // `sessao=expirada` faz o login explicar por que a pessoa voltou pra cá,
      // em vez de simplesmente aparecer na tela de login sem motivo.
      if (!window.location.pathname.startsWith("/login")) {
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
};

export const explanationsApi = {
  regenerate: (anomalyId: number) => api.post(`/explanations/${anomalyId}/regenerate`),
};

export const anomaliesApi = {
  list: (params?: { machine_id?: number; hours?: number; severity?: string; unresolved_only?: boolean }) =>
    api.get("/anomalies", { params }),
  get: (id: number) => api.get(`/anomalies/${id}`),
  resolve: (id: number, is_resolved: boolean) => api.patch(`/anomalies/${id}/resolve`, { is_resolved }),
  stats: (hours = 24) => api.get(`/anomalies/stats/summary?hours=${hours}`),
};

export default api;
