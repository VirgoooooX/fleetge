import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { VitePWA } from "vite-plugin-pwa";
import path from "path";

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      registerType: "prompt",
      includeAssets: [
        "app-logo.svg",
        "app-logo-mask.svg",
        "app-logo-180.png",
        "app-logo-192.png",
        "app-logo-512.png",
      ],
      manifest: false, // reuse existing public/site.webmanifest
      workbox: {
        globPatterns: ["**/*.{js,css,html,woff2,svg,png,ico}"],
        maximumFileSizeToCacheInBytes: 10 * 1024 * 1024, // 10 MB — accommodate large worker chunks
        runtimeCaching: [
          {
            // Static assets — cache-first for fast repeat loads
            urlPattern: /\.(js|css|woff2|ttf|svg|png|ico)$/,
            handler: "CacheFirst",
            options: {
              cacheName: "static-assets",
              expiration: { maxEntries: 200, maxAgeSeconds: 30 * 24 * 60 * 60 },
            },
          },
          {
            // API calls — network-first, fall back to cache when offline
            urlPattern: /^\/api\/.*/,
            handler: "NetworkFirst",
            options: {
              cacheName: "api-cache",
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 100, maxAgeSeconds: 5 * 60 },
            },
          },
        ],
      },
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
