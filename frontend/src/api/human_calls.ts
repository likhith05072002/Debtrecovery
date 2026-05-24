import client from "./client";

export interface SpeakerTurn {
  speaker: number;   // 0 = first detected speaker, 1 = second, etc.
  start_ms: number;
  end_ms: number;
  text: string;
  confidence: number;
}

export interface CallAnalysis {
  id: string;
  human_call_id: string;
  borrower_id: string;
  transcription_status: string;   // pending | processing | completed | failed
  analysis_status: string;        // pending | processing | completed | failed
  transcript_text?: string;
  transcript_speakers: SpeakerTurn[];
  overall_sentiment?: string;     // hostile | negative | neutral | positive | cooperative
  sentiment_score?: number;       // -1.0 to 1.0
  willingness_to_pay?: string;    // high | medium | low | refused
  payment_intent_score?: number;  // 0.0 to 1.0
  key_points: string[];
  borrower_characterization?: string;
  repayment_probability?: number; // 0.0 to 1.0
  repayment_probability_reason?: string;
  recommended_strategy?: string;  // reminder | negotiation | settlement | escalation
  next_call_talking_points: string[];
  analysis_model?: string;
  analysis_error?: string;
  analysis_completed_at?: string;
  created_at?: string;
}

export interface HumanCallRecord {
  id: string;
  borrower_id?: string;
  human_agent_id?: string;
  human_agent_name?: string;
  twilio_call_sid?: string;
  status: string;
  contact_name?: string;
  contact_phone?: string;
  amount_due?: number;
  days_overdue?: number;
  duration_seconds?: number;
  started_at?: string;
  ended_at?: string;
  created_at: string;
}

export interface HumanCallInitiateRequest {
  contact_name: string;
  contact_phone: string;
  agent_id?: string;
  agent_name?: string;
  amount_due?: number;
  days_overdue?: number;
}

export interface HumanCallInitiateResponse {
  call_id: string;
  twilio_call_sid?: string;
  status: string;
  contact_name?: string;
  borrower_id?: string;
}

export const humanCallsApi = {
  getToken: async (agentId?: string): Promise<{ token: string; identity: string }> => {
    const res = await client.get<{ token: string; identity: string }>("/human-calls/token", {
      params: agentId ? { agent_id: agentId } : undefined,
    });
    return res.data;
  },

  list: async (params?: { skip?: number; limit?: number }): Promise<HumanCallRecord[]> => {
    const res = await client.get<HumanCallRecord[]>("/human-calls", { params });
    return res.data;
  },

  get: async (callId: string): Promise<HumanCallRecord> => {
    const res = await client.get<HumanCallRecord>(`/human-calls/${callId}`);
    return res.data;
  },

  initiate: async (data: HumanCallInitiateRequest): Promise<HumanCallInitiateResponse> => {
    const res = await client.post<HumanCallInitiateResponse>("/human-calls/initiate", data);
    return res.data;
  },

  getAnalysis: async (callId: string): Promise<CallAnalysis> => {
    const res = await client.get<CallAnalysis>(`/human-calls/${callId}/analysis`);
    return res.data;
  },

  listByBorrower: async (borrowerId: string): Promise<HumanCallRecord[]> => {
    const res = await client.get<HumanCallRecord[]>("/human-calls", { params: { borrower_id: borrowerId } });
    return res.data;
  },
};
