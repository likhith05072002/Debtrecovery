import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { campaignsApi } from "@/api/campaigns";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PageSpinner } from "@/components/ui/Spinner";
import { formatDate } from "@/lib/utils";
import { Plus } from "lucide-react";
import CampaignForm from "./CampaignForm";

function statusVariant(status: string) {
  return status === "active" ? "success" : status === "completed" ? "info" : status === "paused" ? "warning" : "muted";
}

function strategyColor(strategy: string) {
  const map: Record<string, string> = {
    auto: "bg-indigo-100 text-indigo-700",
    reminder: "bg-blue-100 text-blue-700",
    negotiation: "bg-amber-100 text-amber-700",
    settlement: "bg-orange-100 text-orange-700",
    escalation: "bg-red-100 text-red-700",
  };
  return map[strategy] ?? "bg-slate-100 text-slate-600";
}

export default function CampaignList() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["campaigns"],
    queryFn: campaignsApi.list,
  });

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Campaigns</h1>
          <p className="text-sm text-slate-500 mt-0.5">{(data ?? []).length} campaigns</p>
        </div>
        <Button variant="primary" onClick={() => setShowForm(true)}>
          <Plus size={14} />
          New Campaign
        </Button>
      </div>

      {isLoading ? (
        <PageSpinner />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {(data ?? []).length === 0 && (
            <p className="text-sm text-slate-400 col-span-3 py-8 text-center">No campaigns yet</p>
          )}
          {(data ?? []).map((c) => (
            <Card
              key={c.id}
              className="cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => navigate(`/campaigns/${c.id}`)}
            >
              <div className="p-5">
                <div className="flex items-start justify-between mb-3">
                  <h3 className="font-semibold text-slate-800 text-sm leading-tight">{c.name}</h3>
                  <Badge variant={statusVariant(c.status)}>{c.status}</Badge>
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className={`px-2 py-0.5 rounded font-medium ${strategyColor(c.strategy_type)}`}>
                    {c.strategy_type}
                  </span>
                  <span className="text-slate-500">max {c.max_attempts} attempts</span>
                </div>
                <p className="text-xs text-slate-400 mt-3">{formatDate(c.created_at)}</p>
              </div>
            </Card>
          ))}
        </div>
      )}

      <CampaignForm
        open={showForm}
        onClose={() => setShowForm(false)}
        onSaved={() => {
          setShowForm(false);
          void qc.invalidateQueries({ queryKey: ["campaigns"] });
        }}
      />
    </div>
  );
}
