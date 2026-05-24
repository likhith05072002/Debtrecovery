import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { borrowersApi } from "@/api/borrowers";
import { callsApi, type CallInitiate } from "@/api/calls";
import { humanCallsApi, type HumanCallRecord } from "@/api/human_calls";
import { callsApi as callsApiClient } from "@/api/calls";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card";
import { Badge, severityVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Select } from "@/components/ui/Input";
import { PageSpinner, Spinner } from "@/components/ui/Spinner";
import { formatCurrency, formatDate, formatDuration } from "@/lib/utils";
import { ArrowLeft, Phone, ShieldOff, CheckCircle, TrendingUp, BrainCircuit, ChevronDown, ChevronRight, User, Bot, AlertTriangle, Clock } from "lucide-react";

function sentimentBadge(sentiment?: string) {
  if (!sentiment) return <span className="text-slate-400">—</span>;
  const map: Record<string, "danger" | "warning" | "default" | "info" | "success"> = {
    hostile: "danger", negative: "warning", neutral: "default", positive: "info", cooperative: "success",
  };
  return <Badge variant={map[sentiment] ?? "default"}>{sentiment}</Badge>;
}

function willingnessBadge(w?: string) {
  if (!w) return <span className="text-slate-400">—</span>;
  const map: Record<string, "danger" | "warning" | "muted" | "success"> = {
    refused: "danger", low: "warning", medium: "muted", high: "success",
  };
  return <Badge variant={map[w] ?? "default"}>{w}</Badge>;
}

function strategyDescription(strategy?: string) {
  const desc: Record<string, string> = {
    reminder: "Gentle payment reminder — borrower is cooperative, low friction approach.",
    negotiation: "Negotiate repayment plan — explore installment options.",
    settlement: "Offer settlement discount — borrower is resistant, accept partial payment.",
    escalation: "Escalate to legal — borrower is uncooperative, formal notices required.",
  };
  return strategy ? desc[strategy] ?? strategy : null;
}

