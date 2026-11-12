"use client";
import Link from "next/link";
import useSWR from "swr";
import { RequireProject } from "@/components/app-shell";
import { StatusBadge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader, Progress, Stat } from "@/components/ui/misc";
import { fetcher } from "@/lib/api";
import { useApp } from "@/lib/context";
import type { Project } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

type Dash = {
  total_discovered: number; crawled: number; http_errors: number; missing_titles: number; missing_descriptions: number;
  duplicate_titles: number; duplicate_descriptions: number; needs_improvement: number; generated: number; approved: number;
  partially_approved: number; rejected: number; pending_review: number; validation: Record<string, number>;
  avg_existing_score: number | null; avg_proposed_score: number | null; page_types: Record<string, number>;
  score_distribution: { existing: number[]; proposed: number[] }; status_counts: Record<string, number>;
  last_crawl: { id: number; status: string; finished_at: string | null; created_at: string } | null;
  last_ai_job: { id: number; kind: string; status: string; processed: number; total: number; failed: number } | null;
};

const BUCKETS = ["0–19", "20–39", "40–59", "60–79", "80–100"];

export default function DashboardPage() {
  return <RequireProject>{(p) => <Dashboard project={p} />}</RequireProject>;
}

function Dashboard({ project }: { project: Project }) {
  const { data: d } = useSWR<Dash>(`/projects/${project.id}/dashboard`, fetcher, { refreshInterval: 5000 });
  const { projects } = useApp();
  const { data: overview } = useSWR<{ id: number; name: string; domain: string; crawled: number; approved: number; avg_existing_score: number | null; last_crawl_status: string | null }[]>(
    projects.length > 1 ? "/overview" : null, fetcher);

  if (!d) return <p className="text-sm text-gray-400">Loading dashboard…</p>;
  const maxBucket = Math.max(1, ...d.score_distribution.existing, ...d.score_distribution.proposed);
  const types = Object.entries(d.page_types).sort((a, b) => b[1] - a[1]);
  return (
    <div>
      <PageHeader title={`${project.name} dashboard`} description={<>{project.base_url} · {project.language}{project.target_country ? ` · ${project.target_country}` : ""}</>} />
      {d.total_discovered === 0 ? (
        <Card className="mb-6">
          <CardContent className="py-8 text-center text-sm text-gray-600">
            No pages yet. Configure <Link className="text-brand-600" href="/brand">Brand SEO Intelligence</Link>, then start a crawl in the{" "}
            <Link className="text-brand-600" href="/crawl">Crawl Manager</Link>.
          </CardContent>
        </Card>
      ) : null}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <Stat label="URLs discovered" value={d.total_discovered} />
        <Stat label="Crawled successfully" value={d.crawled} hint={`${d.http_errors} HTTP errors`} />
        <Stat label="Missing titles" value={d.missing_titles} tone={d.missing_titles ? "red" : undefined} />
        <Stat label="Missing descriptions" value={d.missing_descriptions} tone={d.missing_descriptions ? "red" : undefined} />
        <Stat label="Duplicate titles" value={d.duplicate_titles} tone={d.duplicate_titles ? "amber" : undefined} hint="pages sharing a title" />
        <Stat label="Duplicate descriptions" value={d.duplicate_descriptions} tone={d.duplicate_descriptions ? "amber" : undefined} />
        <Stat label="Needs improvement" value={d.needs_improvement} hint="score < 70 or high/critical issue" tone={d.needs_improvement ? "amber" : undefined} />
        <Stat label="Metadata generated" value={d.generated} hint={`${d.validation.passed ?? 0} passed validation`} />
        <Stat label="Approved" value={d.approved} hint={`${d.partially_approved} partially`} tone="green" />
        <Stat label="Pending review" value={d.pending_review} />
        <Stat label="Avg. existing score" value={d.avg_existing_score ?? "—"} />
        <Stat label="Avg. proposed score" value={d.avg_proposed_score ?? "—"} tone={d.avg_proposed_score ? "green" : undefined} />
      </div>
      <p className="mt-2 text-[11px] text-gray-400">Scores are an internal quality assessment of metadata against best practice and your guidelines. They do not predict rankings or CTR.</p>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><div><CardTitle>Metadata score distribution</CardTitle><CardDescription>Existing vs proposed metadata</CardDescription></div></CardHeader>
          <CardContent className="space-y-2.5">
            {BUCKETS.map((b, i) => (
              <div key={b} className="grid grid-cols-[60px_1fr] items-center gap-3 text-xs">
                <span className="tabular text-gray-500">{b}</span>
                <div className="space-y-1">
                  <div className="flex items-center gap-2"><div className="h-2.5 rounded-sm bg-gray-300" style={{ width: `${(d.score_distribution.existing[i] / maxBucket) * 100}%`, minWidth: 2 }} /><span className="tabular text-gray-500">{d.score_distribution.existing[i]}</span></div>
                  <div className="flex items-center gap-2"><div className="h-2.5 rounded-sm bg-brand-500" style={{ width: `${(d.score_distribution.proposed[i] / maxBucket) * 100}%`, minWidth: 2 }} /><span className="tabular text-gray-500">{d.score_distribution.proposed[i]}</span></div>
                </div>
              </div>
            ))}
            <div className="flex gap-4 pt-1 text-[11px] text-gray-500"><span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-gray-300" />Existing</span><span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-brand-500" />Proposed</span></div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Page types</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {types.length ? types.map(([t, n]) => (
              <div key={t} className="text-xs">
                <div className="mb-1 flex justify-between"><span className="text-gray-700">{t}</span><span className="tabular text-gray-500">{n}</span></div>
                <Progress value={(n / Math.max(1, d.crawled)) * 100} />
              </div>
            )) : <p className="text-xs text-gray-400">No crawled pages yet.</p>}
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Latest crawl</CardTitle><Link href="/crawl" className="text-xs text-brand-600">Crawl Manager →</Link></CardHeader>
          <CardContent className="text-sm">
            {d.last_crawl ? (
              <div className="flex flex-wrap items-center gap-3"><span className="font-medium">#{d.last_crawl.id}</span><StatusBadge status={d.last_crawl.status} /><span className="text-gray-500">{fmtDate(d.last_crawl.finished_at ?? d.last_crawl.created_at)}</span>
                <span className="text-gray-500">{Object.entries(d.status_counts).map(([k, v]) => `${v} ${k}`).join(" · ")}</span></div>
            ) : <span className="text-gray-400">No crawls yet.</span>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Latest AI job</CardTitle><Link href="/optimise" className="text-xs text-brand-600">AI Optimisation →</Link></CardHeader>
          <CardContent className="text-sm">
            {d.last_ai_job ? (
              <div className="space-y-2"><div className="flex items-center gap-3"><span className="font-medium capitalize">{d.last_ai_job.kind}</span><StatusBadge status={d.last_ai_job.status} />
                <span className="tabular text-gray-500">{d.last_ai_job.processed}/{d.last_ai_job.total} pages · {d.last_ai_job.failed} failed</span></div>
                <Progress value={(d.last_ai_job.processed / Math.max(1, d.last_ai_job.total)) * 100} /></div>
            ) : <span className="text-gray-400">No AI jobs yet.</span>}
          </CardContent>
        </Card>
      </div>

      {overview && overview.length > 1 ? (
        <Card className="mt-4">
          <CardHeader><CardTitle>All websites</CardTitle></CardHeader>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs text-gray-500"><tr><th className="px-5 py-2 font-medium">Website</th><th className="px-3 font-medium">Crawled</th><th className="px-3 font-medium">Approved</th><th className="px-3 font-medium">Avg. existing score</th><th className="px-3 font-medium">Last crawl</th></tr></thead>
            <tbody>{overview.map((o) => (
              <tr key={o.id} className="border-t border-gray-100"><td className="px-5 py-2"><span className="font-medium">{o.name}</span> <span className="text-gray-400">{o.domain}</span></td><td className="px-3 tabular">{o.crawled}</td><td className="px-3 tabular">{o.approved}</td><td className="px-3 tabular">{o.avg_existing_score ?? "—"}</td><td className="px-3">{o.last_crawl_status ? <StatusBadge status={o.last_crawl_status} /> : "—"}</td></tr>
            ))}</tbody>
          </table>
        </Card>
      ) : null}
    </div>
  );
}
