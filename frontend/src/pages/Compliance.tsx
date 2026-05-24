import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { complianceApi } from "@/api/compliance";
import { borrowersApi } from "@/api/borrowers";
import { Card } from "@/components/ui/Card";
import { Badge, severityVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PageSpinner } from "@/components/ui/Spinner";
import { formatDate } from "@/lib/utils";
import { Search, Link } from "lucide-react";
import { Link as RouterLink } from "react-router-dom";
import type { ComplianceEvent } from "@/api/compliance";

function EventsTable({ events, borrowerMap }: { events: ComplianceEvent[]; borrowerMap: Record<string, { first_name?: string; last_name?: string }> }) {
  if (events.length === 0) {
    return <p className="text-sm text-slate-400 py-12 text-center">No compliance events</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 border-b border-slate-100">
          <tr>
            {["Time", "Borrower", "Type", "Severity", "Call", "Description"].map((h) => (
              <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id} className="border-b border-slate-50 hover:bg-slate-50">
              <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{formatDate(e.created_at)}</td>
              <td className="px-4 py-3 text-xs">
                {borrowerMap[e.borrower_id] ? (
                  <RouterLink to={`/borrowers/${e.borrower_id}`} className="text-indigo-600 hover:underline font-medium">
                    {borrowerMap[e.borrower_id].first_name} {borrowerMap[e.borrower_id].last_name}
                  </RouterLink>
                ) : (
                  <span className="font-mono text-slate-400">{e.borrower_id.slice(0, 8)}…</span>
                )}
              </td>
              <td className="px-4 py-3 font-mono text-xs">{e.event_type.replace(/_/g, " ")}</td>
              <td className="px-4 py-3">
                <Badge variant={severityVariant(e.severity)}>{e.severity}</Badge>
              </td>
              <td className="px-4 py-3">
                {e.call_id ? (
                  <RouterLink to={`/calls/${e.call_id}`} className="text-indigo-500 hover:underline text-xs font-mono flex items-center gap-1">
                    <Link size={10} />
                    {e.call_id.slice(0, 8)}…
                  </RouterLink>
                ) : "—"}
              </td>
              <td className="px-4 py-3 text-slate-600">{e.description ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Compliance() {
  const [borrowerId, setBorrowerId] = useState("");
  const [submitted, setSubmitted] = useState("");

  const { data: recentEvents, isLoading: loadingRecent } = useQuery({
    queryKey: ["compliance", "recent"],
    queryFn: () => complianceApi.listRecent(),
  });

  const { data: borrowerEvents, isLoading: loadingBorrower, error: borrowerError } = useQuery({
    queryKey: ["compliance", "borrower", submitted],
    queryFn: () => complianceApi.getEvents(submitted),
    enabled: !!submitted,
  });

  const { data: borrowers } = useQuery({
    queryKey: ["borrowers"],
    queryFn: () => borrowersApi.list(),
  });

  const borrowerMap = Object.fromEntries((borrowers ?? []).map((b) => [b.id, b]));

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-slate-800">Compliance Audit</h1>
        <p className="text-sm text-slate-500 mt-0.5">FDCPA event log · 7-year immutable trail</p>
      </div>

      {/* Recent events — global view, always visible */}
      <Card>
        <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-700">Recent Events</p>
            <p className="text-xs text-slate-400 mt-0.5">Latest 50 events across all borrowers</p>
          </div>
          {recentEvents && (
            <span className="text-xs text-slate-400">{recentEvents.length} events</span>
          )}
        </div>
        {loadingRecent ? (
          <PageSpinner />
        ) : (
          <EventsTable events={recentEvents ?? []} borrowerMap={borrowerMap} />
        )}
      </Card>

      {/* Search by borrower */}
      <Card>
        <div className="p-4 border-b border-slate-100">
          <p className="text-sm font-semibold text-slate-700 mb-3">Search by Borrower</p>
          <div className="flex gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                className="w-full border border-slate-300 rounded-md pl-8 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                placeholder="Enter borrower UUID…"
                value={borrowerId}
                onChange={(e) => setBorrowerId(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && setSubmitted(borrowerId.trim())}
              />
            </div>
            <Button variant="primary" onClick={() => setSubmitted(borrowerId.trim())} disabled={!borrowerId.trim()}>
              Search
            </Button>
          </div>
        </div>

        {!submitted && (
          <p className="text-sm text-slate-400 py-8 text-center">Enter a borrower UUID to filter events by borrower</p>
        )}

        {submitted && loadingBorrower && <PageSpinner />}

        {submitted && borrowerError && (
          <p className="text-sm text-red-600 px-4 py-8 text-center">{(borrowerError as Error).message}</p>
        )}

        {submitted && borrowerEvents && (
          <>
            <div className="px-4 py-3 bg-slate-50 border-b border-slate-100 text-sm">
              <span className="text-slate-500">Borrower: </span>
              {borrowerMap[submitted] ? (
                <RouterLink to={`/borrowers/${submitted}`} className="text-indigo-600 hover:underline font-medium">
                  {borrowerMap[submitted].first_name} {borrowerMap[submitted].last_name}
                </RouterLink>
              ) : (
                <span className="font-mono text-xs">{submitted}</span>
              )}
              <span className="ml-2 text-slate-400">· {Array.isArray(borrowerEvents) ? borrowerEvents.length : 0} events</span>
            </div>
            <EventsTable events={Array.isArray(borrowerEvents) ? borrowerEvents : []} borrowerMap={borrowerMap} />
          </>
        )}
      </Card>
    </div>
  );
}
