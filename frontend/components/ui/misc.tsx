"use client";
import { X } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

export function Progress({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-gray-100", className)}>
      <div className="h-full rounded-full bg-brand-600 transition-all" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: { key: string; label: React.ReactNode }[]; value: string; onChange: (k: string) => void }) {
  return (
    <div className="flex gap-1 border-b border-gray-200">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={cn(
            "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
            value === t.key ? "border-brand-600 text-brand-700" : "border-transparent text-gray-500 hover:text-gray-800",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Sheet({ open, onClose, title, children, width = "max-w-4xl" }: { open: boolean; onClose: () => void; title: React.ReactNode; children: React.ReactNode; width?: string }) {
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-gray-900/20" onClick={onClose} />
      <div className={cn("relative flex h-full w-full flex-col bg-white shadow-xl", width)}>
        <div className="flex items-center justify-between gap-4 border-b border-gray-200 px-5 py-3">
          <div className="min-w-0 flex-1">{title}</div>
          <button onClick={onClose} className="rounded p-1 text-gray-500 hover:bg-gray-100" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

export function Dialog({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; footer?: React.ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-gray-900/30" onClick={onClose} />
      <div className="relative w-full max-w-lg rounded-lg bg-white shadow-xl">
        <div className="border-b border-gray-100 px-5 py-3 text-sm font-semibold">{title}</div>
        <div className="px-5 py-4">{children}</div>
        {footer ? <div className="flex justify-end gap-2 border-t border-gray-100 px-5 py-3">{footer}</div> : null}
      </div>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: React.ReactNode; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      {icon ? <div className="mb-3 text-gray-300">{icon}</div> : null}
      <p className="text-sm font-medium text-gray-800">{title}</p>
      {children ? <div className="mt-1 max-w-md text-sm text-gray-500">{children}</div> : null}
    </div>
  );
}

export function Alert({ tone = "amber", children, className }: { tone?: "amber" | "red" | "blue" | "green"; children: React.ReactNode; className?: string }) {
  const t = {
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    red: "border-red-200 bg-red-50 text-red-800",
    blue: "border-brand-100 bg-brand-50 text-brand-700",
    green: "border-emerald-200 bg-emerald-50 text-emerald-800",
  }[tone];
  return <div className={cn("rounded-md border px-3 py-2 text-sm", t, className)}>{children}</div>;
}

export function PageHeader({ title, description, actions }: { title: string; description?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-gray-900">{title}</h1>
        {description ? <p className="mt-1 text-sm text-gray-500">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: "red" | "amber" | "green" }) {
  const c = tone === "red" ? "text-red-600" : tone === "amber" ? "text-amber-600" : tone === "green" ? "text-emerald-600" : "text-gray-900";
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className={cn("mt-1 text-2xl font-semibold tabular", c)}>{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-gray-400">{hint}</p> : null}
    </div>
  );
}
