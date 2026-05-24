import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { campaignsApi } from "@/api/campaigns";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { PageSpinner } from "@/components/ui/Spinner";
import { formatDate } from "@/lib/utils";
import { ArrowLeft, Play, UserPlus } from "lucide-react";

function statusVariant(status: string) {
  return status === "active" ? "success" : status === "completed" ? "info" : status === "paused" ? "warning" : "muted";
}

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [addModal, setAddModal] = useState(false);
  const [borrowerIds, setBorrowerIds] = useState("");

  const { data: campaign, isLoading } = useQuery({
    queryKey: ["campaign", id],
    queryFn: () => campaignsApi.get(id!),
    enabled: !!id,
  });

  const startCampaign = useMutation({
    mutationFn: () => campaignsApi.start(id!),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["campaign", id] }),
  });

  const addBorrowers = useMutation({
    mutationFn: () => {
      const ids = borrowerIds.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean);
      return campaignsApi.addBorrowers(id!, ids);
    },
    onSuccess: () => {
      setBorrowerIds("");
      setAddModal(false);
    },
  });

  if (isLoading) return <PageSpinner />;
  if (!campaign) return <div className="p-6 text-slate-500">Campaign not found</div>;

  return (
    <div className="p-6 space-y-5 max-w-4xl">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="text-slate-400 hover:text-slate-600">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <h1 className="text-xl font-bold text-slate-800">{campaign.name}</h1>
          <p className="text-sm text-slate-500">Created {formatDate(campaign.created_at)}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setAddModal(true)}>
            <UserPlus size={14} />
            Add Borrowers
          </Button>
          {campaign.status !== "active" && (
            <Button
              variant="primary"
              loading={startCampaign.isPending}
              onClick={() => startCampaign.mutate()}
            >
              <Play size={14} />
              Start Campaign
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="py-3">
            <div className="text-xs text-slate-500">Status</div>
            <div className="mt-1">
              <Badge variant={statusVariant(campaign.status)}>{campaign.status}</Badge>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-3">
            <div className="text-xs text-slate-500">Strategy</div>
            <div className="text-sm font-semibold text-slate-800 mt-0.5 capitalize">{campaign.strategy_type}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-3">
            <div className="text-xs text-slate-500">Max Attempts</div>
            <div className="text-sm font-semibold text-slate-800 mt-0.5">{campaign.max_attempts}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-3">
            <div className="text-xs text-slate-500">Campaign ID</div>
            <div className="text-xs font-mono text-slate-500 mt-0.5 truncate">{campaign.id}</div>
          </CardContent>
        </Card>
      </div>

      {startCampaign.error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-4 py-3">
          {startCampaign.error.message}
        </p>
      )}

      <Card>
        <CardHeader><CardTitle>Campaign Settings</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-slate-500">Strategy: </span>
              <span className="font-medium capitalize">{campaign.strategy_type}</span>
            </div>
            <div>
              <span className="text-slate-500">Max Attempts: </span>
              <span className="font-medium">{campaign.max_attempts}</span>
            </div>
          </div>
          <p className="text-sm text-slate-400 mt-4">
            Use "Add Borrowers" to enroll borrowers, then "Start Campaign" to begin dispatching calls via Celery.
          </p>
        </CardContent>
      </Card>

      {/* Add Borrowers Modal */}
      <Modal open={addModal} onClose={() => setAddModal(false)} title="Add Borrowers to Campaign">
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            Paste borrower UUIDs, one per line or comma-separated.
          </p>
          <textarea
            className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm font-mono h-32 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder={"uuid-1\nuuid-2\n..."}
            value={borrowerIds}
            onChange={(e) => setBorrowerIds(e.target.value)}
          />
          {addBorrowers.isSuccess && (
            <p className="text-sm text-green-600">Borrowers added successfully.</p>
          )}
          {addBorrowers.error && <p className="text-sm text-red-600">{addBorrowers.error.message}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setAddModal(false)}>Cancel</Button>
            <Button variant="primary" loading={addBorrowers.isPending} onClick={() => addBorrowers.mutate()}>
              Add
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
