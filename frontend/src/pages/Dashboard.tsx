import { useQuery } from "@tanstack/react-query";
import { analyticsApi } from "@/api/analytics";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageSpinner } from "@/components/ui/Spinner";
import { formatCurrency, formatDuration } from "@/lib/utils";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { Phone, TrendingUp, DollarSign, ShieldAlert, Clock, Users } from "lucide-react";

const PIE_COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#64748b", "#06b6d4"];

export default function Dashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: analyticsApi.getDashboard,
    refetchInterval: 30_000,
  });

  if (isLoading) return <PageSpinner />;
  if (!data) return null;

  const { summary, hourly_breakdown, outcome_distribution } = data;

  const kpis = [
    {
      label: "Total Calls",
      value: summary.total_calls.toLocaleString(),
      icon: Phone,
      color: "text-indigo-600",
      bg: "bg-indigo-50",
    },
    {
      label: "Connected Rate",
      value: `${(summary.connected_rate * 100).toFixed(1)}%`,
      icon: Users,
      color: "text-blue-600",
      bg: "bg-blue-50",
    },
    {
      label: "Promise Rate",
      value: `${(summary.promise_rate * 100).toFixed(1)}%`,
      icon: TrendingUp,
      color: "text-green-600",
      bg: "bg-green-50",
    },
    {
      label: "Collected",
      value: formatCurrency(summary.payment_collected),
      icon: DollarSign,
      color: "text-emerald-600",
      bg: "bg-emerald-50",
    },
    {
      label: "Avg Duration",
      value: formatDuration(summary.avg_call_duration),
      icon: Clock,
      color: "text-amber-600",
      bg: "bg-amber-50",
    },
    {
      label: "FDCPA Violations",
      value: summary.compliance_violations.toString(),
      icon: ShieldAlert,
      color: summary.compliance_violations > 0 ? "text-red-600" : "text-slate-500",
      bg: summary.compliance_violations > 0 ? "bg-red-50" : "bg-slate-50",
    },
  ];

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-800">Dashboard</h1>
        <p className="text-sm text-slate-500 mt-0.5">Live overview · refreshes every 30s</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        {kpis.map(({ label, value, icon: Icon, color, bg }) => (
          <Card key={label}>
            <CardContent className="py-4">
              <div className={`inline-flex p-2 rounded-lg ${bg} mb-3`}>
                <Icon size={18} className={color} />
              </div>
              <div className="text-xl font-bold text-slate-800">{value}</div>
              <div className="text-xs text-slate-500 mt-0.5">{label}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Hourly Breakdown */}
        <Card>
          <CardHeader>
            <CardTitle>Calls by Hour</CardTitle>
          </CardHeader>
          <CardContent>
            {hourly_breakdown.length === 0 ? (
              <p className="text-sm text-slate-400 py-8 text-center">No data yet</p>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={hourly_breakdown}>
                  <XAxis
                    dataKey="hour"
                    tickFormatter={(h) => `${h}:00`}
                    tick={{ fontSize: 11 }}
                  />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(v, name) => [v, name === "calls" ? "Total" : name === "connected" ? "Connected" : "Promised"]}
                    labelFormatter={(h) => `Hour ${h}:00`}
                  />
                  <Bar dataKey="calls" fill="#e0e7ff" name="calls" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="connected" fill="#6366f1" name="connected" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="promise_made" fill="#22c55e" name="promise_made" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* Outcome Distribution */}
        <Card>
          <CardHeader>
            <CardTitle>Outcome Distribution</CardTitle>
          </CardHeader>
          <CardContent>
            {outcome_distribution.length === 0 ? (
              <p className="text-sm text-slate-400 py-8 text-center">No data yet</p>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={outcome_distribution}
                    dataKey="count"
                    nameKey="outcome"
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    labelLine={false}
                  >
                    {outcome_distribution.map((_, i) => (
                      <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Legend
                    formatter={(v) => v.replace(/_/g, " ")}
                    wrapperStyle={{ fontSize: 11 }}
                  />
                  <Tooltip formatter={(v) => [v, "calls"]} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
