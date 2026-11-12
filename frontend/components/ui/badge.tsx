import * as React from "react";
import { cn } from "@/lib/utils";

const tones: Record<string, string> = {
  gray: "bg-gray-100 text-gray-700 ring-gray-200",
  blue: "bg-brand-50 text-brand-700 ring-brand-100",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  purple: "bg-violet-50 text-violet-700 ring-violet-200",
};

export function Badge({ tone = "gray", className, ...p }: React.HTMLAttributes<HTMLSpanElement> & { tone?: keyof typeof tones | string }) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset", tones[tone] ?? tones.gray, className)}
      {...p}
    />
  );
}

export const severityTone: Record<string, string> = { Critical: "red", High: "amber", Medium: "blue", Low: "gray" };

const statusTones: Record<string, string> = {
  passed: "green", approved: "green", completed: "green", crawled: "green",
  failed: "red", rejected: "red", blocked: "red", cancelled: "gray", stopped: "gray",
  needs_review: "amber", partially_approved: "purple", paused: "amber", stopping: "amber", mixed: "amber",
  pending: "gray", running: "blue", queued: "gray", not_generated: "gray", redirected: "purple", skipped: "gray", duplicate: "gray",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTones[status] ?? "gray"}>{status.replace(/_/g, " ")}</Badge>;
}

export function ScorePill({ score }: { score: number | null | undefined }) {
  if (score === null || score === undefined) return <span className="text-xs text-gray-400">—</span>;
  const tone = score >= 80 ? "bg-emerald-500" : score >= 60 ? "bg-amber-400" : "bg-red-500";
  return (
    <span className="inline-flex items-center gap-1.5 tabular text-xs font-semibold text-gray-800">
      <span className={cn("h-2 w-2 rounded-full", tone)} />
      {score}
    </span>
  );
}

export function CharCount({ n, min, max }: { n: number | null | undefined; min: number; max: number }) {
  if (n === null || n === undefined) return <span className="text-xs text-gray-400">—</span>;
  const ok = n >= min && n <= max;
  return <span className={cn("tabular text-xs font-medium", ok ? "text-emerald-700" : n === 0 ? "text-red-600" : "text-amber-700")}>{n}</span>;
}
