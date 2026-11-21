import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { VitePWA } from "vite-plugin-pwa";
import AutoImport from "unplugin-auto-import/vite";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";
import path from "path";
import fs from "node:fs";

const packageJson = JSON.parse(
  fs.readFileSync(new URL("./package.json", import.meta.url), "utf8"),
) as { version?: string };

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      dts: "src/auto-imports.d.ts",
    }),
    Components({
      resolvers: [ElementPlusResolver({ importStyle: process.env.VITEST ? false : "css" })],
      dts: "src/components.d.ts",
    }),
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
        globIgnores: ["**/*.worker*.js", "**/MonacoEditor*.js"],
        maximumFileSizeToCacheInBytes: 2 * 1024 * 1024,
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
            // API calls — always hit network so auth/SSE streams are never stale or leaked across sessions
            urlPattern: ({ url }) => url.pathname.startsWith("/api/"),
            handler: "NetworkOnly",
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
  define: {
    __APP_VERSION__: JSON.stringify(packageJson.version || "0.0.0"),
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://127.0.0.1:8030",
        changeOrigin: true,
      },
    },
  },
});
