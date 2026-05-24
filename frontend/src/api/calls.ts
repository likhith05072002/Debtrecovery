import client from "./client";

export interface SentimentPoint {
  turn: number;
  score: number;
  label: string;
}

export interface PromiseInfo {
  amount?: number;
  date?: string;
  status?: string;
}

export interface CallDetail {
  id: string;
  twilio_call_sid?: string;
  borrower_id: string;
  campaign_id?: string;
  status: string;
  outcome?: string;
  duration_seconds?: number;
  turn_count: number;
  interruption_count: number;
  llm_latency_avg_ms?: number;
  tts_latency_avg_ms?: number;
  stt_latency_avg_ms?: number;
  sentiment_trajectory: SentimentPoint[];
  compliance_passed: boolean;
  fdcpa_violations: string[];
  promise?: PromiseInfo;
  started_at?: string;
  ended_at?: string;
  created_at: string;
}

export interface TranscriptTurn {
  turn_index: number;
  speaker: "agent" | "borrower";
  text?: string;
  timestamp_ms?: number;
  sentiment?: number;
  intent?: string;
  entities: Record<string, unknown>;
  barge_in: boolean;
}

export interface CallTranscript {
  call_id: string;
  turns: TranscriptTurn[];
}

export interface CallInitiate {
  borrower_id: string;
  campaign_id?: string;
  strategy_override?: "reminder" | "negotiation" | "settlement" | "escalation";
  scheduled_at?: string;
  language?: string;
  follow_up_enabled?: boolean;
  follow_up_source_call_id?: string;
}

export interface CallInitiateResponse {
  call_id: string;
  twilio_call_sid?: string;
  status: string;
  scheduled_at?: string;
}

export interface AICallAnalysis {
  id: string;
  ai_call_id?: string;
  borrower_id?: string;
  transcription_status: string;
  analysis_status: string;
  transcript_text?: string;
  overall_sentiment?: string;
  sentiment_score?: number;
  willingness_to_pay?: string;
  payment_intent_score?: number;
  key_points: string[];
  borrower_characterization?: string;
  repayment_probability?: number;
  repayment_probability_reason?: string;
  recommended_strategy?: string;
  next_call_talking_points: string[];
  analysis_model?: string;
  analysis_error?: string;
  analysis_completed_at?: string;
  created_at?: string;
}

export interface FollowUpBrief {
  borrower_id: string;
  source_call_id: string;
  source_call_created_at: string;
  analysis_status: string;
  title: string;
  summary: string;
  key_points: string[];
  next_call_focus: string[];
  suggested_opening: string;
  transcript_snippets: string[];
}

export const callsApi = {
  list: async (params?: { status?: string; outcome?: string; skip?: number; limit?: number }) => {
    const res = await client.get<CallDetail[]>("/calls", { params });
    return res.data;
  },
  get: async (id: string) => {
    const res = await client.get<CallDetail>(`/calls/${id}`);
    return res.data;
  },
  getTranscript: async (id: string) => {
    const res = await client.get<CallTranscript>(`/calls/${id}/transcript`);
    return res.data;
  },
  initiate: async (data: CallInitiate) => {
    const res = await client.post<CallInitiateResponse>("/calls/initiate", data);
    return res.data;
  },
  update: async (id: string, data: { outcome?: string }) => {
    const res = await client.patch<CallDetail>(`/calls/${id}`, data);
    return res.data;
  },
  cancel: async (id: string) => {
    await client.delete(`/calls/${id}`);
  },
  getAnalysis: async (id: string): Promise<AICallAnalysis> => {
    const res = await client.get<AICallAnalysis>(`/calls/${id}/analysis`);
    return res.data;
  },
  getFollowUpBrief: async (id: string): Promise<FollowUpBrief> => {
    const res = await client.get<FollowUpBrief>(`/calls/${id}/follow-up-brief`);
    return res.data;
  },
};
