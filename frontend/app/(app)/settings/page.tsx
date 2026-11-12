"use client";
import * as React from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/misc";
import { api, fetcher } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

type AIConf = {
  default_provider: string;
  providers: { provider: string; models: string[]; default_model: string; env_key_configured: boolean; stored_key: { hint: string; updated_at: string } | null }[];
  pricing_per_million_tokens: Record<string, { input: number; output: number; cache_read: number }>;
};

export default function SettingsPage() {
  const toast = useToast();
  const { data, mutate } = useSWR<AIConf>("/settings/ai", fetcher);
  const { data: usage } = useSWR<{ project: string; calls: number; cost_usd: number; tokens: number }[]>("/settings/usage", fetcher);
  const [keys, setKeys] = React.useState<Record<string, string>>({});

  async function save(provider: string) {
    try {
      await api("/settings/ai/credentials", { method: "PUT", json: { provider, api_key: keys[provider] } });
      toast("API key saved (encrypted at rest)", "success");
      setKeys({ ...keys, [provider]: "" });
      mutate();
    } catch (e) { toast((e as Error).message, "error"); }
  }
  async function remove(provider: string) {
    try { await api(`/settings/ai/credentials/${provider}`, { method: "DELETE" }); mutate(); } catch (e) { toast((e as Error).message, "error"); }
  }

  return (
    <div>
      <PageHeader title="Settings" description="AI providers, API keys and usage. Model, effort, attempts and concurrency are configured per website under Website Projects." />
      <div className="grid gap-4 lg:grid-cols-2">
        {(data?.providers ?? []).map((p) => (
          <Card key={p.provider}>
            <CardHeader><div><CardTitle className="capitalize">{p.provider === "anthropic" ? "Anthropic Claude" : "OpenAI"} {data?.default_provider === p.provider ? <Badge tone="blue" className="ml-1">server default</Badge> : null}</CardTitle>
              <CardDescription>Default model: {p.default_model}. Available: {p.models.join(", ")}</CardDescription></div></CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p>Environment key: {p.env_key_configured ? <Badge tone="green">configured</Badge> : <Badge>not set</Badge>} {p.stored_key ? <>· Your key: <Badge tone="green">{p.stored_key.hint}</Badge> <span className="text-xs text-gray-400">updated {fmtDate(p.stored_key.updated_at)}</span></> : null}</p>
              <div className="flex gap-2">
                <Input type="password" autoComplete="off" placeholder={p.provider === "anthropic" ? "sk-ant-…" : "sk-…"} value={keys[p.provider] ?? ""} onChange={(e) => setKeys({ ...keys, [p.provider]: e.target.value })} />
                <Button onClick={() => save(p.provider)} disabled={(keys[p.provider] ?? "").length < 10}>Save key</Button>
                {p.stored_key ? <Button variant="ghost" onClick={() => remove(p.provider)}>Remove</Button> : null}
              </div>
              <p className="text-xs text-gray-500">A key saved here is encrypted and used for your projects; otherwise the server&apos;s {p.provider === "anthropic" ? "ANTHROPIC_API_KEY" : "OPENAI_API_KEY"} environment variable is used. Keys are never shown again.</p>
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>AI usage by website</CardTitle></CardHeader>
          <table className="w-full text-sm"><thead className="bg-gray-50 text-left text-xs text-gray-500"><tr><th className="px-5 py-2 font-medium">Website</th><th className="px-3 font-medium">Calls</th><th className="px-3 font-medium">Tokens</th><th className="px-3 font-medium">Est. cost</th></tr></thead>
            <tbody>{(usage ?? []).map((u, i) => <tr key={i} className="border-t border-gray-100 tabular"><td className="px-5 py-2">{u.project}</td><td className="px-3">{u.calls}</td><td className="px-3">{u.tokens.toLocaleString()}</td><td className="px-3">${u.cost_usd.toFixed(4)}</td></tr>)}</tbody></table>
        </Card>
        <Card>
          <CardHeader><div><CardTitle>Price table (USD per 1M tokens)</CardTitle><CardDescription>Used for cost estimates. Edit PRICING in backend/app/ai/providers.py when prices change.</CardDescription></div></CardHeader>
          <table className="w-full text-sm"><thead className="bg-gray-50 text-left text-xs text-gray-500"><tr><th className="px-5 py-2 font-medium">Model</th><th className="px-3 font-medium">Input</th><th className="px-3 font-medium">Output</th><th className="px-3 font-medium">Cache read</th></tr></thead>
            <tbody>{Object.entries(data?.pricing_per_million_tokens ?? {}).map(([m, p]) => <tr key={m} className="border-t border-gray-100 tabular"><td className="px-5 py-1.5 text-xs">{m}</td><td className="px-3">${p.input}</td><td className="px-3">${p.output}</td><td className="px-3">${p.cache_read}</td></tr>)}</tbody></table>
        </Card>
      </div>
    </div>
  );
}
