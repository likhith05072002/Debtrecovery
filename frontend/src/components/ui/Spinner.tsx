import { cn } from "@/lib/utils";

export function Spinner({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "inline-block w-5 h-5 border-2 border-slate-300 border-t-indigo-600 rounded-full animate-spin",
        className
      )}
    />
  );
}

export function PageSpinner() {
  return (
    <div className="flex items-center justify-center h-48">
      <Spinner className="w-8 h-8" />
    </div>
  );
}
