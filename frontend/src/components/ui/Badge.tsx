import { cn } from "@/lib/utils";

type Variant = "default" | "success" | "warning" | "danger" | "info" | "muted";

const variants: Record<Variant, string> = {
  default: "bg-slate-100 text-slate-700",
  success: "bg-green-100 text-green-800",
  warning: "bg-yellow-100 text-yellow-800",
  danger: "bg-red-100 text-red-800",
  info: "bg-blue-100 text-blue-800",
  muted: "bg-slate-200 text-slate-500",
};

interface BadgeProps {
  variant?: Variant;
  children: React.ReactNode;
  className?: string;
}

export function Badge({ variant = "default", children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium",
        variants[variant],
        className
      )}
    >
      {children}
    </span>
  );
}

export function outcomeVariant(outcome?: string | null): Variant {
  if (!outcome) return "muted";
  const map: Record<string, Variant> = {
    promise_made: "success",
    payment_taken: "success",
    connected: "info",
    voicemail: "default",
    refused: "warning",
    dispute_raised: "danger",
    callback_requested: "info",
    no_answer: "muted",
    failed: "danger",
  };
  return map[outcome] ?? "default";
}

export function severityVariant(severity: string): Variant {
  return severity === "violation" ? "danger" : severity === "warning" ? "warning" : "info";
}
