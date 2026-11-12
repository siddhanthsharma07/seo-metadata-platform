"use client";

const TOKEN_KEY = "smi_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function messageFrom(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: string }).message);
  return fallback;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, headers, body });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check that the backend is running.");
  }
  if (res.status === 401 && !path.startsWith("/auth/")) {
    setToken(null);
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) window.location.href = "/login";
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = typeof data === "object" && data ? (data as { detail?: unknown }).detail : data;
    throw new ApiError(res.status, messageFrom(detail, `Request failed (${res.status})`), detail);
  }
  return data as T;
}

export const fetcher = <T,>(path: string) => api<T>(path);

export async function download(path: string) {
  const token = getToken();
  const res = await fetch(`/api${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let msg = `Download failed (${res.status})`;
    try {
      msg = (await res.json()).detail || msg;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, msg);
  }
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] || "export";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
