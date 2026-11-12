"use client";
import { Check, ExternalLink, Pencil, RefreshCw, X } from "lucide-react";
import * as React from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, CharCount, ScorePill, severityTone, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Alert, Tabs } from "@/components/ui/misc";
import { api, ApiError, fetcher } from "@/lib/api";
import type { AIJob, Issue, Project } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

type Audit = { title_score: number; description_score: number; overall_score: number; breakdown: Record<string, unknown>; issues: Issue[]; ai_evaluated: boolean; ai_summary: string };
type Version = { id: number; version: number; is_current: boolean; title: string; description: string; source: string; validation_status: string; validation_summary: string; attempts: number; rationale: string; feedback: string; model: string; created_at: string };
type Detail = {
  page: { id: number; url: string; status: string; http_status: number; is_indexable: boolean; indexability_reason: string; title_status: string; description_status: string; approved_title: string | null; approved_description: string | null; approved_at: string | null; final_url: string | null; rendered_with_js: boolean; source: string };
  content: { title: string | null; meta_description: string | null; canonical: string | null; meta_robots: string | null; x_robots_tag: string | null; h1: string[]; h2: string[]; headings: { level: number; text: string }[]; lang: string | null; og_title: string | null; og_description: string | null; word_count: number; intro: string; main_content: string; structured_data_types: string[]; entities: { products?: string[]; phrases?: string[]; brand_mentions?: Record<string, number> }; heuristic_page_type: string };
  analysis: null | { page_type: string; primary_topic: string; search_intent: string; target_audience: string; primary_keyword: string; secondary_keywords: string[]; entities: string[]; usps: string[]; key_message: string; positioning: string; content_relevance: string; content_sufficient: boolean; insufficiency_reason: string; model: string };
  existing_audit: Audit | null;
  proposed_audit: Audit | null;
  versions: Version[];
  validations: { id: number; attempt: number; title: string; description: string; passed: boolean; deterministic_issues: Issue[]; ai_review: { summary?: string; skipped?: string; verdict?: string }; created_at: string }[];
  events: { id: number; action: string; field: string; title: string | null; description: string | null; note: string; created_at: string }[];
};

