import axios from "axios";
import { redirectToLogin } from "./authRedirect";

export const apiClient = axios.create({
  baseURL: "", // Same origin with vite proxy
  timeout: 30000,
});

// Request interceptor — inject JWT
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor — handle 401
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      redirectToLogin();
    }
    return Promise.reject(error);
  }
);
