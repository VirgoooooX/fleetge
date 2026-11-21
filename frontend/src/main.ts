import { createApp } from "vue";
import { createPinia } from "pinia";
import { ElLoading } from "element-plus";
import "element-plus/es/components/base/style/css";
import "element-plus/es/components/message/style/css";
import "element-plus/es/components/message-box/style/css";
import "element-plus/es/components/loading/style/css";
import "element-plus/theme-chalk/dark/css-vars.css";
import "@fontsource/geist/latin-400.css";
import "@fontsource/geist/latin-500.css";
import "@fontsource/geist/latin-600.css";
import "@fontsource/geist/latin-700.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import "@fontsource/jetbrains-mono/latin-600.css";
import "@fontsource/jetbrains-mono/latin-700.css";

import App from "./App.vue";
import router from "./router";
import { i18n } from "./i18n";
import { registerSW } from "virtual:pwa-register";
import { initPwaUpdate } from "@/composables/usePwaUpdate";
import "./styles/dashboard.css";
import "./styles/themes.css";
import "./styles/ui.css";
import "./styles/confirm-dialog.css";

// ── PWA: Service Worker registration ──
const updateSW = registerSW({
  onNeedRefresh() {
    initPwaUpdate(async () => {
      await updateSW?.();
    });
  },
  onOfflineReady() {
    console.log("[PWA] App ready for offline use.");
  },
  onRegistered(registration) {
    console.log("[PWA] Service worker registered:", registration);
  },
  onRegisterError(error) {
    console.error("[PWA] Service worker registration failed:", error);
  },
});

const app = createApp(App);

app.use(createPinia());
app.use(router);
app.use(i18n);
app.directive("loading", ElLoading.directive);

app.mount("#app");
