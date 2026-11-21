import { apiClient } from "./client";

interface BillingDates {
  paymentDate: string | null;
  serviceExpiryDate: string | null;
  recommendedNextPaymentDate: string | null;
}

interface RenewalRequest {
  next_payment_date: string | null;
  service_expiry_date: string;
}

const hostPath = (hostId: string) => `/api/hosts/${encodeURIComponent(hostId)}`;

export const billingApi = {
  async getDates(hostId: string, signal?: AbortSignal): Promise<BillingDates> {
    const { data } = await apiClient.get<BillingDates>(`${hostPath(hostId)}/billing`, { signal });
    return data;
  },
  async renew(hostId: string, renewal: RenewalRequest): Promise<BillingDates> {
    const { data } = await apiClient.post<BillingDates>(`${hostPath(hostId)}/renewal`, renewal);
    return data;
  },
};
