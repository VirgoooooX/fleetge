import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import LoginView from "@/views/LoginView.vue";
import DashboardView from "@/views/DashboardView.vue";
import HostDetailView from "@/views/HostDetailView.vue";
import UpdatesView from "@/views/UpdatesView.vue";
import AuditView from "@/views/AuditView.vue";
import SettingsView from "@/views/SettingsView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: LoginView },
    { path: "/", name: "dashboard", component: DashboardView, meta: { requiresAuth: true } },
    { path: "/hosts/:hostId", name: "host-detail", component: HostDetailView, meta: { requiresAuth: true } },
    { path: "/updates", name: "updates", component: UpdatesView, meta: { requiresAuth: true } },
    { path: "/audit", name: "audit", component: AuditView, meta: { requiresAuth: true } },
    { path: "/settings", name: "settings", component: SettingsView, meta: { requiresAuth: true } },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.beforeEach((to, _from) => {
  const auth = useAuthStore();
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
});

export default router;
