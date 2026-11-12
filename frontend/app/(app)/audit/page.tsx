"use client";
import * as React from "react";
import useSWR from "swr";
import { RequireProject } from "@/components/app-shell";
import { MetadataTable } from "@/components/metadata-table";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { PageHeader, Tabs } from "@/components/ui/misc";
import { fetcher } from "@/lib/api";
import type { Project } from "@/lib/types";
import { shortUrl } from "@/lib/utils";

type DupReport = {
  duplicate_titles: { value: string; page_ids: number[] }[];
  duplicate_descriptions: { value: string; page_ids: number[] }[];
  near_duplicate_titles: { page_ids: number[]; similarity: number; values: string[] }[];
  near_duplicate_descriptions: { page_ids: number[]; similarity: number; values: string[] }[];
  keyword_overlaps: { primary_keyword: string; page_ids: number[]; page_types: string[]; same_intent: boolean; note: string }[];
  urls: Record<string, string>;
};

export default function AuditPage() {
  return <RequireProject>{(p) => <Audit project={p} />}</RequireProject>;
}

function Audit({ project }: { project: Project }) {
  const [tab, setTab] = React.useState("table");
  return (
    <div>
      <PageHeader title="Metadata Audit" description="Every crawled page's existing title and description, scored 0–100 with issues, severity and recommendations. Click a row for full details." />
      <div className="mb-4"><Tabs value={tab} onChange={setTab} tabs={[{ key: "table", label: "All pages" }, { key: "dupes", label: "Duplicates & keyword overlap" }]} /></div>
      {tab === "table" ? <MetadataTable key={project.id} project={project} /> : <Duplicates project={project} />}
    </div>
  );
}

function Duplicates({ project }: { project: Project }) {
  const [source, setSource] = React.useState("existing");
  const { data } = useSWR<DupReport>(`/projects/${project.id}/duplicates?source=${source}`, fetcher);
  const url = (id: number) => shortUrl(data?.urls[String(id)] ?? String(id));
  const Group = ({ title, desc, children, count }: { title: string; desc: string; children: React.ReactNode; count: number }) => (
    <Card><CardHeader><div><CardTitle>{title} <Badge className="ml-1">{count}</Badge></CardTitle><CardDescription>{desc}</CardDescription></div></CardHeader><CardContent className="max-h-96 space-y-3 overflow-y-auto">{count ? children : <p className="text-sm text-emerald-700">None found.</p>}</CardContent></Card>
  );
  return (
    <div className="space-y-4">
      <Select className="w-64" value={source} onChange={(e) => setSource(e.target.value)}><option value="existing">Existing metadata</option><option value="proposed">Proposed metadata</option></Select>
      {data ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Group title="Duplicate titles" desc="Identical titles on indexable pages." count={data.duplicate_titles.length}>
            {data.duplicate_titles.map((g, i) => <div key={i} className="text-sm"><p className="font-medium">“{g.value}”</p><ul className="text-xs text-gray-500">{g.page_ids.map((p) => <li key={p}>{url(p)}</li>)}</ul></div>)}
          </Group>
          <Group title="Duplicate descriptions" desc="Identical descriptions on indexable pages." count={data.duplicate_descriptions.length}>
            {data.duplicate_descriptions.map((g, i) => <div key={i} className="text-sm"><p className="font-medium">“{g.value}”</p><ul className="text-xs text-gray-500">{g.page_ids.map((p) => <li key={p}>{url(p)}</li>)}</ul></div>)}
          </Group>
          <Group title="Near-duplicate titles" desc="≥90% similar." count={data.near_duplicate_titles.length}>
            {data.near_duplicate_titles.map((g, i) => <div key={i} className="text-xs"><Badge tone="amber">{Math.round(g.similarity * 100)}%</Badge>{g.page_ids.map((p, n) => <p key={p}><span className="text-gray-400">{url(p)}</span> — {g.values[n]}</p>)}</div>)}
          </Group>
          <Group title="Near-duplicate descriptions" desc="≥85% similar." count={data.near_duplicate_descriptions.length}>
            {data.near_duplicate_descriptions.map((g, i) => <div key={i} className="text-xs"><Badge tone="amber">{Math.round(g.similarity * 100)}%</Badge>{g.page_ids.map((p, n) => <p key={p}><span className="text-gray-400">{url(p)}</span> — {g.values[n]}</p>)}</div>)}
          </Group>
          <div className="lg:col-span-2">
            <Group title="Pages sharing a primary keyword (review)" desc="Flagged for review only. Shared keywords are not automatically treated as cannibalisation. Requires AI page analysis." count={data.keyword_overlaps.length}>
              {data.keyword_overlaps.map((o, i) => (
                <div key={i} className="text-sm"><p><b>{o.primary_keyword}</b> {o.same_intent ? <Badge tone="amber">same intent</Badge> : <Badge>different intents</Badge>} <span className="text-xs text-gray-400">{o.page_types.join(", ")}</span></p>
                  <ul className="text-xs text-gray-500">{o.page_ids.map((p) => <li key={p}>{url(p)}</li>)}</ul><p className="text-[11px] text-gray-400">{o.note}</p></div>
              ))}
            </Group>
          </div>
        </div>
      ) : <p className="text-sm text-gray-400">Loading…</p>}
    </div>
  );
}
