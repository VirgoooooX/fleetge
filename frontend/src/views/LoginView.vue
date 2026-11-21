<template>
  <div class="login-page">
    <div class="login-backdrop" aria-hidden="true" />

    <div class="login-card">
      <div class="login-header">
        <div class="login-brand-mark" aria-hidden="true">
          <AppLogo />
        </div>
        <h1 class="login-title">{{ t('login.title') }}</h1>
        <p class="login-subtitle">{{ t('login.subtitle') }}</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="0"
        class="login-form"
        @submit.prevent="handleLogin"
      >
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            :placeholder="t('login.username')"
            :prefix-icon="User"
            autocomplete="username"
            size="large"
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            :placeholder="t('login.password')"
            :prefix-icon="Lock"
            autocomplete="current-password"
            show-password
            size="large"
          />
        </el-form-item>
        <el-form-item class="submit-item">
          <el-button
            class="ui-button ui-button--primary ui-button--large login-submit-btn"
            type="primary"
            native-type="submit"
            :loading="loading"
            size="large"
          >
            {{ t('login.submit') }}
          </el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import { Lock, User } from "@lucide/vue";
import type { FormInstance, FormRules } from "element-plus";
import AppLogo from "@/components/AppLogo.vue";
import { useAuthStore } from "@/stores/auth";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();
const { t } = useI18n();

const formRef = ref<FormInstance>();
const loading = ref(false);

const form = reactive({
  username: "",
  password: "",
});

const rules = computed<FormRules>(() => ({
  username: [{ required: true, message: t("login.usernameRequired"), trigger: "blur" }],
  password: [{ required: true, message: t("login.passwordRequired"), trigger: "blur" }],
}));

async function handleLogin() {
  if (loading.value) return;
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;

  loading.value = true;
  try {
    const ok = await auth.login(form.username, form.password);
    if (ok) {
      const rawRedirect = route.query.redirect;
      const safeRedirect =
        typeof rawRedirect === "string" &&
        rawRedirect.startsWith("/") &&
        !rawRedirect.startsWith("//")
          ? rawRedirect
          : "/";
      router.push(safeRedirect);
    }
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  padding: 24px;
  background: var(--surface-base);
  position: relative;
  overflow: hidden;
}

.login-backdrop {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 20% 18%, rgba(37, 99, 235, 0.16), transparent 34rem),
    radial-gradient(circle at 82% 84%, rgba(34, 211, 238, 0.10), transparent 30rem),
    linear-gradient(rgba(148, 163, 184, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.04) 1px, transparent 1px);
  background-size: 100% 100%, 100% 100%, 44px 44px, 44px 44px;
}

[data-theme="light"] .login-backdrop {
  background:
    radial-gradient(circle at 20% 18%, rgba(37, 99, 235, 0.08), transparent 34rem),
    radial-gradient(circle at 82% 84%, rgba(8, 145, 178, 0.05), transparent 30rem),
    linear-gradient(rgba(60, 72, 88, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(60, 72, 88, 0.04) 1px, transparent 1px);
  background-size: 100% 100%, 100% 100%, 44px 44px, 44px 44px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: 36px 32px 32px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--login-card-bg);
  -webkit-backdrop-filter: blur(20px);
  backdrop-filter: blur(20px);
  box-shadow: var(--shadow-lg);
  z-index: 1;
  position: relative;
}

.login-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.login-brand-mark {
  width: 84px;
  height: 84px;
  margin-bottom: 18px;
  filter: drop-shadow(0 8px 20px rgba(37, 99, 235, 0.24));
  transition: transform var(--duration-normal) var(--ease-standard);
}

.login-card:hover .login-brand-mark {
  transform: scale(1.03);
}

.login-title {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.login-subtitle {
  font-size: var(--text-base);
  color: var(--text-secondary);
  margin: 0 0 28px;
  line-height: 1.55;
  font-weight: 500;
  max-width: 320px;
}

.login-form {
  width: 100%;
}

:deep(.el-form-item) {
  margin-bottom: 18px;
}

.submit-item {
  margin-top: 24px;
  margin-bottom: 0;
}

:deep(.el-input__wrapper) {
  border-radius: var(--radius-lg) !important;
  padding: 6px 14px !important;
  border: 1px solid var(--border-subtle) !important;
  background: var(--surface-muted) !important;
  box-shadow: none !important;
  transition:
    border-color var(--duration-normal) var(--ease-standard),
    box-shadow var(--duration-normal) var(--ease-standard),
    background-color var(--duration-normal) var(--ease-standard);
}

[data-theme="light"] .login-form :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.8) !important;
}

:deep(.el-input__wrapper.is-focus) {
  border-color: var(--accent-blue) !important;
  box-shadow: 0 0 0 3px var(--focus-ring) !important;
}

.login-submit-btn {
  width: 100%;
  height: 44px !important;
  border-radius: var(--radius-lg) !important;
  font-size: var(--text-base) !important;
}

@media (max-width: 640px) {
  .login-card {
    padding: 30px 22px 26px;
  }

  .login-title {
    font-size: 22px;
  }
}
</style>
