import * as React from "react";
import { cn } from "@/lib/utils";

const base =
  "w-full rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-900 placeholder:text-gray-400 shadow-xs focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 disabled:bg-gray-50";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn(base, "h-9", className)} {...p} />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...p }, ref) => <textarea ref={ref} className={cn(base, "min-h-[80px] py-2 leading-relaxed", className)} {...p} />,
);
Textarea.displayName = "Textarea";

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(({ className, ...p }, ref) => (
  <select ref={ref} className={cn(base, "h-9 pr-8", className)} {...p} />
));
Select.displayName = "Select";

export function Label({ className, ...p }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("mb-1 block text-xs font-medium text-gray-700", className)} {...p} />;
}

export function Field({ label, hint, children, className }: { label: string; hint?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <Label>{label}</Label>
      {children}
      {hint ? <p className="mt-1 text-[11px] text-gray-500">{hint}</p> : null}
    </div>
  );
}

export function Checkbox({ label, checked, onChange, className }: { label?: React.ReactNode; checked: boolean; onChange: (v: boolean) => void; className?: string }) {
  return (
    <label className={cn("inline-flex cursor-pointer items-center gap-2 text-sm text-gray-700", className)}>
      <input type="checkbox" className="h-4 w-4 rounded border-gray-300 accent-brand-600" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
