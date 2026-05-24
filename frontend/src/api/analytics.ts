import client from "./client";

export interface HourlyPoint {
  hour: number;
  calls: number;
  connected: number;
  promise_made: number;
}

export interface OutcomePoint {
  outcome: string;
  count: number;
  percentage: number;
}

export interface DashboardSummary {
  total_calls: number;
  connected_rate: number;
  promise_rate: number;
  avg_call_duration: number;
  payment_collected: string;
  compliance_violations: number;
}

export interface DashboardResponse {
  summary: DashboardSummary;
  hourly_breakdown: HourlyPoint[];
  outcome_distribution: OutcomePoint[];
}

export interface CallQualityResponse {
  avg_stt_latency_ms?: number;
  avg_llm_latency_ms?: number;
  avg_tts_latency_ms?: number;
  avg_e2e_latency_ms?: number;
  barge_in_rate: number;
  stt_confidence_avg: number;
  p95_stt_latency_ms?: number;
  p95_llm_latency_ms?: number;
  p95_tts_latency_ms?: number;
}

export const analyticsApi = {
  getDashboard: async () => {
    const res = await client.get<DashboardResponse>("/analytics/dashboard");
    return res.data;
  },
  getCallQuality: async () => {
    const res = await client.get<CallQualityResponse>("/analytics/call-quality");
    return res.data;
  },
};
