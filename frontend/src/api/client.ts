import axios from "axios";

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
      localStorage.removeItem("token");
      localStorage.removeItem("username");
      if (window.location.pathname !== "/login") {
        const redirect = `${window.location.pathname}${window.location.search}`;
        window.location.replace(
          `/login?redirect=${encodeURIComponent(redirect)}`
        );
      }
    }
    return Promise.reject(error);
  }
);
