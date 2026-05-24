import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { humanCallsApi } from "@/api/human_calls";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PageSpinner, Spinner } from "@/components/ui/Spinner";
import { formatDate, formatDuration } from "@/lib/utils";
import {
  ArrowLeft,
  BrainCircuit,
  User,
  Bot,
  AlertTriangle,
  CheckCircle,
  Clock,
} from "lucide-react";

function sentimentBadge(sentiment?: string) {
  if (!sentiment) return <span className="text-slate-400">—</span>;
  const map: Record<string, "danger" | "warning" | "default" | "info" | "success"> = {
    hostile: "danger",
    negative: "warning",
    neutral: "default",
    positive: "info",
    cooperative: "success",
  };
  return <Badge variant={map[sentiment] ?? "default"}>{sentiment}</Badge>;
}

function willingnessBadge(w?: string) {
  if (!w) return <span className="text-slate-400">—</span>;
  const map: Record<string, "danger" | "warning" | "muted" | "success"> = {
    refused: "danger",
    low: "warning",
    medium: "muted",
    high: "success",
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

export default function HumanCallDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data: call, isLoading: callLoading } = useQuery({
    queryKey: ["human-call", id],
    queryFn: () => humanCallsApi.get(id!),
    enabled: !!id,
  });

  const { data: analysis, isLoading: analysisLoading } = useQuery({
    queryKey: ["human-analysis", id],
    queryFn: () => humanCallsApi.getAnalysis(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.analysis_status;
      return status === "pending" || status === "processing" ? 5000 : false;
    },
  });

  if (callLoading || analysisLoading) return <PageSpinner />;
  if (!call) return (
    <div className="p-6 text-slate-500">Call not found.</div>
  );

  const repaymentPct = analysis?.repayment_probability != null
    ? Math.round(analysis.repayment_probability * 100)
    : null;

  const repaymentColor =
    repaymentPct == null ? "text-slate-400"
    : repaymentPct >= 60 ? "text-green-600"
    : repaymentPct >= 30 ? "text-amber-600"
    : "text-red-600";

  const sentimentScore = analysis?.sentiment_score ?? 0;
  // Map -1..1 to 0..100 for the bar
  const barPct = Math.round(((sentimentScore + 1) / 2) * 100);
  const barColor =
    sentimentScore >= 0.3 ? "bg-green-500"
    : sentimentScore >= -0.2 ? "bg-amber-500"
    : "bg-red-500";

  const isProcessing =
    !analysis ||
    analysis.analysis_status === "pending" ||
    analysis.analysis_status === "processing";

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" onClick={() => navigate("/human-calls")}>
          <ArrowLeft size={16} />
          Back
        </Button>
        <div className="flex items-center gap-2">
          <div className="p-2 bg-indigo-50 rounded-lg">
            <BrainCircuit size={18} className="text-indigo-600" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-slate-800">Human Call Intelligence</h1>
            <p className="text-xs text-slate-500">{formatDate(call.created_at)}</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* LEFT PANEL — Call info + transcript */}
        <div className="space-y-4">
          {/* Call metadata */}
          <Card>
            <div className="p-4 space-y-3">
              <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">Call Info</h2>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">Contact</p>
                  <p className="font-medium text-slate-700">{call.contact_name ?? "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">Phone</p>
                  <p className="font-medium text-slate-700">{call.contact_phone ?? "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">Agent</p>
                  <p className="font-medium text-slate-700">{call.human_agent_name ?? "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">Duration</p>
                  <p className="font-medium text-slate-700">{formatDuration(call.duration_seconds)}</p>
                </div>
                {call.amount_due != null && (
                  <div>
                    <p className="text-xs text-slate-400 mb-0.5">Amount Due</p>
                    <p className="font-medium text-slate-700">₹{Number(call.amount_due).toLocaleString()}</p>
                  </div>
                )}
                {call.days_overdue != null && (
                  <div>
                    <p className="text-xs text-slate-400 mb-0.5">Days Overdue</p>
                    <p className="font-medium text-slate-700">{call.days_overdue} days</p>
                  </div>
                )}
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">Status</p>
                  <p className="font-medium text-slate-700 capitalize">{call.status}</p>
                </div>
              </div>
            </div>
          </Card>

          {/* Transcript */}
          <Card>
            <div className="p-4">
              <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">Transcript</h2>
              {!analysis || analysis.transcription_status === "pending" ? (
                <div className="flex items-center gap-2 text-slate-400 text-sm py-8 justify-center">
                  <Clock size={16} />
                  Transcription pending…
                </div>
              ) : analysis.transcription_status === "processing" ? (
                <div className="flex items-center gap-2 text-blue-600 text-sm py-8 justify-center">
                  <Spinner className="w-4 h-4" />
                  Transcribing call recording…
                </div>
              ) : analysis.transcription_status === "failed" ? (
                <div className="flex items-center gap-2 text-red-500 text-sm py-8 justify-center">
                  <AlertTriangle size={16} />
                  Transcription failed
                </div>
              ) : analysis.transcript_speakers && analysis.transcript_speakers.length > 0 ? (
                <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
                  {analysis.transcript_speakers.map((turn, i) => {
                    const isAgent = turn.speaker === 0;
                    return (
                      <div
                        key={i}
                        className={`flex gap-2 ${isAgent ? "" : "flex-row-reverse"}`}
                      >
                        <div className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center mt-0.5 ${isAgent ? "bg-indigo-100" : "bg-slate-100"}`}>
                          {isAgent
                            ? <Bot size={12} className="text-indigo-600" />
                            : <User size={12} className="text-slate-500" />
                          }
                        </div>
                        <div className={`max-w-[80%] ${isAgent ? "" : "text-right"}`}>
                          <p className={`text-xs font-semibold mb-0.5 ${isAgent ? "text-indigo-600" : "text-slate-500"}`}>
                            {isAgent ? "Agent" : "Borrower"}
                            <span className="ml-1 font-normal text-slate-400">
                              {msToTimestamp(turn.start_ms)}
                            </span>
                          </p>
                          <p className={`text-sm px-3 py-2 rounded-lg ${isAgent ? "bg-indigo-50 text-indigo-900" : "bg-slate-100 text-slate-700"}`}>
                            {turn.text}
                          </p>
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

        {/* RIGHT PANEL — Intelligence report */}
        <div className="space-y-4">
          {/* Status banner */}
          {isProcessing ? (
            <div className="flex items-center gap-3 px-4 py-3 bg-amber-50 border border-amber-200 rounded-xl text-amber-700 text-sm">
              <Spinner className="w-4 h-4 flex-shrink-0" />
              <span>
                {!analysis ? "Waiting for analysis to start…"
                  : analysis.analysis_status === "pending" ? "Analysis queued — will begin after transcription…"
                  : "Analyzing call with GPT-4o — refreshing every 5s…"}
              </span>
            </div>
          ) : analysis?.analysis_status === "failed" ? (
            <div className="flex items-center gap-3 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
              <AlertTriangle size={16} className="flex-shrink-0" />
              <span>Analysis failed{analysis.analysis_error ? `: ${analysis.analysis_error}` : ""}</span>
            </div>
          ) : (
            <div className="flex items-center gap-3 px-4 py-3 bg-green-50 border border-green-200 rounded-xl text-green-700 text-sm">
              <CheckCircle size={16} className="flex-shrink-0" />
              <span>
                Analysis complete
                {analysis?.analysis_completed_at ? ` · ${formatDate(analysis.analysis_completed_at)}` : ""}
              </span>
            </div>
          )}

          {/* Sentiment + Willingness */}
          <Card>
            <div className="p-4 space-y-3">
              <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">Sentiment</h2>
              <div className="flex items-center gap-4">
                <div>
                  <p className="text-xs text-slate-400 mb-1">Overall</p>
                  {sentimentBadge(analysis?.overall_sentiment)}
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-1">Willingness to Pay</p>
                  {willingnessBadge(analysis?.willingness_to_pay)}
                </div>
              </div>
              {analysis?.sentiment_score != null && (
                <div>
                  <div className="flex justify-between text-xs text-slate-400 mb-1">
                    <span>Hostile</span>
                    <span>Score: {analysis.sentiment_score.toFixed(2)}</span>
                    <span>Cooperative</span>
                  </div>
                  <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${barColor}`}
                      style={{ width: `${barPct}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
          </Card>

          {/* Repayment Probability */}
          <Card>
            <div className="p-4">
              <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-2">Repayment Probability</h2>
              {repaymentPct != null ? (
                <>
                  <p className={`text-5xl font-bold ${repaymentColor}`}>{repaymentPct}%</p>
                  {analysis?.repayment_probability_reason && (
                    <p className="text-xs text-slate-500 mt-2 leading-relaxed">
                      {analysis.repayment_probability_reason}
                    </p>
                  )}
                </>
              ) : (
                <p className="text-slate-400 text-sm">Not yet computed</p>
              )}
            </div>
          </Card>

          {/* Borrower Characterization */}
          {analysis?.borrower_characterization && (
            <Card>
              <div className="p-4">
                <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-2">Borrower Characterization</h2>
                <p className="text-sm text-slate-600 italic leading-relaxed border-l-2 border-indigo-200 pl-3">
                  {analysis.borrower_characterization}
                </p>
              </div>
            </Card>
          )}

          {/* Key Points */}
          {analysis?.key_points && analysis.key_points.length > 0 && (
            <Card>
              <div className="p-4">
                <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-2">Key Points</h2>
                <ul className="space-y-1.5">
                  {analysis.key_points.map((pt, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                      <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-indigo-400 flex-shrink-0" />
                      {pt}
                    </li>
                  ))}
                </ul>
              </div>
            </Card>
          )}

          {/* Recommended Strategy */}
          {analysis?.recommended_strategy && (
            <Card>
              <div className="p-4">
                <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-2">Recommended Strategy</h2>
                <div className="flex items-center gap-2 mb-1.5">
                  <Badge variant="info" className="text-sm px-3 py-1">{analysis.recommended_strategy}</Badge>
                </div>
                {strategyDescription(analysis.recommended_strategy) && (
                  <p className="text-xs text-slate-500">{strategyDescription(analysis.recommended_strategy)}</p>
                )}
              </div>
            </Card>
          )}

          {/* Next Call Talking Points */}
          {analysis?.next_call_talking_points && analysis.next_call_talking_points.length > 0 && (
            <Card>
              <div className="p-4">
                <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-2">Next Call Talking Points</h2>
                <ol className="space-y-2">
                  {analysis.next_call_talking_points.map((pt, i) => (
                    <li key={i} className="flex items-start gap-2.5 text-sm text-slate-600">
                      <span className="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-600 text-white text-xs flex items-center justify-center font-semibold">
                        {i + 1}
                      </span>
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
  );
}
