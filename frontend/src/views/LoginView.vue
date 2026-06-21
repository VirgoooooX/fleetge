<template>
  <div class="login-page">
    <!-- Tech Grid Background -->
    <div class="tech-grid" aria-hidden="true"></div>
    
    <!-- High-Tech Background Decor Elements -->
    <div class="tech-bg-element HUD-radar" aria-hidden="true">
      <svg viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="50" cy="50" r="45" stroke="var(--accent-blue)" stroke-width="0.5" stroke-dasharray="2 4" />
        <circle cx="50" cy="50" r="35" stroke="var(--accent-cyan)" stroke-width="0.5" />
        <circle cx="50" cy="50" r="25" stroke="var(--accent-blue)" stroke-width="0.5" stroke-dasharray="10 5" />
        <line x1="50" y1="5" x2="50" y2="95" stroke="rgba(96, 165, 250, 0.15)" stroke-width="0.5" />
        <line x1="5" y1="50" x2="95" y2="50" stroke="rgba(96, 165, 250, 0.15)" stroke-width="0.5" />
      </svg>
    </div>

    <div class="tech-bg-element yaml-snippet font-mono" aria-hidden="true">
      <pre>
services:
  fleetge:
    image: ghcr.io/virgooooox/fleetge:latest
    restart: unless-stopped
    ports:
      - "80:8000"
      </pre>
    </div>

    <div class="tech-bg-element docker-cli font-mono" aria-hidden="true">
      <pre>
$ docker ps -a
CONTAINER ID   IMAGE          STATUS
a1b2c3d4e5f6   nginx:alpine   Up 3 hours
f6e5d4c3b2a1   postgres:15    Exited (0)
      </pre>
    </div>

    <div class="tech-bg-element node-topology" aria-hidden="true">
      <svg viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="20" cy="20" r="4" fill="var(--accent-blue)" />
        <circle cx="80" cy="30" r="5" fill="var(--accent-cyan)" />
        <circle cx="50" cy="70" r="4" fill="var(--success)" />
        <circle cx="30" cy="50" r="3" fill="var(--accent-blue)" />
        <line x1="20" y1="20" x2="30" y2="50" stroke="rgba(96, 165, 250, 0.2)" stroke-width="0.75" stroke-dasharray="2 2" />
        <line x1="30" y1="50" x2="50" y2="70" stroke="rgba(96, 165, 250, 0.2)" stroke-width="0.75" stroke-dasharray="2 2" />
        <line x1="80" y1="30" x2="50" y2="70" stroke="rgba(34, 211, 238, 0.2)" stroke-width="0.75" stroke-dasharray="2 2" />
        <line x1="20" y1="20" x2="80" y2="30" stroke="rgba(96, 165, 250, 0.1)" stroke-width="0.5" />
      </svg>
    </div>
    
    <!-- Floating Tech Metrics Decor -->
    <div class="tech-decor decor-top-left font-mono">SYS_STATUS: ONLINE</div>
    <div class="tech-decor decor-top-right font-mono">DOCKER_PORT: 8000</div>
    <div class="tech-decor decor-bottom-left font-mono">FLEET_NODES: 6/6 ACTIVE</div>
    <div class="tech-decor decor-bottom-right font-mono">ENCRYPTION: FERNET_ENABLED</div>

    <div class="login-card">
      <div class="login-card-glow" aria-hidden="true"></div>
      <!-- HUD Corner Brackets -->
      <div class="hud-corner hud-tl"></div>
      <div class="hud-corner hud-tr"></div>
      <div class="hud-corner hud-bl"></div>
      <div class="hud-corner hud-br"></div>

      <div class="login-header">
        <div class="login-brand-mark" aria-hidden="true">
          <AppLogo />
        </div>
        <h2 class="login-title">{{ t('login.title') }}</h2>
        <p class="login-subtitle">{{ t('login.subtitle') }}</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        @keyup.enter="handleLogin"
        label-width="0"
        class="login-form"
      >
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            :placeholder="t('login.username')"
            :prefix-icon="User"
            size="large"
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            :placeholder="t('login.password')"
            :prefix-icon="Lock"
            show-password
            size="large"
          />
        </el-form-item>
        <el-form-item class="submit-item">
          <el-button
            class="ui-button ui-button--primary ui-button--large"
            type="primary"
            :loading="loading"
            style="width: 100%"
            size="large"
            @click="handleLogin"
          >
            {{ t('login.submit') }}
          </el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from "vue";
