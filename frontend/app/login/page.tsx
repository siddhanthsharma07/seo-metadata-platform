"use client";
import { Globe } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Alert } from "@/components/ui/misc";
import { api, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = React.useState<"login" | "register">("login");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [name, setName] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api<{ access_token: string }>(`/auth/${mode}`, {
        method: "POST",
        json: mode === "login" ? { email, password } : { email, password, full_name: name },
      });
      setToken(res.access_token);
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white"><Globe className="h-5 w-5" /></div>
          <div>
            <p className="text-sm font-semibold">SEO Metadata Intelligence</p>
            <p className="text-xs text-gray-500">Crawl · Audit · Optimise · Approve</p>
          </div>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <h1 className="text-base font-semibold">{mode === "login" ? "Sign in" : "Create your account"}</h1>
          {error ? <Alert tone="red">{error}</Alert> : null}
          {mode === "register" ? (
            <Field label="Full name"><Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></Field>
          ) : null}
          <Field label="Email"><Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></Field>
          <Field label="Password" hint={mode === "register" ? "At least 8 characters." : undefined}>
            <Input type="password" required minLength={mode === "register" ? 8 : 1} value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"} />
          </Field>
          <Button className="w-full" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</Button>
          <p className="text-center text-xs text-gray-500">
            {mode === "login" ? "No account yet? " : "Already registered? "}
            <button type="button" className="font-medium text-brand-600" onClick={() => setMode(mode === "login" ? "register" : "login")}>
              {mode === "login" ? "Create one" : "Sign in"}
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}
