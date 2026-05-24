import client from "./client";

export interface BorrowerProfile {
  id: string;
  external_id: string;
  first_name?: string;
  last_name?: string;
  time_zone: string;
  preferred_language: string;
  original_creditor?: string;
  principal_amount: string;
  current_balance: string;
  days_past_due: number;
  debt_type?: string;
  do_not_call: boolean;
  opted_out: boolean;
  bankruptcy_filed: boolean;
  consent_recorded: boolean;
  engagement_score?: number;
  repayment_likelihood?: number;
  sentiment_trend?: number;
  avoidance_score?: number;
  promise_kept_rate?: number;
  total_calls?: number;
  successful_contacts?: number;
  created_at: string;
  updated_at: string;
}

export interface BorrowerCreate {
  external_id: string;
  phone: string;
  first_name?: string;
  last_name?: string;
  time_zone?: string;
  preferred_language?: string;
  original_creditor?: string;
  principal_amount: number;
  current_balance: number;
  days_past_due?: number;
  debt_type?: string;
  consent_recorded?: boolean;
}

export interface BorrowerUpdate {
  first_name?: string;
  last_name?: string;
  current_balance?: number;
  days_past_due?: number;
  consent_recorded?: boolean;
}

export const borrowersApi = {
  list: async (params?: { search?: string; opted_out?: boolean; do_not_call?: boolean; skip?: number; limit?: number }) => {
    const res = await client.get<BorrowerProfile[]>("/borrowers", { params });
    return res.data;
  },
  get: async (id: string) => {
    const res = await client.get<BorrowerProfile>(`/borrowers/${id}`);
    return res.data;
  },
  create: async (data: BorrowerCreate) => {
    const res = await client.post<BorrowerProfile>("/borrowers", data);
    return res.data;
  },
  update: async (id: string, data: BorrowerUpdate) => {
    const res = await client.patch<BorrowerProfile>(`/borrowers/${id}`, data);
    return res.data;
  },
  optOut: async (id: string, reason?: string) => {
    const res = await client.post(`/borrowers/${id}/opt-out`, { reason });
    return res.data;
  },
  remove: async (id: string) => {
    await client.delete(`/borrowers/${id}`);
  },
  getComplianceEvents: async (id: string) => {
    const res = await client.get(`/compliance/events/${id}`);
    return res.data;
  },
  getBehavioralEvents: async (id: string, eventType?: string) => {
    const res = await client.get(`/borrowers/${id}/behavioral-events`, {
      params: eventType ? { event_type: eventType } : undefined,
    });
    return res.data as Array<{
      id: string;
      call_id: string | null;
      event_type: string;
      event_data: Record<string, unknown>;
      detected_at: string;
    }>;
  },
};
