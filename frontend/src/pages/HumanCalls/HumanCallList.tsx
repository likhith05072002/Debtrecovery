import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Device, Call } from "@twilio/voice-sdk";
import { humanCallsApi } from "@/api/human_calls";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Modal } from "@/components/ui/Modal";
import { PageSpinner, Spinner } from "@/components/ui/Spinner";
import { formatDate, formatDuration } from "@/lib/utils";
import { BrainCircuit, Phone, PhoneOff, UserCheck, Mic, MicOff } from "lucide-react";

// ── Call state machine ────────────────────────────────────────────────────────
type CallPhase =
  | "idle"        // modal not open
  | "form"        // entering contact info
  | "connecting"  // creating DB record + initialising Device
  | "ringing"     // device.connect() called, waiting for pickup
  | "active"      // contact answered
  | "ended";      // call finished

function analysisStatusBadge(status?: string) {
  if (!status || status === "pending")
    return <Badge variant="muted">Pending</Badge>;
  if (status === "processing")
    return (
      <span className="inline-flex items-center gap-1 text-xs text-blue-600">
        <Spinner className="w-3 h-3" /> Processing
      </span>
    );
  if (status === "completed")
    return <Badge variant="success">Complete</Badge>;
  return <Badge variant="danger">Failed</Badge>;
}

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

