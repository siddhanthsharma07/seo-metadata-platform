"use client";
import { Pause, Play, Square, Upload } from "lucide-react";
import * as React from "react";
import useSWR from "swr";
import { RequireProject } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Alert, PageHeader, Progress, Stat, Tabs } from "@/components/ui/misc";
import { api, fetcher, getToken } from "@/lib/api";
import type { CrawlJob, Project } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

type CrawlPage = { id: number; url: string; status: string; http_status: number | null; error: string | null; source: string; depth: number; final_url: string | null; is_indexable: boolean | null; indexability_reason: string | null; rendered_with_js: boolean; response_ms: number | null; attempts: number };
type Log = { id: number; level: string; message: string; url: string | null; created_at: string };

export default function CrawlPage() {
  return <RequireProject>{(p) => <CrawlManager project={p} />}</RequireProject>;
}

function CrawlManager({ project }: { project: Project }) {
  const toast = useToast();
  const base = `/projects/${project.id}/crawls`;
  const { data: jobs, mutate: refreshJobs } = useSWR<CrawlJob[]>(base, fetcher, { refreshInterval: (d) => (d?.[0] && ["running", "pending", "stopping"].includes(d[0].status) ? 1500 : 10000) });
  const job = jobs?.[0];
  const active = job && ["running", "pending", "stopping", "paused"].includes(job.status);
  const [tab, setTab] = React.useState("results");
  const [manual, setManual] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  async function act(path: string, label: string, json: unknown = {}) {
    setBusy(true);
    try {
      await api(path, { method: "POST", json });
      toast(label, "success");
      await refreshJobs();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function addManual() {
    const urls = manual.split(/\n|,/).map((s) => s.trim()).filter(Boolean);
    if (!urls.length) return;
    try {
      const r = await api<{ added: number; rejected_count: number; rejected: { url: string; reason: string }[] }>(`${base}/urls`, { method: "POST", json: { urls } });
      toast(`${r.added} URL(s) added${r.rejected_count ? `, ${r.rejected_count} rejected (${r.rejected[0]?.reason})` : ""}. They are crawled in the next crawl.`, r.rejected_count ? "info" : "success");
      setManual("");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  async function upload(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(`/api${base}/urls/upload`, { method: "POST", body: fd, headers: { Authorization: `Bearer ${getToken()}` } });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      toast(`${data.added} URL(s) added from ${file.name}${data.rejected_count ? `, ${data.rejected_count} rejected` : ""}`, "success");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  const s = job?.stats ?? {};
  const done = (s.crawled ?? 0) + (s.failed ?? 0);
  const pct = s.discovered ? (done / Math.min(s.discovered, job?.settings?.max_urls ?? s.discovered)) * 100 : 0;
  return (
    <div>
      <PageHeader title="Crawl Manager" description={`Discover and crawl ${project.base_url} via sitemaps, robots.txt, internal links, canonicals and manual URLs.`}
        actions={
          !active ? <Button disabled={busy} onClick={() => act(base, "Crawl started")}><Play /> Start crawl</Button> : (
            <>
              {job.status === "paused" ? <Button disabled={busy} onClick={() => act(`${base}/${job.id}/resume`, "Crawl resumed")}><Play /> Resume</Button>
                : <Button variant="secondary" disabled={busy || job.status === "stopping"} onClick={() => act(`${base}/${job.id}/pause`, "Pausing after the current batch")}><Pause /> Pause</Button>}
              <Button variant="destructive" disabled={busy || job.status === "stopping"} onClick={() => act(`${base}/${job.id}/stop`, "Stopping crawl")}><Square /> Stop</Button>
            </>
          )
        } />
      {job ? (
        <Card className="mb-4">
          <CardContent>
            <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
              <span className="font-semibold">Crawl #{job.id}</span><StatusBadge status={job.status} />
              <span className="text-gray-500">Started {fmtDate(job.started_at ?? job.created_at)}</span>
              {job.finished_at ? <span className="text-gray-500">· Finished {fmtDate(job.finished_at)}</span> : null}
              <span className="ml-auto text-xs text-gray-500">Max {job.settings.max_urls} URLs · depth {job.settings.max_depth} · {job.settings.concurrency} concurrent · {job.settings.delay_ms}ms delay · JS: {job.settings.render_js}</span>
            </div>
            <Progress value={job.status === "completed" ? 100 : pct} />
            {job.error ? <Alert tone="red" className="mt-3">{job.error}</Alert> : null}
            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5">
              <Stat label="Discovered" value={s.discovered ?? 0} />
              <Stat label="Crawled" value={s.crawled ?? 0} tone="green" />
              <Stat label="Failed / errors" value={s.failed ?? 0} tone={s.failed ? "red" : undefined} />
              <Stat label="Queued" value={s.queued ?? 0} />
              <Stat label="Blocked / skipped" value={(s.by_status?.blocked ?? 0) + (s.by_status?.skipped ?? 0) + (s.by_status?.duplicate ?? 0)} hint="robots.txt, limits, URL variants" />
            </div>
          </CardContent>
        </Card>
      ) : (
        <Alert tone="blue" className="mb-4">No crawl yet. Crawling respects robots.txt and never bypasses logins, CAPTCHAs or paywalls.</Alert>
      )}

      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <Card>
          <div className="px-5 pt-3"><Tabs value={tab} onChange={setTab} tabs={[{ key: "results", label: "Crawled URLs" }, { key: "errors", label: "Errors" }, { key: "logs", label: "Crawl log" }, { key: "history", label: "History" }]} /></div>
          {tab === "results" || tab === "errors" ? <ResultsTable project={project} errorsOnly={tab === "errors"} live={!!active} /> : null}
          {tab === "logs" && job ? <LogTable base={`${base}/${job.id}/logs`} live={!!active} /> : null}
          {tab === "history" ? (
            <table className="w-full text-sm"><thead className="bg-gray-50 text-left text-xs text-gray-500"><tr><th className="px-5 py-2 font-medium">Crawl</th><th className="px-3 font-medium">Status</th><th className="px-3 font-medium">Crawled</th><th className="px-3 font-medium">Failed</th><th className="px-3 font-medium">Started</th><th className="px-3 font-medium">Finished</th></tr></thead>
              <tbody>{(jobs ?? []).map((j) => <tr key={j.id} className="border-t border-gray-100"><td className="px-5 py-2">#{j.id}</td><td className="px-3"><StatusBadge status={j.status} /></td><td className="px-3 tabular">{j.stats.crawled ?? 0}</td><td className="px-3 tabular">{j.stats.failed ?? 0}</td><td className="px-3 text-xs">{fmtDate(j.started_at)}</td><td className="px-3 text-xs">{fmtDate(j.finished_at)}</td></tr>)}</tbody></table>
          ) : null}
        </Card>
        <div className="space-y-4">
          <Card>
            <CardHeader><div><CardTitle>Add URLs manually</CardTitle><CardDescription>Paste URLs or paths (one per line). Must belong to {project.domain}.</CardDescription></div></CardHeader>
            <CardContent className="space-y-3">
              <Textarea rows={5} value={manual} onChange={(e) => setManual(e.target.value)} placeholder={`${project.base_url}landing-page\n/products/example`} />
              <Button size="sm" onClick={addManual} disabled={!manual.trim()}>Add URLs</Button>
              <div className="border-t border-gray-100 pt-3">
                <label className="inline-flex cursor-pointer items-center gap-2 text-sm font-medium text-brand-600">
                  <Upload className="h-4 w-4" /> Upload .txt / .csv URL list
                  <input type="file" accept=".txt,.csv,text/plain,text/csv" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
                </label>
              </div>
            </CardContent>
          </Card>
          <SummaryCard project={project} />
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ project }: { project: Project }) {
  const { data } = useSWR<{ by_status: Record<string, number>; by_http_status: Record<string, number>; by_source: Record<string, number> }>(`/projects/${project.id}/crawls/summary/status`, fetcher, { refreshInterval: 5000 });
  if (!data) return null;
  const block = (title: string, obj: Record<string, number>) => (
    <div><p className="mb-1 text-xs font-medium text-gray-500">{title}</p><div className="flex flex-wrap gap-1.5">{Object.entries(obj).map(([k, v]) => <Badge key={k} tone={/^[45]/.test(k) ? "red" : "gray"}>{k}: {v}</Badge>)}</div></div>
  );
  return (
    <Card><CardHeader><CardTitle>URL summary</CardTitle></CardHeader>
      <CardContent className="space-y-3">{block("By status", data.by_status)}{block("By HTTP status", data.by_http_status)}{block("Discovered via", data.by_source)}</CardContent>
    </Card>
  );
}

function ResultsTable({ project, errorsOnly, live }: { project: Project; errorsOnly: boolean; live: boolean }) {
  const [status, setStatus] = React.useState("");
  const [q, setQ] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const st = errorsOnly ? "errors" : status;
  const { data } = useSWR<{ total: number; items: CrawlPage[] }>(`/projects/${project.id}/crawls/results/pages?limit=100&offset=${offset}${st ? `&status=${st}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`, fetcher, { refreshInterval: live ? 3000 : 0 });
  return (
    <div>
      <div className="flex flex-wrap gap-2 px-5 py-3">
        <Input className="max-w-xs" placeholder="Filter URLs…" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
        {!errorsOnly ? (
          <Select className="w-44" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
            <option value="">All statuses</option>{["crawled", "queued", "failed", "blocked", "redirected", "skipped", "duplicate"].map((s) => <option key={s}>{s}</option>)}
          </Select>
        ) : null}
        <span className="ml-auto self-center text-xs text-gray-500">{data?.total ?? 0} URLs</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs text-gray-500"><tr><th className="px-5 py-2 font-medium">URL</th><th className="px-3 font-medium">Status</th><th className="px-3 font-medium">HTTP</th><th className="px-3 font-medium">Indexable</th><th className="px-3 font-medium">Source</th><th className="px-3 font-medium">Depth</th><th className="px-3 font-medium">Details</th></tr></thead>
          <tbody>
            {(data?.items ?? []).map((p) => (
              <tr key={p.id} className="border-t border-gray-100 align-top">
                <td className="max-w-md break-all px-5 py-2 text-xs">{p.url}{p.final_url && p.final_url !== p.url ? <div className="text-gray-400">→ {p.final_url}</div> : null}</td>
                <td className="px-3 py-2"><StatusBadge status={p.status} /></td>
                <td className="px-3 py-2 tabular text-xs">{p.http_status ?? "—"}</td>
                <td className="px-3 py-2 text-xs">{p.is_indexable === null ? "—" : p.is_indexable ? "Yes" : <span className="text-amber-700" title={p.indexability_reason ?? ""}>No</span>}</td>
                <td className="px-3 py-2 text-xs text-gray-500">{p.source}{p.rendered_with_js ? " · JS" : ""}</td>
                <td className="px-3 py-2 tabular text-xs">{p.depth}</td>
                <td className="max-w-xs px-3 py-2 text-xs text-gray-500">{p.error || p.indexability_reason || (p.response_ms ? `${p.response_ms} ms` : "")}{p.attempts > 1 ? ` · ${p.attempts} attempts` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && data.total > 100 ? (
        <div className="flex justify-end gap-2 px-5 py-3">
          <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 100))}>Previous</Button>
          <Button size="sm" variant="secondary" disabled={offset + 100 >= data.total} onClick={() => setOffset(offset + 100)}>Next</Button>
        </div>
      ) : null}
    </div>
  );
}

function LogTable({ base, live }: { base: string; live: boolean }) {
  const [level, setLevel] = React.useState("");
  const { data } = useSWR<Log[]>(`${base}?limit=500${level ? `&level=${level}` : ""}`, fetcher, { refreshInterval: live ? 2000 : 0 });
  return (
    <div>
      <div className="px-5 py-3"><Select className="w-40" value={level} onChange={(e) => setLevel(e.target.value)}><option value="">All levels</option><option value="info">Info</option><option value="warning">Warning</option><option value="error">Error</option></Select></div>
      <div className="max-h-[560px] overflow-y-auto">
        <table className="w-full text-xs">
          <tbody>{(data ?? []).map((l) => (
            <tr key={l.id} className="border-t border-gray-100 align-top">
              <td className="whitespace-nowrap px-5 py-1.5 text-gray-400">{new Date(l.created_at).toLocaleTimeString()}</td>
              <td className="px-2 py-1.5"><Badge tone={l.level === "error" ? "red" : l.level === "warning" ? "amber" : "gray"}>{l.level}</Badge></td>
              <td className="px-2 py-1.5 text-gray-700">{l.message}{l.url ? <div className="break-all text-gray-400">{l.url}</div> : null}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}