import { useRouter, useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import { User, Lock } from "@element-plus/icons-vue";
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

const rules: FormRules = {
  username: [{ required: true, message: t('login.usernameRequired'), trigger: "blur" }],
  password: [{ required: true, message: t('login.passwordRequired'), trigger: "blur" }],
};

async function handleLogin() {
  if (loading.value) return;
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;

  loading.value = true;
  try {
    const ok = await auth.login(form.username, form.password);
    if (ok) {
      const redirect = (route.query.redirect as string) || "/";
      router.push(redirect);
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

/* Cyber Tech Grid Background overlay */
.tech-grid {
  position: absolute;
  inset: 0;
  background-image: 
    linear-gradient(rgba(96, 165, 250, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(96, 165, 250, 0.035) 1px, transparent 1px);
  background-size: 48px 48px;
  z-index: 0;
  pointer-events: none;
  animation: gridScroll 45s linear infinite;
}

@keyframes gridScroll {
  from { background-position: 0 0; }
  to { background-position: 48px 48px; }
}

/* Floating Tech Decor text widgets */
.tech-decor {
  position: absolute;
  font-size: 10px;
  font-family: var(--font-mono), monospace;
  color: var(--accent-cyan);
  opacity: 0.3;
  z-index: 1;
  pointer-events: none;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  font-weight: 700;
}

.decor-top-left { top: 32px; left: 32px; animation: floatDecor 4s infinite alternate ease-in-out; }
.decor-top-right { top: 32px; right: 32px; animation: floatDecor 4.5s infinite alternate ease-in-out 0.5s; }
.decor-bottom-left { bottom: 32px; left: 32px; animation: floatDecor 5s infinite alternate ease-in-out 1s; }
.decor-bottom-right { bottom: 32px; right: 32px; animation: floatDecor 5.5s infinite alternate ease-in-out 1.5s; }

@keyframes floatDecor {
  0% { transform: translateY(0); opacity: 0.25; }
  100% { transform: translateY(-8px); opacity: 0.45; }
}

/* Background Tech Decor Elements */
.tech-bg-element {
  position: absolute;
  pointer-events: none;
  opacity: 0.08;
  z-index: 0;
  transition: opacity 0.5s ease;
}

[data-theme="light"] .tech-bg-element {
  opacity: 0.05;
}

.HUD-radar {
  width: 280px;
  height: 280px;
  top: 10%;
  right: 12%;
  animation: radarRotate 40s linear infinite;
}

@keyframes radarRotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.yaml-snippet {
  top: 25%;
  left: 8%;
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.4;
  transform: rotate(-4deg);
  animation: floatBGElement 8s infinite alternate ease-in-out;
}

.docker-cli {
  bottom: 20%;
  right: 8%;
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.4;
  transform: rotate(3deg);
  animation: floatBGElement 10s infinite alternate ease-in-out 1s;
}

.node-topology {
  width: 180px;
  height: 180px;
  bottom: 15%;
  left: 12%;
  animation: floatBGElement 12s infinite alternate ease-in-out 2s;
}

@keyframes floatBGElement {
  0% { transform: translateY(0) rotate(var(--rot, 0deg)); }
  100% { transform: translateY(-12px) rotate(var(--rot, 0deg)); }
}

.yaml-snippet { --rot: -4deg; }
.docker-cli { --rot: 3deg; }

/* Dynamic floating background mesh */
.login-page::before,
.login-page::after {
  content: '';
  position: absolute;
  border-radius: 50%;
  filter: blur(120px);
  z-index: 0;
  pointer-events: none;
  opacity: 0.65;
}

.login-page::before {
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, rgba(37, 99, 235, 0.32) 0%, transparent 80%);
  top: -10%;
  left: 15%;
  animation: floatBG1 22s infinite alternate ease-in-out;
}

.login-page::after {
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.2) 0%, transparent 80%);
  bottom: -10%;
  right: 15%;
  animation: floatBG2 26s infinite alternate ease-in-out;
}

@keyframes floatBG1 {
  0% { transform: translate(0, 0) scale(1); }
  100% { transform: translate(100px, 60px) scale(1.15); }
}

@keyframes floatBG2 {
  0% { transform: translate(0, 0) scale(1); }
  100% { transform: translate(-100px, -80px) scale(1.1); }
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: 48px 36px;
  border: 1px solid var(--border-subtle);
  border-radius: 24px;
  background: var(--login-card-bg);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  box-shadow: 0 28px 75px rgba(0, 0, 0, 0.25);
  z-index: 1;
  position: relative;
  animation: cardSlideIn 0.8s cubic-bezier(0.16, 1, 0.3, 1) both;
}

/* Conic Glowing Border Outline */
@keyframes rotateGlow {
  0% { transform: translate(-50%, -50%) rotate(0deg); }
  100% { transform: translate(-50%, -50%) rotate(360deg); }
}

.login-card-glow {
  position: absolute;
  inset: -1.5px;
  border-radius: 24px;
  overflow: hidden;
  z-index: -1;
  pointer-events: none;
}

.login-card-glow::before {
  content: '';
  position: absolute;
  width: 200%;
  aspect-ratio: 1 / 1;
  top: 50%;
  left: 50%;
  background: conic-gradient(from 0deg at 50% 50%, transparent 20%, var(--accent-blue), var(--accent-cyan), transparent 60%);
  animation: rotateGlow 8s linear infinite;
  opacity: 0.75;
}

@keyframes cardSlideIn {
  from {
    opacity: 0;
    transform: translateY(40px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

/* HUD Corner Brackets */
.hud-corner {
  position: absolute;
  width: 14px;
  height: 14px;
  border-color: rgba(96, 165, 250, 0.35);
  border-style: solid;
  border-width: 0;
  pointer-events: none;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  z-index: 2;
}

.hud-tl { top: 14px; left: 14px; border-top-width: 2px; border-left-width: 2px; }
.hud-tr { top: 14px; right: 14px; border-top-width: 2px; border-right-width: 2px; }
.hud-bl { bottom: 14px; left: 14px; border-bottom-width: 2px; border-left-width: 2px; }
.hud-br { bottom: 14px; right: 14px; border-bottom-width: 2px; border-right-width: 2px; }

.login-card:hover .hud-corner {
  border-color: var(--accent-cyan);
  transform: scale(1.1);
}

.login-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.login-brand-mark {
  width: 144px;
  height: 144px;
  margin-bottom: 28px;
  filter: drop-shadow(0 12px 32px rgba(37, 99, 235, 0.35));
  transition: transform 0.6s cubic-bezier(0.175, 0.885, 0.32, 1.275);
  animation: logoPulse 4s infinite alternate ease-in-out;
}

@keyframes logoPulse {
  0% { transform: scale(1); }
  100% { transform: scale(1.04); filter: drop-shadow(0 12px 30px rgba(37, 99, 235, 0.38)); }
}

.login-card:hover .login-brand-mark {
  transform: rotate(360deg) scale(1.08);
  animation: none;
}

.login-title {
  font-size: 32px;
  font-weight: 900;
  letter-spacing: -0.03em;
  color: var(--text-primary);
  margin: 0 0 10px;
  background: linear-gradient(135deg, var(--text-primary) 30%, var(--accent-blue) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.login-subtitle {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0 0 40px;
  line-height: 1.6;
  font-weight: 500;
  max-width: 320px;
}

.login-form {
  width: 100%;
}

:deep(.el-form-item) {
  margin-bottom: 24px;
}

.submit-item {
  margin-top: 32px;
  margin-bottom: 0;
}

:deep(.el-input__wrapper) {
  border-radius: 10px !important;
  padding: 6px 16px !important;
  border: 1px solid var(--border-subtle) !important;
  background: rgba(15, 23, 42, 0.18) !important;
  box-shadow: none !important;
  transition: all 0.3s ease !important;
}

[data-theme="light"] :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.65) !important;
}

:deep(.el-input__wrapper.is-focus) {
  border-color: var(--accent-blue) !important;
  box-shadow: 0 0 0 3px var(--focus-ring) !important;
  background: rgba(15, 23, 42, 0.28) !important;
}

[data-theme="light"] :deep(.el-input__wrapper.is-focus) {
  background: rgba(255, 255, 255, 0.9) !important;
}

/* Shining button animation */
:deep(.el-button--primary) {
  border-radius: 10px !important;
  height: 48px !important;
  font-weight: 700 !important;
  font-size: 15px !important;
  background: linear-gradient(135deg, var(--accent-blue) 0%, #1d4ed8 100%) !important;
  border: none !important;
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.22) !important;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1) !important;
  position: relative;
  overflow: hidden;
}

:deep(.el-button--primary)::after {
  content: '';
  position: absolute;
  top: 0;
  left: -150%;
  width: 50%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.25), transparent);
  transform: skewX(-25deg);
  animation: shineSweep 4s infinite linear;
}

@keyframes shineSweep {
  0% { left: -150%; }
  50% { left: 150%; }
  100% { left: 150%; }
}

:deep(.el-button--primary:hover) {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.38) !important;
  background: linear-gradient(135deg, var(--accent-blue) 0%, #2563eb 100%) !important;
}

:deep(.el-button--primary:active) {
  transform: translateY(0);
}

@media (max-width: 576px) {
  .login-card {
    padding: 40px 24px;
    border-radius: 20px;
  }
  
  .login-title {
    font-size: 28px;
  }

  .tech-decor,
  .tech-bg-element {
    display: none;
  }
}
</style>