export default function HumanCallList() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  // ── Form state ──────────────────────────────────────────────────────────────
  const [contactName, setContactName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [amountDue, setAmountDue] = useState("");
  const [daysOverdue, setDaysOverdue] = useState("");
  const [agentName, setAgentName] = useState("");

  // ── Call phase ──────────────────────────────────────────────────────────────
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [callError, setCallError] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const [callDuration, setCallDuration] = useState(0);
  const [currentCallId, setCurrentCallId] = useState<string | null>(null);

  // ── Twilio refs ──────────────────────────────────────────────────────────────
  const deviceRef = useRef<Device | null>(null);
  const activeCallRef = useRef<Call | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Data queries ─────────────────────────────────────────────────────────────
  const { data: humanCalls, isLoading: callsLoading } = useQuery({
    queryKey: ["human-calls"],
    queryFn: () => humanCallsApi.list({ limit: 200 }),
  });

  const callIds = (humanCalls ?? []).map((c) => c.id);
  const { data: analysesMap } = useQuery({
    queryKey: ["human-analyses", callIds.join(",")],
    queryFn: async () => {
      const results: Record<string, Awaited<ReturnType<typeof humanCallsApi.getAnalysis>>> = {};
      await Promise.all(
        callIds.map(async (id) => {
          try { results[id] = await humanCallsApi.getAnalysis(id); } catch { /* not ready */ }
        })
      );
      return results;
    },
    enabled: callIds.length > 0,
    refetchInterval: 10_000,
  });

  // ── Cleanup on unmount ───────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      timerRef.current && clearInterval(timerRef.current);
      activeCallRef.current?.disconnect();
      deviceRef.current?.destroy();
    };
  }, []);

  // ── Timer helpers ────────────────────────────────────────────────────────────
  const startTimer = () => {
    setCallDuration(0);
    timerRef.current = setInterval(() => setCallDuration((d) => d + 1), 1000);
  };
  const stopTimer = () => {
    timerRef.current && clearInterval(timerRef.current);
    timerRef.current = null;
  };
  const formatTimer = (s: number) => {
    const m = Math.floor(s / 60).toString().padStart(2, "0");
    const sec = (s % 60).toString().padStart(2, "0");
    return `${m}:${sec}`;
  };

  // ── Main call action ─────────────────────────────────────────────────────────
  const handleCallNow = async () => {
    setCallError(null);
    setPhase("connecting");

    try {
      // 1. Create HumanCall DB record
      const initiated = await humanCallsApi.initiate({
        contact_name: contactName,
        contact_phone: contactPhone,
        agent_name: agentName || undefined,
        amount_due: amountDue ? parseFloat(amountDue) : undefined,
        days_overdue: daysOverdue ? parseInt(daysOverdue, 10) : undefined,
      });
      setCurrentCallId(initiated.call_id);

      // 2. Get Twilio Access Token
      const { token } = await humanCallsApi.getToken(agentName || "agent");

      // 3. Initialise Twilio Device
      const device = new Device(token, { logLevel: "warn" });
      deviceRef.current = device;
      await device.register();

      // 4. Connect (browser → Twilio TwiML App → contact phone)
      setPhase("ringing");
      const call = await device.connect({
        params: { humanCallId: initiated.call_id },
      });
      activeCallRef.current = call;

      call.on("accept", () => {
        setPhase("active");
        startTimer();
        void qc.invalidateQueries({ queryKey: ["human-calls"] });
      });

      call.on("disconnect", () => {
        setPhase("ended");
        stopTimer();
        activeCallRef.current = null;
        void qc.invalidateQueries({ queryKey: ["human-calls"] });
      });

      call.on("error", (err: Error) => {
        setCallError(err.message);
        setPhase("ended");
        stopTimer();
      });

    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Call failed";
      setCallError(msg);
      setPhase("form");
    }
  };

  const handleHangUp = () => {
    activeCallRef.current?.disconnect();
    deviceRef.current?.destroy();
    deviceRef.current = null;
    activeCallRef.current = null;
    stopTimer();
    setPhase("ended");
    void qc.invalidateQueries({ queryKey: ["human-calls"] });
  };

  const toggleMute = () => {
    if (!activeCallRef.current) return;
    const next = !muted;
    activeCallRef.current.mute(next);
    setMuted(next);
  };

  const closeModal = () => {
    if (phase === "active") return;
    handleHangUp();
    setPhase("idle");
    setContactName("");
    setContactPhone("");
    setAmountDue("");
    setDaysOverdue("");
    setAgentName("");
    setCallError(null);
    setCurrentCallId(null);
  };

  const openModal = () => {
    setPhase("form");
    setCallError(null);
  };

  const canCall = contactName.trim().length > 0 && contactPhone.trim().length > 0;

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-50 rounded-lg">
            <BrainCircuit size={20} className="text-indigo-600" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-800">Human Calls</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              {(humanCalls ?? []).length} recorded call{(humanCalls ?? []).length !== 1 ? "s" : ""} · AI intelligence auto-generated after each call
            </p>
          </div>
        </div>
        <Button variant="primary" onClick={openModal}>
          <Phone size={14} />
          Make a Call
        </Button>
      </div>

      {/* Calls table */}
      <Card>
        {callsLoading ? (
          <PageSpinner />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-100">
                <tr>
                  {["Date", "Contact", "Phone", "Amount Due", "Days Overdue", "Duration", "Analysis", "Sentiment", "Repayment %", "Strategy"].map((h) => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(humanCalls ?? []).length === 0 && (
                  <tr>
                    <td colSpan={10} className="text-center py-16 text-slate-400">
                      <div className="flex flex-col items-center gap-2">
                        <UserCheck size={32} className="text-slate-300" />
                        <p>No calls yet — click "Make a Call" to start</p>
                      </div>
                    </td>
                  </tr>
                )}
                {(humanCalls ?? []).map((call) => {
                  const analysis = analysesMap?.[call.id];
                  const repaymentPct = analysis?.repayment_probability != null
                    ? Math.round(analysis.repayment_probability * 100) : null;
                  return (
                    <tr
                      key={call.id}
                      className="border-b border-slate-50 hover:bg-slate-50 cursor-pointer transition-colors"
                      onClick={() => navigate(`/human-calls/${call.id}`)}
                    >
                      <td className="px-4 py-3 text-slate-600 text-xs">{formatDate(call.created_at)}</td>
                      <td className="px-4 py-3 font-medium text-slate-700">{call.contact_name ?? "—"}</td>
                      <td className="px-4 py-3 text-slate-500 text-xs">{call.contact_phone ?? "—"}</td>
                      <td className="px-4 py-3 text-slate-600">
                        {call.amount_due != null
                          ? <span className="font-medium">₹{Number(call.amount_due).toLocaleString()}</span>
                          : <span className="text-slate-400">—</span>}
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {call.days_overdue != null
                          ? <span>{call.days_overdue}d</span>
                          : <span className="text-slate-400">—</span>}
                      </td>
                      <td className="px-4 py-3">{formatDuration(call.duration_seconds)}</td>
                      <td className="px-4 py-3">{analysisStatusBadge(analysis?.analysis_status)}</td>
                      <td className="px-4 py-3">{sentimentBadge(analysis?.overall_sentiment)}</td>
                      <td className="px-4 py-3">
                        {repaymentPct != null
                          ? <span className={repaymentPct >= 60 ? "font-semibold text-green-600" : repaymentPct >= 30 ? "font-semibold text-amber-600" : "font-semibold text-red-600"}>{repaymentPct}%</span>
                          : <span className="text-slate-400">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        {analysis?.recommended_strategy
                          ? <Badge variant="info">{analysis.recommended_strategy}</Badge>
                          : <span className="text-slate-400">—</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Make a Call Modal */}
      <Modal
        open={phase !== "idle"}
        onClose={closeModal}
        title={phase === "active" ? "Call in Progress" : phase === "ended" ? "Call Ended" : "Make a Call"}
      >
        <div className="space-y-4">

          {/* FORM phase */}
          {phase === "form" && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Input
                  label="Contact Name *"
                  placeholder="e.g. Rahul Kumar"
                  value={contactName}
                  onChange={(e) => setContactName(e.target.value)}
                />
                <Input
                  label="Phone Number *"
                  placeholder="+91XXXXXXXXXX"
                  value={contactPhone}
                  onChange={(e) => setContactPhone(e.target.value)}
                />
                <Input
                  label="Amount Due (₹)"
                  placeholder="e.g. 45000"
                  type="number"
                  value={amountDue}
                  onChange={(e) => setAmountDue(e.target.value)}
                />
                <Input
                  label="Days Overdue"
                  placeholder="e.g. 90"
                  type="number"
                  value={daysOverdue}
                  onChange={(e) => setDaysOverdue(e.target.value)}
                />
              </div>
              <Input
                label="Your Name (Agent)"
                placeholder="e.g. Priya Sharma"
                value={agentName}
                onChange={(e) => setAgentName(e.target.value)}
              />
              <p className="text-xs text-slate-500">
                Your browser microphone connects directly to the contact's phone. Deepgram transcribes the call live; AI analysis is generated when you hang up.
              </p>
              {callError && <p className="text-sm text-red-600">{callError}</p>}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={closeModal}>Cancel</Button>
                <Button variant="primary" disabled={!canCall} onClick={handleCallNow}>
                  <Phone size={14} />
                  Call Now
                </Button>
              </div>
            </>
          )}

          {/* CONNECTING phase */}
          {phase === "connecting" && (
            <div className="flex flex-col items-center gap-3 py-6">
              <Spinner className="w-8 h-8 text-indigo-600" />
              <p className="text-sm text-slate-600">Setting up secure connection…</p>
              <p className="text-xs text-slate-400">Initialising Twilio Device</p>
            </div>
          )}

          {/* RINGING phase */}
          {phase === "ringing" && (
            <div className="flex flex-col items-center gap-4 py-6">
              <div className="w-16 h-16 rounded-full bg-indigo-100 flex items-center justify-center animate-pulse">
                <Phone size={28} className="text-indigo-600" />
              </div>
              <div className="text-center">
                <p className="font-semibold text-slate-700">{contactName}</p>
                <p className="text-sm text-slate-500 mt-0.5">{contactPhone}</p>
                <p className="text-sm text-slate-500 mt-1">Ringing…</p>
              </div>
              <Button variant="danger" onClick={handleHangUp}>
                <PhoneOff size={14} />
                Cancel
              </Button>
            </div>
          )}

          {/* ACTIVE phase */}
          {phase === "active" && (
            <div className="flex flex-col items-center gap-4 py-4">
              <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center">
                <Phone size={28} className="text-green-600" />
              </div>
              <div className="text-center">
                <p className="font-semibold text-slate-700">{contactName}</p>
                <p className="text-sm text-slate-500 mt-0.5">{contactPhone}</p>
                <p className="text-lg font-mono text-green-600 mt-1">{formatTimer(callDuration)}</p>
                <p className="text-xs text-slate-400 mt-0.5">Connected · Deepgram transcribing live</p>
              </div>
              <div className="flex gap-3">
                <Button
                  variant={muted ? "danger" : "ghost"}
                  onClick={toggleMute}
                  className="flex items-center gap-2"
                >
                  {muted ? <MicOff size={16} /> : <Mic size={16} />}
                  {muted ? "Unmute" : "Mute"}
                </Button>
                <Button variant="danger" onClick={handleHangUp}>
                  <PhoneOff size={14} />
                  Hang Up
                </Button>
              </div>
            </div>
          )}

          {/* ENDED phase */}
          {phase === "ended" && (
            <div className="flex flex-col items-center gap-3 py-4">
              <div className="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center">
                <PhoneOff size={28} className="text-slate-500" />
              </div>
              <div className="text-center">
                <p className="font-semibold text-slate-700">Call Ended</p>
                {callDuration > 0 && (
                  <p className="text-sm text-slate-500 mt-1">Duration: {formatTimer(callDuration)}</p>
                )}
                <p className="text-xs text-slate-400 mt-1">AI analysis is being generated — check the call list</p>
              </div>
              {callError && <p className="text-sm text-red-600">{callError}</p>}
              <div className="flex gap-2">
                <Button variant="ghost" onClick={closeModal}>Close</Button>
                {currentCallId && (
                  <Button variant="primary" onClick={() => { closeModal(); navigate(`/human-calls/${currentCallId}`); }}>
                    View Intelligence Report
                  </Button>
                )}
              </div>
            </div>
          )}

        </div>
      </Modal>
    </div>
  );
}
