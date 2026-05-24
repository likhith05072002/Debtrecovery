import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { borrowersApi } from "@/api/borrowers";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Input";
import { PageSpinner } from "@/components/ui/Spinner";
import { formatCurrency } from "@/lib/utils";
import { Plus, Search, Trash2 } from "lucide-react";
import BorrowerForm from "./BorrowerForm";

export default function BorrowerList() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "dnc" | "opted_out">("all");
  const [showForm, setShowForm] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["borrowers", search, filter],
    queryFn: () =>
      borrowersApi.list({
        ...(filter === "dnc" ? { do_not_call: true } : {}),
        ...(filter === "opted_out" ? { opted_out: true } : {}),
      }),
  });

  const filtered = (data ?? []).filter((b) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      b.external_id?.toLowerCase().includes(q) ||
      b.first_name?.toLowerCase().includes(q) ||
      b.last_name?.toLowerCase().includes(q)
    );
  });

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Borrowers</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {data?.length ?? 0} total records
          </p>
        </div>
        <Button variant="primary" onClick={() => setShowForm(true)}>
          <Plus size={14} />
          New Borrower
        </Button>
      </div>

      <div className="flex gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            className="w-full border border-slate-300 rounded-md pl-8 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder="Search by name or ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} className="w-36">
          <option value="all">All</option>
          <option value="dnc">DNC Only</option>
          <option value="opted_out">Opted Out</option>
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
                  {["Name", "External ID", "Balance", "DPD", "Engagement", "Last Status", "Flags", ""].map((h) => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={8} className="text-center py-12 text-slate-400 text-sm">
                      No borrowers found
                    </td>
                  </tr>
                )}
                {filtered.map((b) => (
                  <tr
                    key={b.id}
                    className="border-b border-slate-50 hover:bg-slate-50 cursor-pointer transition-colors"
                    onClick={() => navigate(`/borrowers/${b.id}`)}
                  >

                    <td className="px-4 py-3 font-medium text-slate-800">
                      {b.first_name} {b.last_name}
                    </td>
                    <td className="px-4 py-3 text-slate-500 font-mono text-xs">{b.external_id}</td>
                    <td className="px-4 py-3">{formatCurrency(b.current_balance)}</td>
                    <td className="px-4 py-3">
                      <span className={b.days_past_due > 90 ? "text-red-600 font-medium" : b.days_past_due > 30 ? "text-amber-600" : "text-slate-700"}>
                        {b.days_past_due}d
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {b.engagement_score != null ? (
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-indigo-500 rounded-full"
                              style={{ width: `${Math.round(b.engagement_score * 100)}%` }}
                            />
                          </div>
                          <span className="text-xs text-slate-500">{(b.engagement_score * 100).toFixed(0)}%</span>
                        </div>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={b.opted_out ? "danger" : b.do_not_call ? "warning" : "muted"}>
                        {b.opted_out ? "Opted Out" : b.do_not_call ? "DNC" : "Active"}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 flex gap-1 flex-wrap">
                      {b.opted_out && <Badge variant="danger">OPT-OUT</Badge>}
                      {b.do_not_call && <Badge variant="warning">DNC</Badge>}
                      {b.bankruptcy_filed && <Badge variant="danger">BK</Badge>}
                      {!b.consent_recorded && <Badge variant="warning">No Consent</Badge>}
                    </td>
                    <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                      <button
                        disabled={deletingId === b.id}
                        onClick={async () => {
                          if (!confirm(`Delete ${b.first_name} ${b.last_name}? This cannot be undone.`)) return;
                          setDeletingId(b.id);
                          try {
                            await borrowersApi.remove(b.id);
                            void refetch();
                          } catch (err: any) {
                            alert(`Delete failed: ${err?.response?.data?.detail ?? err?.message ?? "Unknown error"}`);
                          } finally {
                            setDeletingId(null);
                          }
                        }}
                        className="p-1.5 rounded text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors disabled:opacity-40"
                        title="Delete borrower"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <BorrowerForm
        open={showForm}
        onClose={() => setShowForm(false)}
        onSaved={() => {
          setShowForm(false);
          void refetch();
        }}
      />
    </div>
  );
}
