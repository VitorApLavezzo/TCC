import axios from "axios";

const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("token");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

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
  create: (data: { name: string; hostname: string; os_type?: string }) =>
    api.post("/machines", data),
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
  list: (machineId: number, hours = 24) =>
    api.get(`/metrics/${machineId}?hours=${hours}`),
  latest: (machineId: number) => api.get(`/metrics/${machineId}/latest`),
};

export const explanationsApi = {
  regenerate: (anomalyId: number) => api.post(`/explanations/${anomalyId}/regenerate`),
};

export const anomaliesApi = {
  list: (params?: { machine_id?: number; hours?: number; severity?: string; unresolved_only?: boolean }) =>
    api.get("/anomalies", { params }),
  get: (id: number) => api.get(`/anomalies/${id}`),
  resolve: (id: number, is_resolved: boolean) =>
    api.patch(`/anomalies/${id}/resolve`, { is_resolved }),
  stats: (hours = 24) => api.get(`/anomalies/stats/summary?hours=${hours}`),
};

export default api;
