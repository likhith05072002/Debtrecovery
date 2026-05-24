import client from "./client";

export interface ComplianceEvent {
  id: string;
  borrower_id: string;
  call_id?: string;
  event_type: string;
  severity: "info" | "warning" | "violation";
  description?: string;
  auto_actioned?: boolean;
  created_at: string;
}

export const complianceApi = {
  getEvents: async (borrower_id: string) => {
    const res = await client.get<ComplianceEvent[]>(`/compliance/events/${borrower_id}`);
    return res.data;
  },
  listRecent: async (severity?: string) => {
    const params = severity ? { severity } : {};
    const res = await client.get<ComplianceEvent[]>("/compliance/events", { params });
    return res.data;
  },
  recordConsent: async (borrower_id: string) => {
    const res = await client.post(`/compliance/consent/${borrower_id}`);
    return res.data;
  },
};
