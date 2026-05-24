import { useQuery } from "@tanstack/react-query";
import client from "@/api/client";

interface UsageData {
  ai_minutes_today: number;
  ai_calls_today: number;
  api_calls_today: number;
  ai_minutes_month: number;
  ai_calls_month: number;
  successful_collections_month: number;
}

interface SubscriptionData {
  plan_tier: string;
  status: string;
  trial_ends_at: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
}

interface PlanData {
  tier: string;
  monthly_ai_minutes: number | null;
  max_borrowers: number | null;
  max_users: number | null;
  base_price_cents: number;
  per_minute_rate_cents: number;
}

function UsageBar({ used, limit, label }: { used: number; limit: number | null; label: string }) {
  const pct = limit ? Math.min((used / limit) * 100, 100) : 0;
  const color = pct > 90 ? "bg-red-500" : pct > 75 ? "bg-yellow-500" : "bg-blue-500";

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="text-gray-600">{label}</span>
        <span className="font-medium">
          {Math.round(used)} / {limit ?? "Unlimited"}
        </span>
      </div>
      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`h-full ${color} rounded-full transition-all`}
          style={{ width: limit ? `${pct}%` : "5%" }}
        />
      </div>
    </div>
  );
}

export default function BillingUsage() {
  const { data: usage } = useQuery<UsageData>({
    queryKey: ["billing-usage"],
    queryFn: () => client.get("/billing/usage").then((r) => r.data),
    refetchInterval: 30_000,
  });

  const { data: subscription } = useQuery<SubscriptionData>({
    queryKey: ["billing-subscription"],
    queryFn: () => client.get("/billing/subscription").then((r) => r.data),
  });

  const { data: plans = [] } = useQuery<PlanData[]>({
    queryKey: ["billing-plans"],
    queryFn: () => client.get("/billing/plans").then((r) => r.data),
  });

  const currentPlan = plans.find((p) => p.tier === subscription?.plan_tier);

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-2xl font-bold mb-6">Billing & Usage</h1>

      {/* Current Plan Card */}
      <div className="bg-white rounded-lg border p-6 mb-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold capitalize">
              {subscription?.plan_tier || "Starter"} Plan
            </h2>
            <p className="text-sm text-gray-500 mt-1">
              Status:{" "}
              <span
                className={`font-medium ${
                  subscription?.status === "active"
                    ? "text-green-600"
                    : subscription?.status === "trialing"
                    ? "text-blue-600"
                    : "text-red-600"
                }`}
              >
                {subscription?.status || "trialing"}
              </span>
              {subscription?.trial_ends_at && (
                <span className="ml-2">
                  (trial ends {new Date(subscription.trial_ends_at).toLocaleDateString()})
                </span>
              )}
            </p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold">
              ${currentPlan ? (currentPlan.base_price_cents / 100).toFixed(0) : "499"}
              <span className="text-sm text-gray-500 font-normal">/mo</span>
            </p>
            <button
              onClick={async () => {
                const { data } = await client.post("/billing/portal", {
                  return_url: window.location.href,
                });
                window.location.href = data.portal_url;
              }}
              className="mt-2 text-sm text-blue-600 hover:underline"
            >
              Manage Subscription
            </button>
          </div>
        </div>
      </div>

      {/* Usage Metrics */}
      <div className="bg-white rounded-lg border p-6 mb-6">
        <h2 className="text-lg font-semibold mb-4">Current Usage</h2>
        <div className="space-y-4">
          <UsageBar
            used={usage?.ai_minutes_month || 0}
            limit={currentPlan?.monthly_ai_minutes ?? null}
            label="AI Call Minutes (this month)"
          />
          <UsageBar
            used={usage?.ai_calls_month || 0}
            limit={currentPlan?.monthly_ai_minutes ? currentPlan.monthly_ai_minutes : null}
            label="AI Calls (this month)"
          />
        </div>

        <div className="mt-6 grid grid-cols-3 gap-4">
          <div className="text-center p-3 bg-gray-50 rounded-lg">
            <p className="text-2xl font-bold">{usage?.ai_minutes_today.toFixed(1) || "0"}</p>
            <p className="text-xs text-gray-500">Minutes Today</p>
          </div>
          <div className="text-center p-3 bg-gray-50 rounded-lg">
            <p className="text-2xl font-bold">{usage?.ai_calls_today || 0}</p>
            <p className="text-xs text-gray-500">Calls Today</p>
          </div>
          <div className="text-center p-3 bg-gray-50 rounded-lg">
            <p className="text-2xl font-bold">
              ${(usage?.successful_collections_month || 0).toLocaleString()}
            </p>
            <p className="text-xs text-gray-500">Collected This Month</p>
          </div>
        </div>
      </div>

      {/* Plan Comparison */}
      <div className="bg-white rounded-lg border p-6">
        <h2 className="text-lg font-semibold mb-4">Available Plans</h2>
        <div className="grid grid-cols-3 gap-4">
          {plans.map((plan) => (
            <div
              key={plan.tier}
              className={`p-4 rounded-lg border-2 ${
                plan.tier === subscription?.plan_tier
                  ? "border-blue-500 bg-blue-50"
                  : "border-gray-200"
              }`}
            >
              <h3 className="font-semibold capitalize">{plan.tier}</h3>
              <p className="text-xl font-bold mt-1">
                {plan.base_price_cents > 0
                  ? `$${(plan.base_price_cents / 100).toFixed(0)}/mo`
                  : "Custom"}
              </p>
              <ul className="mt-3 space-y-1 text-sm text-gray-600">
                <li>{plan.monthly_ai_minutes ?? "Unlimited"} AI min/mo</li>
                <li>{plan.max_borrowers?.toLocaleString() ?? "Unlimited"} borrowers</li>
                <li>{plan.max_users ?? "Unlimited"} users</li>
                <li>${(plan.per_minute_rate_cents / 100).toFixed(2)}/min overage</li>
              </ul>
              {plan.tier !== subscription?.plan_tier && plan.base_price_cents > 0 && (
                <button
                  onClick={async () => {
                    const { data } = await client.post("/billing/checkout", {
                      plan_tier: plan.tier,
                      success_url: `${window.location.origin}/settings/billing?success=true`,
                      cancel_url: window.location.href,
                    });
                    window.location.href = data.checkout_url;
                  }}
                  className="mt-3 w-full py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
                >
                  {(currentPlan?.base_price_cents || 0) < plan.base_price_cents
                    ? "Upgrade"
                    : "Switch"}
                </button>
              )}
              {plan.tier === subscription?.plan_tier && (
                <p className="mt-3 text-center text-sm text-blue-600 font-medium">
                  Current Plan
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
