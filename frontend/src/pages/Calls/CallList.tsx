import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { callsApi } from "@/api/calls";
import { Card } from "@/components/ui/Card";
import { Badge, outcomeVariant } from "@/components/ui/Badge";
import { Select } from "@/components/ui/Input";
import { PageSpinner } from "@/components/ui/Spinner";
import { formatDate, formatDuration } from "@/lib/utils";
import { Shield, ShieldAlert } from "lucide-react";

export default function CallList() {
  const navigate = useNavigate();
  const [outcome, setOutcome] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["calls", outcome],
    queryFn: () => callsApi.list({ outcome: outcome || undefined, limit: 100 }),
  });

  const rows = data ?? [];

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Calls</h1>
          <p className="text-sm text-slate-500 mt-0.5">{rows.length} records</p>
        </div>
        <Select value={outcome} onChange={(e) => setOutcome(e.target.value)} className="w-44">
          <option value="">All Outcomes</option>
          <option value="promise_made">Promise Made</option>
          <option value="payment_taken">Payment Taken</option>
          <option value="refused">Refused</option>
          <option value="voicemail">Voicemail</option>
          <option value="no_answer">No Answer</option>
          <option value="dispute_raised">Dispute Raised</option>
          <option value="callback_requested">Callback Requested</option>
        </Select>
      </div>

      <Card>
        {isLoading ? (
          <PageSpinner />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-100">
                <tr>
                  {["Date", "Status", "Outcome", "Duration", "Turns", "Interruptions", "Sentiment Δ", "Compliance"].map((h) => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr><td colSpan={8} className="text-center py-12 text-slate-400">No calls found</td></tr>
                )}
                {rows.map((c) => {
                  const sentimentDelta =
                    c.sentiment_trajectory.length >= 2
                      ? (c.sentiment_trajectory.at(-1)?.score ?? 0) - (c.sentiment_trajectory[0]?.score ?? 0)
                      : null;

                  return (
                    <tr
                      key={c.id}
                      className="border-b border-slate-50 hover:bg-slate-50 cursor-pointer transition-colors"
                      onClick={() => navigate(`/calls/${c.id}`)}
                    >
                      <td className="px-4 py-3 text-slate-600">{formatDate(c.created_at)}</td>
                      <td className="px-4 py-3">
                        <Badge variant={c.status === "completed" ? "success" : c.status === "failed" ? "danger" : "default"}>
                          {c.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={outcomeVariant(c.outcome)}>
                          {c.outcome?.replace(/_/g, " ") ?? "—"}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">{formatDuration(c.duration_seconds)}</td>
                      <td className="px-4 py-3">{c.turn_count}</td>
                      <td className="px-4 py-3">{c.interruption_count}</td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {sentimentDelta != null ? (
                          <span className={sentimentDelta > 0 ? "text-green-600" : sentimentDelta < 0 ? "text-red-600" : "text-slate-500"}>
                            {sentimentDelta > 0 ? "+" : ""}{sentimentDelta.toFixed(2)}
                          </span>
                        ) : "—"}
                      </td>
                      <td className="px-4 py-3">
                        {c.compliance_passed ? (
                          <Shield size={14} className="text-green-500" />
                        ) : (
                          <ShieldAlert size={14} className="text-red-500" />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