export function PageDetail({ project, pageId, onChanged, limits }: { project: Project; pageId: number; onChanged: () => void; limits: { tmin: number; tmax: number; dmin: number; dmax: number } }) {
  const toast = useToast();
  const base = `/projects/${project.id}/pages/${pageId}`;
  const [jobId, setJobId] = React.useState<number | null>(null);
  const { data: job } = useSWR<AIJob>(jobId ? `/projects/${project.id}/ai/jobs/${jobId}` : null, fetcher, { refreshInterval: 2000 });
  const running = !!job && ["pending", "running"].includes(job.status);
  const { data: d, mutate } = useSWR<Detail>(base, fetcher, { refreshInterval: running ? 2500 : 0 });
  const [tab, setTab] = React.useState("review");
  const [editing, setEditing] = React.useState(false);
  const [title, setTitle] = React.useState("");
  const [desc, setDesc] = React.useState("");
  const [note, setNote] = React.useState("");
  const [fields, setFields] = React.useState("both");
  const [blocked, setBlocked] = React.useState<Issue[] | null>(null);

  React.useEffect(() => {
    if (job && !running) {
      mutate();
      onChanged();
      if (job.status === "failed") toast(job.error || job.log.at(-1)?.m || "Regeneration failed", "error");
      else toast("Regeneration finished", "success");
      setJobId(null);
    }
  }, [job, running, mutate, onChanged, toast]);

  if (!d) return <p className="p-6 text-sm text-gray-400">Loading…</p>;
  const cur = d.versions.find((v) => v.is_current);
  const c = d.content;

  async function action(a: string, extra: Record<string, unknown> = {}) {
    setBlocked(null);
    try {
      const r = await api<{ warnings?: Issue[] }>(`${base}/actions`, { method: "POST", json: { action: a, note, ...extra } });
      toast(a === "edit" ? "Edit saved as a new version" : `Done: ${a.replace(/_/g, " ")}`, "success");
      if (r.warnings?.length) toast(`Approved with warnings: ${r.warnings.map((w) => w.name).join(", ")}`, "info");
      setEditing(false);
      setNote("");
      await mutate();
      onChanged();
    } catch (e) {
      const err = e as ApiError;
      const issues = (err.detail as { issues?: Issue[] })?.issues;
      if (issues) setBlocked(issues);
      toast(err.message, "error");
    }
  }

  async function regenerate() {
    try {
      const r = await api<{ job_id: number }>(`${base}/regenerate`, { method: "POST", json: { fields, feedback: note } });
      setJobId(r.job_id);
      setNote("");
      toast("Regenerating with validation…", "info");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  return (
    <div>
      <div className="border-b border-gray-100 px-5 py-3">
        <a href={d.page.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 break-all text-sm font-medium text-brand-700 hover:underline">{d.page.url}<ExternalLink className="h-3.5 w-3.5" /></a>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
          <Badge>{d.analysis?.page_type ?? c.heuristic_page_type}</Badge>
          <Badge tone={d.page.is_indexable ? "green" : "amber"}>{d.page.is_indexable ? "Indexable" : d.page.indexability_reason}</Badge>
          <Badge>HTTP {d.page.http_status}</Badge>
          <Badge>{c.word_count} words</Badge>
          {d.page.rendered_with_js ? <Badge tone="purple">JS rendered</Badge> : null}
          {cur ? <StatusBadge status={cur.validation_status} /> : <StatusBadge status="not_generated" />}
          <span className="text-gray-400">Title: <StatusBadge status={d.page.title_status} /> Description: <StatusBadge status={d.page.description_status} /></span>
        </div>
      </div>
      <div className="px-5"><Tabs value={tab} onChange={setTab} tabs={[{ key: "review", label: "Review & approve" }, { key: "audit", label: "Audit findings" }, { key: "context", label: "Page context" }, { key: "history", label: `History (${d.versions.length})` }]} /></div>

      {tab === "review" ? (
        <div className="space-y-4 p-5">
          {running ? <Alert tone="blue">AI is regenerating and validating this page… ({job?.status})</Alert> : null}
          {d.analysis && !d.analysis.content_sufficient ? <Alert>Insufficient content for reliable AI metadata: {d.analysis.insufficiency_reason} Please write it manually.</Alert> : null}
          {cur?.validation_status === "failed" ? <Alert tone="red">{cur.validation_summary}</Alert> : null}
          {blocked ? <Alert tone="red"><b>Approval blocked by mandatory guardrails:</b><ul className="mt-1 list-disc pl-5">{blocked.map((i, n) => <li key={n}>{i.name}: {i.explanation}</li>)}</ul></Alert> : null}

          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-md border border-gray-200 bg-gray-50/60 p-4">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Existing <span className="ml-1 normal-case"><ScorePill score={d.existing_audit?.overall_score} /></span></p>
              <p className="text-xs text-gray-500">Title <CharCount n={(c.title ?? "").length} min={limits.tmin} max={limits.tmax} /></p>
              <p className="mb-3 text-sm text-gray-800">{c.title || <span className="text-red-500">Missing</span>}</p>
              <p className="text-xs text-gray-500">Description <CharCount n={(c.meta_description ?? "").length} min={limits.dmin} max={limits.dmax} /></p>
              <p className="text-sm text-gray-700">{c.meta_description || <span className="text-red-500">Missing</span>}</p>
            </div>
            <div className="rounded-md border border-brand-100 bg-white p-4">
              <p className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-brand-700">
                <span>Proposed {cur ? <span className="ml-1 normal-case text-gray-500">v{cur.version} · {cur.source.replace(/_/g, " ")}</span> : null} <span className="ml-1 normal-case"><ScorePill score={d.proposed_audit?.overall_score} /></span></span>
                {cur && !editing ? <button className="inline-flex items-center gap-1 normal-case text-gray-500 hover:text-gray-800" onClick={() => { setTitle(cur.title); setDesc(cur.description); setEditing(true); }}><Pencil className="h-3.5 w-3.5" />Edit</button> : null}
              </p>
              {editing || !cur ? (
                <div className="space-y-3">
                  <Field label={`Title (${title.length} chars, target ${limits.tmin}–${limits.tmax})`}><Input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
                  <Field label={`Description (${desc.length} chars, target ${limits.dmin}–${limits.dmax})`}><Textarea rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
                  <div className="flex gap-2"><Button size="sm" onClick={() => action("edit", { title, description: desc })} disabled={!title && !desc}>Save edit</Button>{cur ? <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button> : null}</div>
                  <p className="text-[11px] text-gray-500">Manual edits are checked against your guardrails and saved as a new version.</p>
                </div>
              ) : (
                <>
                  <p className="text-xs text-gray-500">Title <CharCount n={cur.title.length} min={limits.tmin} max={limits.tmax} /></p>
                  <p className="mb-3 text-sm font-medium text-gray-900">{cur.title || "—"}</p>
                  <p className="text-xs text-gray-500">Description <CharCount n={cur.description.length} min={limits.dmin} max={limits.dmax} /></p>
                  <p className="text-sm text-gray-800">{cur.description || "—"}</p>
                  {cur.rationale ? <p className="mt-3 border-t border-gray-100 pt-2 text-xs text-gray-500"><b>AI rationale:</b> {cur.rationale}</p> : null}
                  {cur.validation_summary && cur.validation_status === "passed" ? <p className="mt-1 text-xs text-emerald-700"><b>Validation:</b> {cur.validation_summary}</p> : null}
                </>
              )}
            </div>
          </div>

          <SerpPreview url={d.page.url} title={cur?.title || c.title || ""} desc={cur?.description || c.meta_description || ""} />

          <div className="rounded-md border border-gray-200 p-4">
            <Field label="Note / feedback for regeneration (optional)"><Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Mention free returns only if stated on the page; keep it less promotional." /></Field>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="success" size="sm" disabled={!cur} onClick={() => action("approve_both")}><Check /> Approve both</Button>
              <Button variant="secondary" size="sm" disabled={!cur} onClick={() => action("approve_title")}>Approve title only</Button>
              <Button variant="secondary" size="sm" disabled={!cur} onClick={() => action("approve_description")}>Approve description only</Button>
              <Button variant="ghost" size="sm" className="text-red-600" onClick={() => action("reject")}><X /> Reject</Button>
              <span className="mx-1 w-px bg-gray-200" />
              <Select className="h-8 w-44 text-xs" value={fields} onChange={(e) => setFields(e.target.value)}><option value="both">Regenerate both</option><option value="title">Regenerate title</option><option value="description">Regenerate description</option></Select>
              <Button variant="secondary" size="sm" disabled={running} onClick={regenerate}><RefreshCw className={running ? "animate-spin" : ""} /> Regenerate</Button>
            </div>
            {d.page.approved_at ? <p className="mt-3 text-xs text-gray-500">Last approval {fmtDate(d.page.approved_at)}. Approved title: <b>{d.page.approved_title ?? "—"}</b></p> : null}
          </div>
        </div>
      ) : null}

      {tab === "audit" ? (
        <div className="grid gap-4 p-5 lg:grid-cols-2">
          {([["Existing metadata", d.existing_audit], ["Proposed metadata", d.proposed_audit]] as const).map(([label, a]) => (
            <div key={label} className="rounded-md border border-gray-200">
              <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2"><span className="text-sm font-semibold">{label}</span>
                {a ? <span className="flex gap-3 text-xs">Title <ScorePill score={a.title_score} /> Desc. <ScorePill score={a.description_score} /> Overall <ScorePill score={a.overall_score} /></span> : null}</div>
              {a ? (
                <div className="space-y-3 p-4">
                  {a.ai_summary ? <p className="text-xs text-gray-600"><b>AI assessment:</b> {a.ai_summary}</p> : null}
                  <Breakdown b={a.breakdown} />
                  {a.issues.length ? a.issues.map((i, n) => (
                    <div key={n} className="rounded border border-gray-100 p-2.5">
                      <div className="flex flex-wrap items-center gap-1.5"><Badge tone={severityTone[i.severity]}>{i.severity}</Badge><span className="text-sm font-medium">{i.name}</span><span className="text-[11px] text-gray-400">{i.field} · {i.source === "ai" ? "AI review" : "rule check"}</span></div>
                      {i.explanation ? <p className="mt-1 text-xs text-gray-600">{i.explanation}</p> : null}
                      {i.recommendation ? <p className="mt-0.5 text-xs text-emerald-700">→ {i.recommendation}</p> : null}
                    </div>
                  )) : <p className="text-sm text-emerald-700">No issues found.</p>}
                </div>
              ) : <p className="p-4 text-sm text-gray-400">Not available yet.</p>}
            </div>
          ))}
        </div>
      ) : null}

      {tab === "context" ? (
        <div className="grid gap-4 p-5 lg:grid-cols-2">
          <div className="space-y-2 text-sm">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">AI page understanding</h4>
            {d.analysis ? (
              <dl className="grid grid-cols-[130px_1fr] gap-x-3 gap-y-1.5 text-xs">
                <dt className="text-gray-500">Primary topic</dt><dd>{d.analysis.primary_topic}</dd>
                <dt className="text-gray-500">Search intent</dt><dd className="capitalize">{d.analysis.search_intent}</dd>
                <dt className="text-gray-500">Audience</dt><dd>{d.analysis.target_audience}</dd>
                <dt className="text-gray-500">Primary keyword</dt><dd className="font-medium">{d.analysis.primary_keyword}</dd>
                <dt className="text-gray-500">Secondary</dt><dd>{d.analysis.secondary_keywords.join(", ") || "—"}</dd>
                <dt className="text-gray-500">Entities</dt><dd>{d.analysis.entities.join(", ") || "—"}</dd>
                <dt className="text-gray-500">USPs (evidenced)</dt><dd>{d.analysis.usps.join("; ") || "—"}</dd>
                <dt className="text-gray-500">Key message</dt><dd>{d.analysis.key_message}</dd>
                <dt className="text-gray-500">Positioning</dt><dd>{d.analysis.positioning}</dd>
                <dt className="text-gray-500">Content focus</dt><dd>{d.analysis.content_relevance}</dd>
                <dt className="text-gray-500">Model</dt><dd className="text-gray-400">{d.analysis.model}</dd>
              </dl>
            ) : <p className="text-xs text-gray-400">Run AI analysis under AI Optimisation.</p>}
            <h4 className="pt-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Extracted SEO metadata</h4>
            <dl className="grid grid-cols-[130px_1fr] gap-x-3 gap-y-1.5 break-words text-xs">
              <dt className="text-gray-500">Canonical</dt><dd className="break-all">{c.canonical || "—"}</dd>
              <dt className="text-gray-500">Meta robots</dt><dd>{c.meta_robots || "—"}{c.x_robots_tag ? ` · X-Robots: ${c.x_robots_tag}` : ""}</dd>
              <dt className="text-gray-500">Language</dt><dd>{c.lang || "—"}</dd>
              <dt className="text-gray-500">OG title</dt><dd>{c.og_title || "—"}</dd>
              <dt className="text-gray-500">OG description</dt><dd>{c.og_description || "—"}</dd>
              <dt className="text-gray-500">H1</dt><dd>{c.h1.join(" | ") || "—"}</dd>
              <dt className="text-gray-500">Structured data</dt><dd>{c.structured_data_types.join(", ") || "—"}</dd>
              <dt className="text-gray-500">Products</dt><dd>{c.entities?.products?.join(", ") || "—"}</dd>
            </dl>
            <h4 className="pt-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Headings</h4>
            <ul className="space-y-0.5 text-xs">{c.headings.slice(0, 40).map((h, i) => <li key={i} style={{ paddingLeft: (h.level - 1) * 12 }}><span className="text-gray-400">H{h.level}</span> {h.text}</li>)}</ul>
          </div>
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Main content (boilerplate removed)</h4>
            <div className="max-h-[640px] overflow-y-auto whitespace-pre-line rounded-md border border-gray-200 bg-gray-50 p-3 text-xs leading-relaxed text-gray-700">{c.main_content || "No extractable content."}</div>
          </div>
        </div>
      ) : null}

      {tab === "history" ? (
        <div className="space-y-5 p-5">
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Metadata versions</h4>
            <div className="space-y-2">{d.versions.map((v) => (
              <div key={v.id} className="rounded-md border border-gray-200 p-3 text-sm">
                <div className="mb-1 flex flex-wrap items-center gap-2 text-xs"><b>v{v.version}</b>{v.is_current ? <Badge tone="blue">current</Badge> : null}<Badge>{v.source.replace(/_/g, " ")}</Badge><StatusBadge status={v.validation_status} /><span className="text-gray-400">{fmtDate(v.created_at)} · {v.attempts} attempt(s) {v.model ? `· ${v.model}` : ""}</span></div>
                <p className="font-medium">{v.title}</p><p className="text-gray-600">{v.description}</p>
                {v.feedback ? <p className="mt-1 text-xs text-gray-500">Feedback: {v.feedback}</p> : null}
              </div>
            ))}{!d.versions.length ? <p className="text-xs text-gray-400">No versions yet.</p> : null}</div>
          </div>
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Validation attempts</h4>
            <div className="space-y-2">{d.validations.map((v) => (
              <div key={v.id} className="rounded-md border border-gray-200 p-3 text-xs">
                <div className="mb-1 flex items-center gap-2"><b>Attempt {v.attempt}</b><StatusBadge status={v.passed ? "passed" : "failed"} /><span className="text-gray-400">{fmtDate(v.created_at)}</span></div>
                <p className="text-gray-800">{v.title}</p><p className="text-gray-500">{v.description}</p>
                {v.deterministic_issues.filter((i) => i.blocking).map((i, n) => <p key={n} className="text-red-600">✕ {i.name}: {i.explanation}</p>)}
                {v.ai_review?.summary ? <p className="mt-1 text-gray-600">AI reviewer: {v.ai_review.summary}</p> : null}
                {v.ai_review?.skipped ? <p className="mt-1 text-gray-400">{v.ai_review.skipped}</p> : null}
              </div>
            ))}{!d.validations.length ? <p className="text-xs text-gray-400">No validations yet.</p> : null}</div>
          </div>
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Approval log</h4>
            <ul className="space-y-1 text-xs">{d.events.map((e) => <li key={e.id}><span className="text-gray-400">{fmtDate(e.created_at)}</span> · <b className="capitalize">{e.action}</b> ({e.field}){e.title ? ` — "${e.title}"` : ""}{e.note ? ` · ${e.note}` : ""}</li>)}</ul>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Breakdown({ b }: { b: Record<string, unknown> }) {
  const parts = (["title", "description"] as const).map((k) => [k, b?.[k] as Record<string, number | boolean> | undefined] as const);
  return (
    <div className="grid grid-cols-2 gap-3 text-[11px]">
      {parts.map(([k, v]) => (
        <div key={k}>
          <p className="mb-1 font-medium capitalize text-gray-600">{k} score components</p>
          {v && !("missing" in v) ? Object.entries(v).map(([name, pts]) => <div key={name} className="flex justify-between text-gray-500"><span className="capitalize">{name.replace(/_/g, " ")}</span><span className="tabular">{String(pts)}</span></div>) : <p className="text-red-500">Missing (0)</p>}
        </div>
      ))}
      <p className="col-span-2 text-gray-400">Relevance measured by: {String(b?.relevance_source ?? "heuristic")}</p>
    </div>
  );
}

function SerpPreview({ url, title, desc }: { url: string; title: string; desc: string }) {
  let host = url;
  let path = "";
  try { const u = new URL(url); host = u.hostname; path = u.pathname.split("/").filter(Boolean).join(" › "); } catch { /* ignore */ }
  return (
    <div className="rounded-md border border-gray-200 p-4">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Approximate search result preview</p>
      <p className="text-xs text-gray-600">{host}{path ? ` › ${path}` : ""}</p>
      <p className="truncate text-[18px] leading-snug text-[#1a0dab]" style={{ maxWidth: 600 }}>{title || "(no title)"}</p>
      <p className="line-clamp-2 text-[13px] text-gray-600" style={{ maxWidth: 600 }}>{desc || "(no description)"}</p>
    </div>
  );
}
