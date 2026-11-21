<template>
  <el-dialog
    v-model="visible"
    :title="t('settings.hosts.renewal.title')"
    width="min(520px, calc(100vw - 24px))"
    class="ui-dialog"
    append-to-body
  >
    <el-form label-position="top" class="settings-form" v-loading="loading">
      <el-form-item :label="t('settings.hosts.renewal.nextPayment')">
        <el-date-picker
          v-model="form.next_payment_date"
          type="date"
          value-format="YYYY-MM-DD"
          clearable
        />
        <div v-if="suggestion" class="form-help">
          {{ t("settings.hosts.renewal.suggestion", { date: suggestion }) }}
        </div>
      </el-form-item>
      <el-form-item :label="t('settings.hosts.renewal.expiryDate')" required>
        <el-date-picker
          v-model="form.service_expiry_date"
          type="date"
          value-format="YYYY-MM-DD"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button class="ui-button" @click="visible = false">{{ t("compose.cancel") }}</el-button>
      <el-button
        class="ui-button ui-button--primary"
        type="primary"
        :loading="saving"
        :disabled="loading"
        @click="confirmRenewal"
      >
        {{ t("settings.hosts.renewal.confirm") }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { useI18n } from "vue-i18n";
import { apiErrorMessage } from "@/api/errors";
import { billingApi } from "@/api/billing";

export interface RenewalSavedPayload {
  paymentDate?: string;
  serviceExpiryDate?: string;
}

const props = defineProps<{
  modelValue: boolean;
  hostId: string;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", value: boolean): void;
  (e: "saved", data: RenewalSavedPayload): void;
}>();

const { t } = useI18n();
const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit("update:modelValue", value),
});

const loading = ref(false);
const saving = ref(false);
const suggestion = ref("");
const form = reactive({
  next_payment_date: "",
  service_expiry_date: "",
});
let activeRequestId = 0;

watch(
  () => [props.modelValue, props.hostId] as const,
  async ([open, hostId], _previous, onCleanup) => {
    const requestId = ++activeRequestId;
    if (!open || !hostId) {
      loading.value = false;
      return;
    }
    const controller = new AbortController();
    onCleanup(() => {
      activeRequestId++;
      controller.abort();
    });
    form.next_payment_date = "";
    form.service_expiry_date = "";
    suggestion.value = "";
    loading.value = true;
    try {
      const data = await billingApi.getDates(hostId, controller.signal);
      if (requestId !== activeRequestId || !visible.value) return;
      suggestion.value = data.recommendedNextPaymentDate || "";
      form.next_payment_date = data.recommendedNextPaymentDate || "";
      if (data.serviceExpiryDate) {
        form.service_expiry_date = data.serviceExpiryDate;
      }
    } catch (error) {
      if (requestId !== activeRequestId || !visible.value) return;
      ElMessage.error(apiErrorMessage(error, t("settings.hosts.renewal.loadError")));
    } finally {
      if (requestId === activeRequestId) {
        loading.value = false;
      }
    }
  },
  { immediate: true },
);

async function confirmRenewal() {
  if (loading.value || saving.value || !visible.value || !props.hostId) return;
  if (!form.service_expiry_date) {
    ElMessage.error(t("settings.hosts.renewal.expiryRequired"));
    return;
  }
  const requestId = activeRequestId;
  saving.value = true;
  try {
    const data = await billingApi.renew(props.hostId, {
      next_payment_date: form.next_payment_date || null,
      service_expiry_date: form.service_expiry_date,
    });
    if (requestId !== activeRequestId || !visible.value) return;
    visible.value = false;
    ElMessage.success(t("settings.hosts.renewal.success"));
    emit("saved", {
      paymentDate: data.paymentDate || "",
      serviceExpiryDate: data.serviceExpiryDate || "",
    });
  } catch (error) {
    if (requestId === activeRequestId && visible.value) {
      ElMessage.error(apiErrorMessage(error, t("settings.hosts.renewal.saveError")));
    }
  } finally {
    saving.value = false;
  }
}
</script>
