import { useQuery } from "@tanstack/react-query";
import { analyticsApi } from "@/api/analytics";
import { Card, CardContent } from "@/components/ui/Card";
import { PageSpinner } from "@/components/ui/Spinner";
import { Activity } from "lucide-react";

interface MetricCardProps {
  label: string;
  value?: number | null;
  unit?: string;
  good?: (v: number) => boolean;
}

function MetricCard({ label, value, unit = "ms", good }: MetricCardProps) {
  const isGood = value != null && good ? good(value) : null;
  return (
    <Card>
      <CardContent className="py-5">
        <div className="text-xs text-slate-500 mb-2">{label}</div>
        {value != null ? (
          <div className={`text-2xl font-bold ${isGood === true ? "text-green-600" : isGood === false ? "text-red-600" : "text-slate-800"}`}>
            {unit === "%" ? `${(value * 100).toFixed(1)}%` : `${Math.round(value)}${unit}`}
          </div>
        ) : (
          <div className="text-2xl font-bold text-slate-300">—</div>
        )}
      </CardContent>
    </Card>
  );
}

export default function CallQuality() {
  const { data, isLoading } = useQuery({
    queryKey: ["call-quality"],
    queryFn: analyticsApi.getCallQuality,
    refetchInterval: 60_000,
  });

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-2">
        <Activity size={20} className="text-indigo-500" />
        <div>
          <h1 className="text-xl font-bold text-slate-800">Call Quality</h1>
          <p className="text-sm text-slate-500 mt-0.5">Latency metrics · refreshes every 60s</p>
        </div>
      </div>

      {isLoading ? (
        <PageSpinner />
      ) : !data ? null : (
        <>
          <div>
            <h2 className="text-sm font-semibold text-slate-600 mb-3">Average Latency</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <MetricCard label="STT (avg)" value={data.avg_stt_latency_ms} good={(v) => v < 150} />
              <MetricCard label="LLM (avg)" value={data.avg_llm_latency_ms} good={(v) => v < 500} />
              <MetricCard label="TTS (avg)" value={data.avg_tts_latency_ms} good={(v) => v < 150} />
              <MetricCard label="End-to-End (avg)" value={data.avg_e2e_latency_ms} good={(v) => v < 1100} />
            </div>
          </div>

          <div>
            <h2 className="text-sm font-semibold text-slate-600 mb-3">p95 Latency</h2>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <MetricCard label="STT (p95)" value={data.p95_stt_latency_ms} good={(v) => v < 200} />
              <MetricCard label="LLM (p95)" value={data.p95_llm_latency_ms} good={(v) => v < 700} />
              <MetricCard label="TTS (p95)" value={data.p95_tts_latency_ms} good={(v) => v < 200} />
            </div>
          </div>

          <div>
            <h2 className="text-sm font-semibold text-slate-600 mb-3">Quality Signals</h2>
            <div className="grid grid-cols-2 gap-4">
              <MetricCard
                label="Barge-In Rate"
                value={data.barge_in_rate}
                unit="%"
                good={(v) => v < 0.2}
              />
              <MetricCard
                label="STT Confidence (avg)"
                value={data.stt_confidence_avg}
                unit="%"
                good={(v) => v > 0.75}
              />
            </div>
          </div>

          <div className="text-xs text-slate-400 border-t border-slate-100 pt-4">
            <strong>Targets:</strong> STT p50 &lt;150ms · LLM p50 &lt;500ms · TTS p50 &lt;150ms · E2E p50 &lt;600ms · STT confidence &gt;75%
          </div>
        </>
      )}
    </div>
  );
}