function msToTimestamp(ms: number) {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60).toString().padStart(2, "0");
  const s = (total % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function HumanCallIntelligenceItem({ call }: { call: HumanCallRecord }) {
  const [expanded, setExpanded] = useState(false);

  const { data: analysis } = useQuery({
    queryKey: ["human-analysis", call.id],
    queryFn: () => humanCallsApi.getAnalysis(call.id),
    enabled: expanded,
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.analysis_status;
      return status === "pending" || status === "processing" ? 5000 : false;
    },
  });

  const repaymentPct = analysis?.repayment_probability != null
    ? Math.round(analysis.repayment_probability * 100)
    : null;
  const repaymentColor =
    repaymentPct == null ? "text-slate-400"
    : repaymentPct >= 60 ? "text-green-600"
    : repaymentPct >= 30 ? "text-amber-600"
    : "text-red-600";

  const sentimentScore = analysis?.sentiment_score ?? 0;
  const barPct = Math.round(((sentimentScore + 1) / 2) * 100);
  const barColor = sentimentScore >= 0.3 ? "bg-green-500" : sentimentScore >= -0.2 ? "bg-amber-500" : "bg-red-500";

  const isProcessing = !analysis || analysis.analysis_status === "pending" || analysis.analysis_status === "processing";

  return (
    <div className="border border-slate-100 rounded-xl overflow-hidden">
      {/* Summary row */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-3 bg-white hover:bg-slate-50 transition-colors text-left"
      >
        {expanded ? <ChevronDown size={14} className="text-slate-400 flex-shrink-0" /> : <ChevronRight size={14} className="text-slate-400 flex-shrink-0" />}
        <div className="flex-1 grid grid-cols-4 gap-3 text-sm min-w-0">
          <span className="text-slate-500 text-xs">{formatDate(call.created_at)}</span>
          <span className="font-medium text-slate-700 truncate">{call.human_agent_name ?? "—"}</span>
          <span className="text-slate-500">{formatDuration(call.duration_seconds)}</span>
          <span className="capitalize text-xs">
            <Badge variant={call.status === "completed" ? "success" : call.status === "failed" ? "danger" : "default"}>
              {call.status}
            </Badge>
          </span>
        </div>
      </button>

      {/* Expanded intelligence view */}
      {expanded && (
        <div className="border-t border-slate-100 bg-slate-50 p-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* LEFT — Call info + transcript */}
            <div className="space-y-4">
              <Card>
                <div className="p-4 space-y-3">
                  <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Call Info</h3>
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div><p className="text-xs text-slate-400 mb-0.5">Contact</p><p className="font-medium text-slate-700">{call.contact_name ?? "—"}</p></div>
                    <div><p className="text-xs text-slate-400 mb-0.5">Phone</p><p className="font-medium text-slate-700">{call.contact_phone ?? "—"}</p></div>
                    <div><p className="text-xs text-slate-400 mb-0.5">Agent</p><p className="font-medium text-slate-700">{call.human_agent_name ?? "—"}</p></div>
                    <div><p className="text-xs text-slate-400 mb-0.5">Duration</p><p className="font-medium text-slate-700">{formatDuration(call.duration_seconds)}</p></div>
                    {call.amount_due != null && (
                      <div><p className="text-xs text-slate-400 mb-0.5">Amount Due</p><p className="font-medium text-slate-700">₹{Number(call.amount_due).toLocaleString()}</p></div>
                    )}
                    {call.days_overdue != null && (
                      <div><p className="text-xs text-slate-400 mb-0.5">Days Overdue</p><p className="font-medium text-slate-700">{call.days_overdue} days</p></div>
                    )}
                    <div><p className="text-xs text-slate-400 mb-0.5">Status</p><p className="font-medium text-slate-700 capitalize">{call.status}</p></div>
                  </div>
                </div>
              </Card>

              <Card>
                <div className="p-4">
                  <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-3">Transcript</h3>
                  {!analysis || analysis.transcription_status === "pending" ? (
                    <div className="flex items-center gap-2 text-slate-400 text-sm py-6 justify-center"><Clock size={14} />Transcription pending…</div>
                  ) : analysis.transcription_status === "processing" ? (
                    <div className="flex items-center gap-2 text-blue-600 text-sm py-6 justify-center"><Spinner className="w-4 h-4" />Transcribing…</div>
                  ) : analysis.transcription_status === "failed" ? (
                    <div className="flex items-center gap-2 text-red-500 text-sm py-6 justify-center"><AlertTriangle size={14} />Transcription failed</div>
                  ) : analysis.transcript_speakers && analysis.transcript_speakers.length > 0 ? (
                    <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                      {analysis.transcript_speakers.map((turn, i) => {
                        const isAgent = turn.speaker === 0;
                        return (
                          <div key={i} className={`flex gap-2 ${isAgent ? "" : "flex-row-reverse"}`}>
                            <div className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center mt-0.5 ${isAgent ? "bg-indigo-100" : "bg-slate-100"}`}>
                              {isAgent ? <Bot size={10} className="text-indigo-600" /> : <User size={10} className="text-slate-500" />}
                            </div>
                            <div className={`max-w-[80%] ${isAgent ? "" : "text-right"}`}>
                              <p className={`text-xs font-semibold mb-0.5 ${isAgent ? "text-indigo-600" : "text-slate-500"}`}>
                                {isAgent ? "Agent" : "Borrower"}
                                <span className="ml-1 font-normal text-slate-400">{msToTimestamp(turn.start_ms)}</span>
                              </p>
                              <p className={`text-sm px-3 py-2 rounded-lg ${isAgent ? "bg-indigo-50 text-indigo-900" : "bg-white text-slate-700"}`}>{turn.text}</p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : analysis.transcript_text ? (
                    <p className="text-sm text-slate-600 whitespace-pre-wrap">{analysis.transcript_text}</p>
                  ) : (
                    <p className="text-sm text-slate-400 py-4 text-center">No transcript available</p>
                  )}
                </div>
              </Card>
            </div>

            {/* RIGHT — Intelligence report */}
            <div className="space-y-4">
              {isProcessing ? (
                <div className="flex items-center gap-3 px-4 py-3 bg-amber-50 border border-amber-200 rounded-xl text-amber-700 text-sm">
                  <Spinner className="w-4 h-4 flex-shrink-0" />
                  <span>{!analysis ? "Waiting for analysis…" : analysis.analysis_status === "pending" ? "Analysis queued…" : "Analyzing with GPT-4o…"}</span>
                </div>
              ) : analysis?.analysis_status === "failed" ? (
                <div className="flex items-center gap-3 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
                  <AlertTriangle size={14} className="flex-shrink-0" />
                  <span>Analysis failed{analysis.analysis_error ? `: ${analysis.analysis_error}` : ""}</span>
                </div>
              ) : (
                <div className="flex items-center gap-3 px-4 py-3 bg-green-50 border border-green-200 rounded-xl text-green-700 text-sm">
                  <CheckCircle size={14} className="flex-shrink-0" />
                  <span>Analysis complete{analysis?.analysis_completed_at ? ` · ${formatDate(analysis.analysis_completed_at)}` : ""}</span>
                </div>
              )}

              <Card>
                <div className="p-4 space-y-3">
                  <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Sentiment</h3>
                  <div className="flex items-center gap-4">
                    <div><p className="text-xs text-slate-400 mb-1">Overall</p>{sentimentBadge(analysis?.overall_sentiment)}</div>
                    <div><p className="text-xs text-slate-400 mb-1">Willingness to Pay</p>{willingnessBadge(analysis?.willingness_to_pay)}</div>
                  </div>
                  {analysis?.sentiment_score != null && (
                    <div>
                      <div className="flex justify-between text-xs text-slate-400 mb-1">
                        <span>Hostile</span><span>Score: {analysis.sentiment_score.toFixed(2)}</span><span>Cooperative</span>
                      </div>
                      <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${barPct}%` }} />
                      </div>
                    </div>
                  )}
                </div>
              </Card>

              <Card>
                <div className="p-4">
                  <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Repayment Probability</h3>
                  {repaymentPct != null ? (
                    <>
                      <p className={`text-4xl font-bold ${repaymentColor}`}>{repaymentPct}%</p>
                      {analysis?.repayment_probability_reason && (
                        <p className="text-xs text-slate-500 mt-2 leading-relaxed">{analysis.repayment_probability_reason}</p>
                      )}
                    </>
                  ) : (
                    <p className="text-slate-400 text-sm">Not yet computed</p>
                  )}
                </div>
              </Card>

              {analysis?.borrower_characterization && (
                <Card>
                  <div className="p-4">
                    <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Borrower Characterization</h3>
                    <p className="text-sm text-slate-600 italic leading-relaxed border-l-2 border-indigo-200 pl-3">{analysis.borrower_characterization}</p>
                  </div>
                </Card>
              )}

              {analysis?.key_points && analysis.key_points.length > 0 && (
                <Card>
                  <div className="p-4">
                    <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Key Points</h3>
                    <ul className="space-y-1.5">
                      {analysis.key_points.map((pt, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                          <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-indigo-400 flex-shrink-0" />{pt}
                        </li>
                      ))}
                    </ul>
                  </div>
                </Card>
              )}

              {analysis?.recommended_strategy && (
                <Card>
                  <div className="p-4">
                    <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Recommended Strategy</h3>
                    <Badge variant="info" className="text-sm px-3 py-1 mb-1.5">{analysis.recommended_strategy}</Badge>
                    {strategyDescription(analysis.recommended_strategy) && (
                      <p className="text-xs text-slate-500">{strategyDescription(analysis.recommended_strategy)}</p>
                    )}
                  </div>
                </Card>
              )}

              {analysis?.next_call_talking_points && analysis.next_call_talking_points.length > 0 && (
                <Card>
                  <div className="p-4">
                    <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Next Call Talking Points</h3>
                    <ol className="space-y-2">
                      {analysis.next_call_talking_points.map((pt, i) => (
                        <li key={i} className="flex items-start gap-2.5 text-sm text-slate-600">
                          <span className="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-600 text-white text-xs flex items-center justify-center font-semibold">{i + 1}</span>
                          {pt}
                        </li>
                      ))}
                    </ol>
                  </div>
                </Card>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function AICallIntelligenceItem({ call }: { call: { id: string; created_at: string; duration_seconds?: number; outcome?: string; status: string } }) {
  const [expanded, setExpanded] = useState(false);

  const { data: analysis } = useQuery({
    queryKey: ["ai-call-analysis", call.id],
    queryFn: () => callsApiClient.getAnalysis(call.id),
    enabled: expanded,
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.analysis_status;
      return status === "pending" || status === "processing" ? 5000 : false;
    },
  });

  const repaymentPct = analysis?.repayment_probability != null
    ? Math.round(analysis.repayment_probability * 100)
    : null;
  const repaymentColor =
    repaymentPct == null ? "text-slate-400"
    : repaymentPct >= 60 ? "text-green-600"
    : repaymentPct >= 30 ? "text-amber-600"
    : "text-red-600";

  const sentimentScore = analysis?.sentiment_score ?? 0;
  const barPct = Math.round(((sentimentScore + 1) / 2) * 100);
  const barColor = sentimentScore >= 0.3 ? "bg-green-500" : sentimentScore >= -0.2 ? "bg-amber-500" : "bg-red-500";

  const isProcessing = !analysis || analysis.analysis_status === "pending" || analysis.analysis_status === "processing";

  return (
    <div className="border border-slate-100 rounded-xl overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-3 bg-white hover:bg-slate-50 transition-colors text-left"
      >
        {expanded ? <ChevronDown size={14} className="text-slate-400 flex-shrink-0" /> : <ChevronRight size={14} className="text-slate-400 flex-shrink-0" />}
        <div className="flex-1 grid grid-cols-4 gap-3 text-sm min-w-0">
          <span className="text-slate-500 text-xs">{formatDate(call.created_at)}</span>
          <span className="font-medium text-slate-700">{formatDuration(call.duration_seconds)}</span>
          <span>
            <Badge variant={call.outcome === "promise_made" ? "success" : call.outcome === "refused" ? "warning" : "default"}>
              {call.outcome?.replace(/_/g, " ") ?? call.status}
            </Badge>
          </span>
          <span className="text-xs text-slate-400">{analysis?.analysis_status === "completed" ? "✓ Analyzed" : analysis?.analysis_status === "processing" ? "Analyzing…" : expanded ? "Loading…" : ""}</span>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-slate-100 bg-slate-50 p-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* LEFT — transcript text (AI calls have text only, no speaker diarization) */}
            <div className="space-y-4">
              {analysis?.transcript_text && (
                <Card>
                  <div className="p-4">
                    <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-3">Transcript</h3>
                    <div className="space-y-2 max-h-72 overflow-y-auto pr-1 text-sm text-slate-600 whitespace-pre-wrap">
                      {analysis.transcript_text}
                    </div>
                  </div>
                </Card>
              )}
            </div>

            {/* RIGHT — Intelligence */}
            <div className="space-y-4">
              {isProcessing ? (
                <div className="flex items-center gap-3 px-4 py-3 bg-amber-50 border border-amber-200 rounded-xl text-amber-700 text-sm">
                  <Spinner className="w-4 h-4 flex-shrink-0" />
                  <span>{!analysis ? "Analysis starting…" : analysis.analysis_status === "pending" ? "Analysis queued…" : "Analyzing with GPT-4o…"}</span>
                </div>
              ) : analysis?.analysis_status === "failed" ? (
                <div className="flex items-center gap-3 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
                  <AlertTriangle size={14} className="flex-shrink-0" />
                  <span>Analysis failed{analysis.analysis_error ? `: ${analysis.analysis_error}` : ""}</span>
                </div>
              ) : (
                <div className="flex items-center gap-3 px-4 py-3 bg-green-50 border border-green-200 rounded-xl text-green-700 text-sm">
                  <CheckCircle size={14} className="flex-shrink-0" />
                  <span>Analysis complete{analysis?.analysis_completed_at ? ` · ${formatDate(analysis.analysis_completed_at)}` : ""}</span>
                </div>
              )}

              <Card>
                <div className="p-4 space-y-3">
                  <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Sentiment</h3>
                  <div className="flex items-center gap-4">
                    <div><p className="text-xs text-slate-400 mb-1">Overall</p>{sentimentBadge(analysis?.overall_sentiment)}</div>
                    <div><p className="text-xs text-slate-400 mb-1">Willingness to Pay</p>{willingnessBadge(analysis?.willingness_to_pay)}</div>
                  </div>
                  {analysis?.sentiment_score != null && (
                    <div>
                      <div className="flex justify-between text-xs text-slate-400 mb-1">
                        <span>Hostile</span><span>Score: {analysis.sentiment_score.toFixed(2)}</span><span>Cooperative</span>
                      </div>
                      <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${barPct}%` }} />
                      </div>
                    </div>
                  )}
                </div>
              </Card>

              <Card>
                <div className="p-4">
                  <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Repayment Probability</h3>
                  {repaymentPct != null ? (
                    <>
                      <p className={`text-4xl font-bold ${repaymentColor}`}>{repaymentPct}%</p>
                      {analysis?.repayment_probability_reason && (
                        <p className="text-xs text-slate-500 mt-2 leading-relaxed">{analysis.repayment_probability_reason}</p>
                      )}
                    </>
                  ) : (
                    <p className="text-slate-400 text-sm">Not yet computed</p>
                  )}
                </div>
              </Card>

              {analysis?.borrower_characterization && (
                <Card>
                  <div className="p-4">
                    <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Borrower Characterization</h3>
                    <p className="text-sm text-slate-600 italic leading-relaxed border-l-2 border-indigo-200 pl-3">{analysis.borrower_characterization}</p>
                  </div>
                </Card>
              )}

              {analysis?.key_points && analysis.key_points.length > 0 && (
                <Card>
                  <div className="p-4">
                    <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Key Points</h3>
                    <ul className="space-y-1.5">
                      {analysis.key_points.map((pt, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                          <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-indigo-400 flex-shrink-0" />{pt}
                        </li>
                      ))}
                    </ul>
                  </div>
                </Card>
              )}

              {analysis?.recommended_strategy && (
                <Card>
                  <div className="p-4">
                    <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Recommended Strategy</h3>
                    <Badge variant="info" className="text-sm px-3 py-1 mb-1.5">{analysis.recommended_strategy}</Badge>
                    {strategyDescription(analysis.recommended_strategy) && (
                      <p className="text-xs text-slate-500">{strategyDescription(analysis.recommended_strategy)}</p>
                    )}
                  </div>
                </Card>
              )}

              {analysis?.next_call_talking_points && analysis.next_call_talking_points.length > 0 && (
                <Card>
                  <div className="p-4">
                    <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Next Call Talking Points</h3>
                    <ol className="space-y-2">
                      {analysis.next_call_talking_points.map((pt, i) => (
                        <li key={i} className="flex items-start gap-2.5 text-sm text-slate-600">
                          <span className="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-600 text-white text-xs flex items-center justify-center font-semibold">{i + 1}</span>
                          {pt}
                        </li>
                      ))}
                    </ol>
                  </div>
                </Card>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ScoreBar({ label, value, color = "bg-indigo-500" }: { label: string; value?: number | null; color?: string }) {
  const pct = value != null ? Math.round(value * 100) : null;
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-600 mb-1">
        <span>{label}</span>
        <span className="font-medium">{pct != null ? `${pct}%` : "—"}</span>
      </div>
      <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct ?? 0}%` }} />
      </div>
    </div>
  );
}

export default function BorrowerDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [callModal, setCallModal] = useState(false);
  const [strategy, setStrategy] = useState<CallInitiate["strategy_override"]>(undefined);
  const [language, setLanguage] = useState<string>("en");
  const [optOutModal, setOptOutModal] = useState(false);

  const { data: borrower, isLoading } = useQuery({
    queryKey: ["borrower", id],
    queryFn: () => borrowersApi.get(id!),
    enabled: !!id,
  });

  const { data: calls } = useQuery({
    queryKey: ["calls", "borrower", id],
    queryFn: () => callsApi.list(),
    enabled: !!id,
    select: (data) => data.filter((c) => c.borrower_id === id).slice(0, 20),
  });

  const { data: events } = useQuery({
    queryKey: ["compliance", id],
    queryFn: () => borrowersApi.getComplianceEvents(id!),
    enabled: !!id,
  });

  const { data: pressureEvents } = useQuery({
    queryKey: ["pressure-events", id],
    queryFn: () => borrowersApi.getBehavioralEvents(id!, "pressure_escalation"),
    enabled: !!id,
  });

  const { data: humanCalls } = useQuery({
    queryKey: ["human-calls", "borrower", id],
    queryFn: () => humanCallsApi.listByBorrower(id!),
    enabled: !!id,
  });

  const initiateCall = useMutation({
    mutationFn: () =>
      callsApi.initiate({ borrower_id: id!, strategy_override: strategy, language }),
    onSuccess: () => {
      setCallModal(false);
      void qc.invalidateQueries({ queryKey: ["borrower", id] });
    },
  });

  const optOut = useMutation({
    mutationFn: () => borrowersApi.optOut(id!),
    onSuccess: () => {
      setOptOutModal(false);
      void qc.invalidateQueries({ queryKey: ["borrower", id] });
    },
  });

  if (isLoading) return <PageSpinner />;
  if (!borrower) return <div className="p-6 text-slate-500">Borrower not found</div>;

  return (
    <div className="p-6 space-y-5 max-w-5xl">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="text-slate-400 hover:text-slate-600">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <h1 className="text-xl font-bold text-slate-800">
            {borrower.first_name} {borrower.last_name}
          </h1>
          <p className="text-sm text-slate-500">{borrower.external_id}</p>
        </div>
        <div className="flex gap-2">
          {!borrower.opted_out && (
            <Button
              variant="primary"
              onClick={() => setCallModal(true)}
              disabled={borrower.do_not_call || borrower.bankruptcy_filed}
            >
              <Phone size={14} />
              Initiate Call
            </Button>
          )}
          {!borrower.opted_out && (
            <Button variant="danger" onClick={() => setOptOutModal(true)}>
              <ShieldOff size={14} />
              Opt Out
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Profile */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Profile</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
              {[
                ["Original Creditor", borrower.original_creditor ?? "—"],
                ["Debt Type", borrower.debt_type ?? "—"],
                ["Principal", formatCurrency(borrower.principal_amount)],
                ["Current Balance", formatCurrency(borrower.current_balance)],
                ["Days Past Due", `${borrower.days_past_due}d`],
                ["Timezone", borrower.time_zone],
                ["Total Calls", (borrower.total_calls ?? 0).toString()],
                ["Contacts", (borrower.successful_contacts ?? 0).toString()],
                ["Created", formatDate(borrower.created_at)],
                ["Updated", formatDate(borrower.updated_at)],
              ].map(([k, v]) => (
                <div key={k}>
                  <span className="text-slate-500">{k}: </span>
                  <span className="font-medium text-slate-800">{v}</span>
                </div>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {borrower.opted_out && <Badge variant="danger">Opted Out</Badge>}
              {borrower.do_not_call && <Badge variant="warning">DNC</Badge>}
              {borrower.bankruptcy_filed && <Badge variant="danger">Bankruptcy</Badge>}
              {borrower.consent_recorded ? (
                <Badge variant="success"><CheckCircle size={10} className="mr-1" />TCPA Consent</Badge>
              ) : (
                <Badge variant="warning">No TCPA Consent</Badge>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Behavioral Scores */}
        <Card>
          <CardHeader>
            <CardTitle>Behavioral Scores</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <ScoreBar label="Engagement" value={borrower.engagement_score} color="bg-indigo-500" />
            <ScoreBar label="Avoidance" value={borrower.avoidance_score} color="bg-red-400" />
            <ScoreBar label="Repayment Likelihood" value={borrower.repayment_likelihood} color="bg-green-500" />
            <ScoreBar label="Promise Kept Rate" value={borrower.promise_kept_rate} color="bg-amber-400" />
          </CardContent>
        </Card>
      </div>

      {/* Call History */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Calls</CardTitle>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-100">
              <tr>
                {["Date", "Duration", "Outcome", "Turns", "Sentiment Δ", "Compliance"].map((h) => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(!calls || calls.length === 0) && (
                <tr><td colSpan={6} className="text-center py-8 text-slate-400">No calls yet</td></tr>
              )}
              {(calls ?? []).map((c) => (
                <tr key={c.id} className="border-b border-slate-50 hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link to={`/calls/${c.id}`} className="text-indigo-600 hover:underline">
                      {formatDate(c.created_at)}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{formatDuration(c.duration_seconds)}</td>
                  <td className="px-4 py-3">
                    <Badge variant={c.outcome === "promise_made" ? "success" : c.outcome === "refused" ? "warning" : "default"}>
                      {c.outcome?.replace(/_/g, " ") ?? c.status}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">{c.turn_count}</td>
                  <td className="px-4 py-3 font-mono text-xs">
                    {c.sentiment_trajectory.length >= 2
                      ? ((c.sentiment_trajectory.at(-1)?.score ?? 0) - (c.sentiment_trajectory[0]?.score ?? 0)).toFixed(2)
                      : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={c.compliance_passed ? "success" : "danger"}>
                      {c.compliance_passed ? "Pass" : "Fail"}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* AI Call Intelligence */}
      {calls && calls.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BrainCircuit size={16} className="text-indigo-600" />
              AI Call Intelligence
            </CardTitle>
          </CardHeader>
          <div className="p-4 space-y-1">
            <div className="grid grid-cols-4 gap-3 px-4 pb-2 text-xs font-semibold text-slate-400 uppercase tracking-wide">
              <span>Date</span>
              <span>Duration</span>
              <span>Outcome</span>
              <span>Analysis</span>
            </div>
            {calls.map((c) => (
              <AICallIntelligenceItem key={c.id} call={c} />
            ))}
          </div>
        </Card>
      )}

      {/* Aggression Level Timeline */}
      {Array.isArray(pressureEvents) && pressureEvents.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp size={16} className="text-orange-500" />
              Aggression Level History
            </CardTitle>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-100">
                <tr>
                  {["Time", "Call", "Level Reached", "Trigger Phrase"].map((h) => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pressureEvents.map((e) => {
                  const level = e.event_data.level as number;
                  const levelColors = ["", "bg-yellow-100 text-yellow-800", "bg-orange-100 text-orange-800", "bg-red-100 text-red-800", "bg-red-200 text-red-900"];
                  const levelLabels = ["", "Level 1 — Firm", "Level 2 — Aggressive", "Level 3 — Final Warning", "Level 4 — Last Resort"];
                  return (
                    <tr key={e.id} className="border-b border-slate-50">
                      <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">{formatDate(e.detected_at)}</td>
                      <td className="px-4 py-3 text-xs font-mono text-slate-500">
                        {e.call_id ? (
                          <Link to={`/calls/${e.call_id}`} className="text-indigo-600 hover:underline">
                            {e.call_id.slice(0, 8)}…
                          </Link>
                        ) : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${levelColors[level] ?? levelColors[4]}`}>
                          {levelLabels[level] ?? `Level ${level}`}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-600 text-xs italic max-w-xs truncate">
                        "{e.event_data.trigger as string}"
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Compliance Events */}
      {Array.isArray(events) && events.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Compliance Events</CardTitle>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-100">
                <tr>
                  {["Time", "Type", "Severity", "Description"].map((h) => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {events.map((e: { id: string; created_at: string; event_type: string; severity: string; description?: string }) => (
                  <tr key={e.id} className="border-b border-slate-50">
                    <td className="px-4 py-3 text-slate-500 text-xs">{formatDate(e.created_at)}</td>
                    <td className="px-4 py-3 font-mono text-xs">{e.event_type}</td>
                    <td className="px-4 py-3"><Badge variant={severityVariant(e.severity)}>{e.severity}</Badge></td>
                    <td className="px-4 py-3 text-slate-600">{e.description ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Human Call Intelligence */}
      {Array.isArray(humanCalls) && humanCalls.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BrainCircuit size={16} className="text-indigo-600" />
              Human Call Intelligence
            </CardTitle>
          </CardHeader>
          <div className="p-4 space-y-1">
            {/* Column headers */}
            <div className="grid grid-cols-4 gap-3 px-4 pb-2 text-xs font-semibold text-slate-400 uppercase tracking-wide">
              <span>Date</span>
              <span>Agent</span>
              <span>Duration</span>
              <span>Status</span>
            </div>
            {humanCalls.map((hc) => (
              <HumanCallIntelligenceItem key={hc.id} call={hc} />
            ))}
          </div>
        </Card>
      )}

      {/* Initiate Call Modal */}
      <Modal open={callModal} onClose={() => setCallModal(false)} title="Initiate Call">
        <div className="space-y-4">
          <Select label="Strategy Override" value={strategy ?? ""} onChange={(e) => setStrategy((e.target.value as CallInitiate["strategy_override"]) || undefined)}>
            <option value="">Auto (ML-selected)</option>
            <option value="reminder">Reminder</option>
            <option value="negotiation">Negotiation</option>
            <option value="settlement">Settlement</option>
            <option value="escalation">Escalation</option>
          </Select>
          <Select label="Language" value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="en">English</option>
            <option value="hi">Hindi (हिन्दी)</option>
            <option value="kn">Kannada (ಕನ್ನಡ)</option>
            <option value="te">Telugu (తెలుగు)</option>
          </Select>
          {initiateCall.error && <p className="text-sm text-red-600">{initiateCall.error.message}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCallModal(false)}>Cancel</Button>
            <Button variant="primary" loading={initiateCall.isPending} onClick={() => initiateCall.mutate()}>
              <Phone size={14} />
              Call Now
            </Button>
          </div>
        </div>
      </Modal>

      {/* Opt-Out Confirm Modal */}
      <Modal open={optOutModal} onClose={() => setOptOutModal(false)} title="Confirm Opt-Out">
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            This will mark the borrower as opted-out, add them to the DNC list, and cancel all pending scheduled calls. This action cannot be undone.
          </p>
          {optOut.error && <p className="text-sm text-red-600">{optOut.error.message}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOptOutModal(false)}>Cancel</Button>
            <Button variant="danger" loading={optOut.isPending} onClick={() => optOut.mutate()}>
              Confirm Opt-Out
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
