import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { callsApi } from "@/api/calls";
import { borrowersApi } from "@/api/borrowers";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card";
import { Badge, outcomeVariant } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Input";
import { PageSpinner } from "@/components/ui/Spinner";
import { cn, formatDate, formatDuration, formatCurrency } from "@/lib/utils";
import { ArrowLeft, BrainCircuit, Phone, Shield, ShieldAlert, Zap } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";

export default function CallDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [followUpModal, setFollowUpModal] = useState(false);
  const [language, setLanguage] = useState("en");

  const { data: call, isLoading: loadingCall } = useQuery({
    queryKey: ["call", id],
    queryFn: () => callsApi.get(id!),
    enabled: !!id,
  });

  const { data: borrower } = useQuery({
    queryKey: ["borrower-for-call", call?.borrower_id],
    queryFn: () => borrowersApi.get(call!.borrower_id),
    enabled: !!call?.borrower_id,
  });

  const { data: transcript, isLoading: loadingTranscript } = useQuery({
    queryKey: ["transcript", id],
    queryFn: () => callsApi.getTranscript(id!),
    enabled: !!id,
  });

  const {
    data: followUpBrief,
    isLoading: loadingFollowUpBrief,
    isError: followUpBriefError,
  } = useQuery({
    queryKey: ["follow-up-brief", id],
    queryFn: () => callsApi.getFollowUpBrief(id!),
    enabled: !!id,
    retry: false,
  });

  const followUpCall = useMutation({
    mutationFn: () => callsApi.initiate({
      borrower_id: call!.borrower_id,
      language,
      follow_up_enabled: true,
      follow_up_source_call_id: id,
    }),
    onSuccess: () => {
      setFollowUpModal(false);
      navigate(`/borrowers/${call!.borrower_id}`);
    },
  });

  if (loadingCall) return <PageSpinner />;
  if (!call) return <div className="p-6 text-slate-500">Call not found</div>;

  const sentimentData = call.sentiment_trajectory.map((p) => ({
    turn: p.turn,
    score: Number(p.score.toFixed(3)),
  }));

  return (
    <div className="p-6 space-y-5 max-w-5xl">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="text-slate-400 hover:text-slate-600">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <h1 className="text-xl font-bold text-slate-800">Call Detail</h1>
          <p className="text-xs text-slate-400 font-mono">{call.twilio_call_sid ?? call.id}</p>
        </div>
        {followUpBrief && (
          <Button variant="primary" onClick={() => setFollowUpModal(true)}>
            <Phone size={14} />
            Follow-up Call
          </Button>
        )}
        <Badge variant={outcomeVariant(call.outcome)}>
          {call.outcome?.replace(/_/g, " ") ?? call.status}
        </Badge>
        {call.compliance_passed ? (
          <Badge variant="success"><Shield size={10} className="mr-1" />Compliant</Badge>
        ) : (
          <Badge variant="danger"><ShieldAlert size={10} className="mr-1" />Violation</Badge>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BrainCircuit size={16} className="text-indigo-600" />
            Follow-up AI Brief
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {loadingFollowUpBrief && (
            <p className="text-sm text-slate-400">Preparing follow-up guidance from the previous call...</p>
          )}
          {!loadingFollowUpBrief && followUpBriefError && (
            <p className="text-sm text-slate-400">
              Follow-up guidance is not ready for this call yet. Once the previous call analysis is available, this page will prepare the next automated follow-up.
            </p>
          )}
          {followUpBrief && (
            <>
              <div className="rounded-2xl border border-indigo-100 bg-indigo-50/60 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-indigo-500">AI Summary</p>
                <p className="mt-2 text-sm text-slate-700">{followUpBrief.summary}</p>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Key Points From Last Call</p>
                  <div className="space-y-2">
                    {followUpBrief.key_points.map((point, index) => (
                      <div key={index} className="rounded-xl border border-slate-100 bg-white px-3 py-2 text-sm text-slate-700">
                        {point}
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">What To Focus On Next</p>
                  <div className="space-y-2">
                    {followUpBrief.next_call_focus.map((point, index) => (
                      <div key={index} className="rounded-xl border border-emerald-100 bg-emerald-50/70 px-3 py-2 text-sm text-slate-700">
                        {point}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <div className="rounded-2xl border border-amber-100 bg-amber-50/70 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Suggested Personalized Opener</p>
                <p className="mt-2 text-sm text-slate-700">{followUpBrief.suggested_opening}</p>
              </div>
              <div className="flex flex-col gap-3 rounded-2xl border border-slate-100 bg-slate-50 p-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="text-sm font-medium text-slate-700">Start the next call with memory from this one.</p>
                  <p className="text-xs text-slate-500 mt-1">
                    The AI will automatically use these points when you launch a follow-up call.
                  </p>
                </div>
                <Button variant="primary" onClick={() => setFollowUpModal(true)}>
                  <Phone size={14} />
                  Follow-up Call
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Duration", value: formatDuration(call.duration_seconds) },
          { label: "Turns", value: call.turn_count.toString() },
          { label: "Interruptions", value: call.interruption_count.toString() },
          { label: "Started", value: formatDate(call.started_at) },
        ].map(({ label, value }) => (
          <Card key={label}>
            <CardContent className="py-3">
              <div className="text-xs text-slate-500">{label}</div>
              <div className="text-sm font-semibold text-slate-800 mt-0.5">{value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Sentiment Timeline</CardTitle>
          </CardHeader>
          <CardContent>
            {sentimentData.length < 2 ? (
              <p className="text-sm text-slate-400 py-8 text-center">Not enough turns for chart</p>
            ) : (
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={sentimentData}>
                  <XAxis dataKey="turn" tick={{ fontSize: 11 }} label={{ value: "Turn", position: "insideBottom", offset: -2, fontSize: 11 }} />
                  <YAxis domain={[-1, 1]} tick={{ fontSize: 11 }} />
                  <ReferenceLine y={0} stroke="#e2e8f0" strokeDasharray="4 4" />
                  <Tooltip formatter={(v) => [(v as number).toFixed(3), "Sentiment"]} labelFormatter={(t) => `Turn ${t}`} />
                  <Line
                    type="monotone"
                    dataKey="score"
                    stroke="#6366f1"
                    strokeWidth={2}
                    dot={{ r: 3, fill: "#6366f1" }}
                    activeDot={{ r: 5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Latency (avg ms)</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {[
                { label: "STT", value: call.stt_latency_avg_ms },
                { label: "LLM", value: call.llm_latency_avg_ms },
                { label: "TTS", value: call.tts_latency_avg_ms },
              ].map(({ label, value }) => (
                <div key={label} className="flex justify-between text-sm">
                  <span className="text-slate-500">{label}</span>
                  <span className="font-medium text-slate-800">{value != null ? `${value}ms` : "-"}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          {call.promise && (
            <Card>
              <CardHeader><CardTitle>Promise</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-500">Amount</span>
                  <span className="font-medium">{formatCurrency(call.promise.amount)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Date</span>
                  <span className="font-medium">{call.promise.date ?? "-"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Status</span>
                  <Badge variant={call.promise.status === "kept" ? "success" : call.promise.status === "broken" ? "danger" : "default"}>
                    {call.promise.status ?? "pending"}
                  </Badge>
                </div>
              </CardContent>
            </Card>
          )}

          {call.fdcpa_violations.length > 0 && (
            <Card>
              <CardHeader><CardTitle className="text-red-600">FDCPA Violations</CardTitle></CardHeader>
              <CardContent>
                <ul className="text-sm text-red-600 space-y-1">
                  {call.fdcpa_violations.map((v, i) => (
                    <li key={i} className="flex items-start gap-1.5">
                      <ShieldAlert size={12} className="mt-0.5 shrink-0" />
                      {v}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Transcript</CardTitle>
        </CardHeader>
        <CardContent>
          {loadingTranscript && <PageSpinner />}
          {transcript && transcript.turns.length === 0 && (
            <p className="text-sm text-slate-400 py-4 text-center">No transcript available</p>
          )}
          <div className="space-y-3">
            {(transcript?.turns ?? []).map((turn) => (
              <div
                key={turn.turn_index}
                className={cn("flex gap-3", turn.speaker === "agent" ? "justify-start" : "justify-end")}
              >
                <div
                  className={cn(
                    "max-w-[70%] rounded-xl px-4 py-3 text-sm",
                    turn.speaker === "agent"
                      ? "bg-indigo-50 text-slate-800 rounded-tl-none"
                      : "bg-slate-100 text-slate-800 rounded-tr-none"
                  )}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      {turn.speaker}
                    </span>
                    {turn.barge_in && (
                      <span className="flex items-center gap-0.5 text-xs text-amber-600">
                        <Zap size={10} />barge-in
                      </span>
                    )}
                    {turn.timestamp_ms != null && (
                      <span className="text-xs text-slate-400 ml-auto">
                        {(turn.timestamp_ms / 1000).toFixed(1)}s
                      </span>
                    )}
                  </div>
                  <p>{turn.text ?? <span className="italic text-slate-400">[no transcript]</span>}</p>
                  <div className="flex flex-wrap gap-2 mt-2">
                    {turn.intent && (
                      <span className="text-xs bg-white/60 border border-slate-200 rounded px-1.5 py-0.5 text-slate-500">
                        {turn.intent}
                      </span>
                    )}
                    {turn.sentiment != null && (
                      <span className={cn(
                        "text-xs rounded px-1.5 py-0.5",
                        turn.sentiment > 0.2 ? "bg-green-100 text-green-700" :
                        turn.sentiment < -0.2 ? "bg-red-100 text-red-700" :
                        "bg-slate-100 text-slate-500"
                      )}>
                        {turn.sentiment > 0 ? "+" : ""}{turn.sentiment.toFixed(2)}
                      </span>
                    )}
                    {(turn.entities?.amounts as unknown[])?.length > 0 && (
                      <span className="text-xs bg-emerald-50 text-emerald-700 border border-emerald-100 rounded px-1.5 py-0.5">
                        amounts: {(turn.entities.amounts as string[]).join(", ")}
                      </span>
                    )}
                    {(turn.entities?.dates as unknown[])?.length > 0 && (
                      <span className="text-xs bg-blue-50 text-blue-700 border border-blue-100 rounded px-1.5 py-0.5">
                        dates: {(turn.entities.dates as string[]).join(", ")}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <p className="text-xs text-slate-400">
        Borrower: <Link to={`/borrowers/${call.borrower_id}`} className="text-indigo-500 hover:underline">{call.borrower_id}</Link>
        {call.campaign_id && <> . Campaign: <Link to={`/campaigns/${call.campaign_id}`} className="text-indigo-500 hover:underline">{call.campaign_id}</Link></>}
      </p>

      <Modal open={followUpModal} onClose={() => setFollowUpModal(false)} title="Launch Follow-up Call">
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            This starts a new automated call that remembers the previous conversation and pushes the next payment step automatically.
          </p>
          {followUpBrief && (
            <div className="rounded-xl border border-slate-100 bg-slate-50 p-3 text-sm text-slate-700 space-y-2">
              <p><span className="font-semibold">Borrower:</span> {borrower?.first_name ?? "Borrower"}</p>
              <p><span className="font-semibold">Source call:</span> {formatDate(followUpBrief.source_call_created_at)}</p>
              <p><span className="font-semibold">Opening:</span> {followUpBrief.suggested_opening}</p>
            </div>
          )}
          <Select label="Language" value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="en">English</option>
            <option value="hi">Hindi</option>
            <option value="kn">Kannada</option>
            <option value="te">Telugu</option>
          </Select>
          {followUpCall.error && <p className="text-sm text-red-600">{followUpCall.error.message}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setFollowUpModal(false)}>Cancel</Button>
            <Button
              variant="primary"
              loading={followUpCall.isPending}
              disabled={!followUpBrief}
              onClick={() => followUpCall.mutate()}
            >
              <Phone size={14} />
              Start Follow-up Call
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
