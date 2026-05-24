import client from "./client";

export interface CampaignCreate {
  name: string;
  strategy_type: "auto" | "reminder" | "negotiation" | "settlement" | "escalation";
  max_attempts?: number;
  call_window_start?: string;
  call_window_end?: string;
  retry_interval_hrs?: number;
  settlement_floor_pct?: number;
}

export interface CampaignResponse {
  id: string;
  name: string;
  strategy_type: string;
  status: string;
  max_attempts: number;
  created_at: string;
}

export const campaignsApi = {
  list: async () => {
    const res = await client.get<CampaignResponse[]>("/campaigns");
    return res.data;
  },
  get: async (id: string) => {
    const res = await client.get<CampaignResponse>(`/campaigns/${id}`);
    return res.data;
  },
  create: async (data: CampaignCreate) => {
    const res = await client.post<CampaignResponse>("/campaigns", data);
    return res.data;
  },
  addBorrowers: async (id: string, borrower_ids: string[]) => {
    const res = await client.post<{ added: number }>(`/campaigns/${id}/borrowers`, { borrower_ids });
    return res.data;
  },
  start: async (id: string) => {
    const res = await client.post(`/campaigns/${id}/start`);
    return res.data;
  },
};
