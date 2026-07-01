import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

export const botApi = {
  status: () => api.get("/bot/status").then((r) => r.data),
  start: () => api.post("/bot/start").then((r) => r.data),
  stop: () => api.post("/bot/stop").then((r) => r.data),
  logs: (since = 0) => api.get(`/bot/logs?since=${since}`).then((r) => r.data),
  clearLogs: () => api.delete("/bot/logs").then((r) => r.data),
  config: () => api.get("/bot/config").then((r) => r.data),
  updateConfig: (payload) => api.put("/bot/config", payload).then((r) => r.data),
  commands: () => api.get("/bot/commands").then((r) => r.data),
  audit: () => api.get("/bot/audit").then((r) => r.data),
};
