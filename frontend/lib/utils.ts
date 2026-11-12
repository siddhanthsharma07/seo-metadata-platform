import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtDate(v?: string | null) {
  if (!v) return "—";
  return new Date(v).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function shortUrl(url: string) {
  try {
    const u = new URL(url);
    return (u.pathname + u.search) || "/";
  } catch {
    return url;
  }
}
