"use client";
import { Bot, Brain, Sparkles } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import useSWR from "swr";
import { RequireProject } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox, Select } from "@/components/ui/input";
import { Alert, PageHeader, Progress } from "@/components/ui/misc";
import { api, fetcher } from "@/lib/api";
import type { AIJob, Project } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

type Status = { provider: string; model: string | null; configured: boolean; message: string; settings: Record<string, unknown> };
type Usage = { items: { stage: string; model: string; calls: number; input_tokens: number; output_tokens: number; cache_read_tokens: number; cost_usd: number; failed_calls: number }[]; total_cost_usd: number; total_calls: number; total_tokens: number };

export default function OptimisePage() {
  return <RequireProject>{(p) => <Optimise project={p} />}</RequireProject>;
}

function Optimise({ project }: { project: Project }) {
  const toast = useToast();
  const base = `/projects/${project.id}/ai`;
  const { data: status } = useSWR<Status>(`${base}/status`, fetcher);
  const { data: jobs, mutate } = useSWR<AIJob[]>(`${base}/jobs`, fetcher, { refreshInterval: (d) => (d?.some((j) => ["pending", "running"].includes(j.status)) ? 2000 : 15000) });
  const { data: usage } = useSWR<Usage>(`${base}/usage`, fetcher, { refreshInterval: 10000 });
  const [force, setForce] = React.useState(false);
  const [includeNI, setIncludeNI] = React.useState(false);
  const [fields, setFields] = React.useState("both");
  const running = jobs?.find((j) => ["pending", "running"].includes(j.status));

  async function start(kind: "analyze" | "generate") {
    try {
      await api(`${base}/jobs`, { method: "POST", json: { kind, force, include_non_indexable: includeNI, fields } });
      toast(kind === "analyze" ? "AI analysis started" : "Metadata generation started", "success");
      mutate();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }
  async function cancel(id: number) {
    try { await api(`${base}/jobs/${id}/cancel`, { method: "POST" }); mutate(); } catch (e) { toast((e as Error).message, "error"); }
  }

  return (
    <div>
      <PageHeader title="AI Optimisation" description="Separate AI stages: page understanding → existing-metadata evaluation → generation → independent validation → regeneration on failure." />
      {status && !status.configured ? (
        <Alert tone="red" className="mb-4"><b>AI provider not configured.</b> {status.message} <Link href="/settings" className="font-medium underline">Open Settings</Link></Alert>
      ) : status ? (
        <Alert tone="blue" className="mb-4">Using <b>{status.provider}</b>{status.model ? ` · ${status.model}` : " · default model"} · up to {String(status.settings.max_attempts)} validation attempts · {String(status.settings.concurrency)} pages in parallel. Change per-website settings under Website Projects.</Alert>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><Brain className="h-4 w-4 text-brand-600" />1. Understand pages & audit existing metadata</CardTitle><CardDescription>Identifies page type, intent, keywords, entities and evidenced USPs, then scores existing metadata semantically.</CardDescription></div></CardHeader>
          <CardContent><Button disabled={!status?.configured || !!running} onClick={() => start("analyze")}><Bot /> Run AI analysis</Button></CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-brand-600" />2. Generate & validate new metadata</CardTitle><CardDescription>Runs analysis where needed, generates page-specific metadata under your guardrails, validates it (rules + independent AI reviewer) and regenerates on failure.</CardDescription></div></CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-4">
              <Select className="w-48" value={fields} onChange={(e) => setFields(e.target.value)}><option value="both">Titles and descriptions</option><option value="title">Titles only</option><option value="description">Descriptions only</option></Select>
              <Checkbox label="Force reprocessing (ignore cache)" checked={force} onChange={setForce} />
              <Checkbox label="Include non-indexable pages" checked={includeNI} onChange={setIncludeNI} />
            </div>
            <Button disabled={!status?.configured || !!running} onClick={() => start("generate")}><Sparkles /> Generate metadata</Button>
            <p className="text-xs text-gray-500">Pages whose content and guidelines haven't changed are skipped automatically (no duplicate AI cost). Pages with insufficient content are flagged for manual input instead of guessed.</p>
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader><CardTitle>AI jobs</CardTitle></CardHeader>
        <div className="divide-y divide-gray-100">
          {(jobs ?? []).map((j) => (
            <div key={j.id} className="px-5 py-3">
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span className="font-medium">#{j.id} · <span className="capitalize">{j.kind}</span></span><StatusBadge status={j.status} />
                <span className="tabular text-xs text-gray-500">{j.processed}/{j.total} processed · {j.failed} failed</span>
                <span className="text-xs text-gray-400">{fmtDate(j.created_at)}</span>
                {["pending", "running"].includes(j.status) ? <Button size="sm" variant="ghost" className="ml-auto text-red-600" onClick={() => cancel(j.id)}>Cancel</Button> : null}
              </div>
              {["pending", "running"].includes(j.status) ? <Progress className="mt-2" value={(j.processed / Math.max(1, j.total)) * 100} /> : null}
              {j.error ? <Alert tone="red" className="mt-2">{j.error}</Alert> : null}
              {j.log.length ? <details className="mt-1 text-xs text-gray-500"><summary className="cursor-pointer">Log ({j.log.length})</summary><ul className="mt-1 max-h-48 overflow-y-auto">{j.log.map((l, i) => <li key={i}><span className="text-gray-400">{new Date(l.t).toLocaleTimeString()}</span> {l.m}</li>)}</ul></details> : null}
            </div>
          ))}
          {!jobs?.length ? <p className="px-5 py-6 text-sm text-gray-400">No AI jobs yet.</p> : null}
        </div>
      </Card>

      <Card className="mt-4">
        <CardHeader><div><CardTitle>API usage & cost</CardTitle><CardDescription>Estimated from token usage and the price table in Settings.</CardDescription></div>
          {usage ? <div className="text-right text-sm"><p className="font-semibold tabular">${usage.total_cost_usd.toFixed(4)}</p><p className="text-xs text-gray-500">{usage.total_calls} calls · {usage.total_tokens.toLocaleString()} tokens</p></div> : null}</CardHeader>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs text-gray-500"><tr><th className="px-5 py-2 font-medium">Stage</th><th className="px-3 font-medium">Model</th><th className="px-3 font-medium">Calls</th><th className="px-3 font-medium">Failed</th><th className="px-3 font-medium">Input</th><th className="px-3 font-medium">Cached</th><th className="px-3 font-medium">Output</th><th className="px-3 font-medium">Cost</th></tr></thead>
          <tbody>{(usage?.items ?? []).map((u, i) => <tr key={i} className="border-t border-gray-100 tabular"><td className="px-5 py-2 capitalize">{u.stage}</td><td className="px-3 text-xs">{u.model}</td><td className="px-3">{u.calls}</td><td className="px-3">{u.failed_calls}</td><td className="px-3">{u.input_tokens.toLocaleString()}</td><td className="px-3">{u.cache_read_tokens.toLocaleString()}</td><td className="px-3">{u.output_tokens.toLocaleString()}</td><td className="px-3">${u.cost_usd.toFixed(4)}</td></tr>)}</tbody>
        </table>
      </Card>
    </div>
  );
}
