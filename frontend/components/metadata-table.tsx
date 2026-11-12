"use client";
import { ArrowDown, ArrowUp, CheckCheck, RefreshCw, Search, X } from "lucide-react";
import * as React from "react";
import useSWR from "swr";
import { PageDetail } from "@/components/page-detail";
import { useToast } from "@/components/toast";
import { Badge, CharCount, ScorePill, severityTone, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox, Input, Select, Textarea } from "@/components/ui/input";
import { Dialog, Empty, Sheet } from "@/components/ui/misc";
import { api, fetcher } from "@/lib/api";
import type { Guidelines, PageRow, Project } from "@/lib/types";
import { cn, shortUrl } from "@/lib/utils";

export type Filters = {
  q?: string; page_type?: string; min_score?: string; max_score?: string; missing?: string; duplicate?: string;
  critical?: boolean; approval?: string; validation?: string; sort?: string; order?: "asc" | "desc";
};

const PAGE_SIZE = 50;

function qs(f: Filters, offset: number) {
  const p = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
  Object.entries(f).forEach(([k, v]) => {
    if (v !== undefined && v !== "" && v !== false) p.set(k, String(v));
  });
  return p.toString();
}

export function MetadataTable({ project, initial = {}, mode = "audit" }: { project: Project; initial?: Filters; mode?: "audit" | "approval" }) {
  const toast = useToast();
  const [filters, setFilters] = React.useState<Filters>({ sort: "id", order: "asc", ...initial });
  const [offset, setOffset] = React.useState(0);
  const [selected, setSelected] = React.useState<Set<number>>(new Set());
  const [openId, setOpenId] = React.useState<number | null>(null);
  const [regenOpen, setRegenOpen] = React.useState(false);
  const [feedback, setFeedback] = React.useState("");
  const [regenFields, setRegenFields] = React.useState("both");
  const key = `/projects/${project.id}/pages?${qs(filters, offset)}`;
  const { data, mutate, isLoading } = useSWR<{ total: number; items: PageRow[] }>(key, fetcher, { keepPreviousData: true });
  const { data: types } = useSWR<string[]>("/meta/page-types", fetcher);
  const { data: g } = useSWR<Guidelines>(`/projects/${project.id}/guidelines`, fetcher);
  const tmin = Number(g?.seo_guidelines.title_min ?? 50), tmax = Number(g?.seo_guidelines.title_max ?? 60);
  const dmin = Number(g?.seo_guidelines.description_min ?? 140), dmax = Number(g?.seo_guidelines.description_max ?? 160);

  const set = (patch: Filters) => {
    setFilters((f) => ({ ...f, ...patch }));
    setOffset(0);
    setSelected(new Set());
  };
  const sortBy = (col: string) => set({ sort: col, order: filters.sort === col && filters.order === "asc" ? "desc" : "asc" });
  const items = data?.items ?? [];
  const allSelected = items.length > 0 && items.every((i) => selected.has(i.id));
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(items.map((i) => i.id)));
  const toggle = (id: number) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  async function bulk(action: string, extra: Record<string, unknown> = {}) {
    try {
      const r = await api<{ done?: number; skipped?: { url: string; reason: string }[]; job_id?: number; queued?: number }>(`/projects/${project.id}/pages/bulk`, {
        method: "POST", json: { page_ids: [...selected], action, ...extra },
      });
      if (r.job_id) toast(`AI job #${r.job_id} queued for ${r.queued} page(s). Track it under AI Optimisation.`, "success");
      else toast(`${r.done} approved${r.skipped?.length ? `, ${r.skipped.length} skipped (e.g. ${r.skipped[0].reason})` : ""}`, r.skipped?.length ? "info" : "success");
      setSelected(new Set());
      mutate();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  const activeFilters = Object.entries(filters).filter(([k, v]) => !["sort", "order"].includes(k) && v);
  const Th = ({ col, children, className }: { col?: string; children: React.ReactNode; className?: string }) => (
    <th className={cn("whitespace-nowrap px-2 py-2 text-left font-medium", col && "cursor-pointer select-none hover:text-gray-800", className)} onClick={col ? () => sortBy(col) : undefined}>
      <span className="inline-flex items-center gap-0.5">{children}{col && filters.sort === col ? (filters.order === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />) : null}</span>
    </th>
  );

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-gray-100 px-4 py-3">
        <div className="relative w-64">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-400" />
          <Input className="pl-8" placeholder="Search URL, title, description, keyword" value={filters.q ?? ""} onChange={(e) => set({ q: e.target.value })} />
        </div>
        <Select className="w-auto min-w-[150px]" value={filters.page_type ?? ""} onChange={(e) => set({ page_type: e.target.value })}>
          <option value="">All page types</option>{(types ?? []).map((t) => <option key={t}>{t}</option>)}
        </Select>
        <Select className="w-auto min-w-[150px]" value={`${filters.min_score ?? ""}-${filters.max_score ?? ""}`} onChange={(e) => { const [a, b] = e.target.value.split("-"); set({ min_score: a, max_score: b }); }}>
          <option value="-">Any existing score</option><option value="0-39">Poor (0–39)</option><option value="40-69">Needs work (40–69)</option><option value="70-84">Good (70–84)</option><option value="85-100">Strong (85–100)</option>
        </Select>
        <Select className="w-auto min-w-[150px]" value={filters.missing ?? ""} onChange={(e) => set({ missing: e.target.value })}>
          <option value="">Missing: any state</option><option value="any">Missing title or desc.</option><option value="title">Missing title</option><option value="description">Missing description</option>
        </Select>
        <Select className="w-auto min-w-[150px]" value={filters.duplicate ?? ""} onChange={(e) => set({ duplicate: e.target.value })}>
          <option value="">Duplicates: any</option><option value="any">Duplicate title or desc.</option><option value="title">Duplicate title</option><option value="description">Duplicate description</option>
        </Select>
        <Select className="w-auto min-w-[150px]" value={filters.approval ?? ""} onChange={(e) => set({ approval: e.target.value })}>
          <option value="">Any approval state</option><option value="pending">Pending review</option><option value="approved">Approved</option><option value="partially_approved">Partially approved</option><option value="rejected">Rejected</option>
        </Select>
        <Select className="w-auto min-w-[150px]" value={filters.validation ?? ""} onChange={(e) => set({ validation: e.target.value })}>
          <option value="">Any validation</option><option value="passed">Validation passed</option><option value="failed">Validation failed</option><option value="needs_review">Needs manual review</option><option value="not_generated">Not generated</option>
        </Select>
        <Checkbox label="Critical issues" checked={!!filters.critical} onChange={(v) => set({ critical: v })} />
        {activeFilters.length ? <Button variant="ghost" size="sm" onClick={() => { setFilters({ sort: "id", order: "asc" }); setOffset(0); }}><X /> Clear</Button> : null}
        <span className="ml-auto text-xs text-gray-500">{data?.total ?? 0} pages</span>
      </div>

      {selected.size ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-brand-100 bg-brand-50 px-4 py-2 text-sm">
          <span className="font-medium text-brand-700">{selected.size} selected</span>
          <Button size="sm" variant="success" onClick={() => bulk("approve_both")}><CheckCheck /> Approve title + description</Button>
          <Button size="sm" variant="secondary" onClick={() => bulk("approve_title")}>Approve titles</Button>
          <Button size="sm" variant="secondary" onClick={() => bulk("approve_description")}>Approve descriptions</Button>
          <Button size="sm" variant="secondary" onClick={() => setRegenOpen(true)}><RefreshCw /> Regenerate</Button>
          <Button size="sm" variant="secondary" onClick={() => bulk("generate")}>Generate missing</Button>
          <Button size="sm" variant="ghost" className="text-red-600" onClick={() => bulk("reject")}>Reject</Button>
        </div>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[1700px] text-[13px]">
          <thead className="sticky top-0 bg-gray-50 text-[11px] uppercase tracking-wide text-gray-500">
            <tr>
              <th className="w-8 px-3 py-2"><input type="checkbox" className="accent-brand-600" checked={allSelected} onChange={toggleAll} aria-label="Select all" /></th>
              <Th col="id">S. No.</Th>
              <Th col="url" className="min-w-[180px]">Page URL</Th>
              <Th col="page_type">Page type</Th>
              <Th col="primary_keyword">Primary keyword</Th>
              <Th className="min-w-[200px]">Existing title</Th>
              <Th col="existing_title_len">Chars</Th>
              <Th className="min-w-[200px]">Proposed title</Th>
              <Th col="proposed_title_len">Chars</Th>
              <Th className="min-w-[240px]">Existing description</Th>
              <Th col="existing_description_len">Chars</Th>
              <Th className="min-w-[240px]">Proposed description</Th>
              <Th col="proposed_description_len">Chars</Th>
              <Th col="existing_score">Existing score</Th>
              <Th col="proposed_score">Proposed score</Th>
              <Th col="issues" className="min-w-[160px]">Issues</Th>
              <Th>Validation</Th>
              <Th>Approval</Th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id} className={cn("cursor-pointer border-t border-gray-100 align-top hover:bg-gray-50/80", selected.has(r.id) && "bg-brand-50/40")} onClick={() => setOpenId(r.id)}>
                <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}><input type="checkbox" className="accent-brand-600" checked={selected.has(r.id)} onChange={() => toggle(r.id)} aria-label="Select row" /></td>
                <td className="px-2 py-2 tabular text-gray-500">{r.s_no}</td>
                <td className="max-w-[220px] break-all px-2 py-2 text-gray-800" title={r.url}>{shortUrl(r.url)}{r.is_indexable === false ? <Badge className="ml-1">noindex</Badge> : null}</td>
                <td className="px-2 py-2"><Badge>{r.page_type}</Badge></td>
                <td className="px-2 py-2 text-gray-700">{r.primary_keyword || <span className="text-gray-400">—</span>}</td>
                <td className="px-2 py-2 text-gray-600">{r.existing_title || <span className="text-red-500">Missing</span>}</td>
                <td className="px-2 py-2"><CharCount n={r.existing_title_len} min={tmin} max={tmax} /></td>
                <td className="px-2 py-2 font-medium text-gray-900">{r.proposed_title || <span className="font-normal text-gray-400">—</span>}{r.title_status === "approved" ? <Badge tone="green" className="ml-1">✓</Badge> : null}</td>
                <td className="px-2 py-2"><CharCount n={r.proposed_title_len} min={tmin} max={tmax} /></td>
                <td className="px-2 py-2 text-gray-600">{r.existing_description || <span className="text-red-500">Missing</span>}</td>
                <td className="px-2 py-2"><CharCount n={r.existing_description_len} min={dmin} max={dmax} /></td>
                <td className="px-2 py-2 text-gray-900">{r.proposed_description || <span className="text-gray-400">—</span>}{r.description_status === "approved" ? <Badge tone="green" className="ml-1">✓</Badge> : null}</td>
                <td className="px-2 py-2"><CharCount n={r.proposed_description_len} min={dmin} max={dmax} /></td>
                <td className="px-2 py-2"><ScorePill score={r.existing_score} /></td>
                <td className="px-2 py-2"><ScorePill score={r.proposed_score} /></td>
                <td className="px-2 py-2"><div className="flex flex-wrap gap-1">{r.issues.slice(0, 3).map((i, n) => <Badge key={n} tone={severityTone[i.severity]}>{i.name}</Badge>)}{r.issue_count > 3 ? <span className="text-[11px] text-gray-400">+{r.issue_count - 3}</span> : null}</div></td>
                <td className="px-2 py-2"><StatusBadge status={r.validation_status} />{r.proposal_source === "manual_edit" ? <div className="mt-1 text-[10px] text-gray-400">manually edited</div> : null}</td>
                <td className="px-2 py-2"><StatusBadge status={r.approval_status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!items.length && !isLoading ? (
          <Empty title={mode === "approval" ? "Nothing waiting for review" : "No pages match"}>
            {mode === "approval" ? "Generate metadata under AI Optimisation; proposals appear here for review." : "Adjust the filters, or crawl the website first."}
          </Empty>
        ) : null}
      </div>
      {data && data.total > PAGE_SIZE ? (
        <div className="flex items-center justify-end gap-2 border-t border-gray-100 px-4 py-2 text-xs text-gray-500">
          {offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
          <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</Button>
          <Button size="sm" variant="secondary" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</Button>
        </div>
      ) : null}

      <Sheet open={openId !== null} onClose={() => { setOpenId(null); mutate(); }} title={<span className="text-sm font-semibold">Page review</span>} width="max-w-5xl">
        {openId !== null ? <PageDetail project={project} pageId={openId} onChanged={() => mutate()} limits={{ tmin, tmax, dmin, dmax }} /> : null}
      </Sheet>
      <Dialog open={regenOpen} onClose={() => setRegenOpen(false)} title={`Regenerate ${selected.size} page(s)`}
        footer={<><Button variant="secondary" onClick={() => setRegenOpen(false)}>Cancel</Button><Button onClick={() => { setRegenOpen(false); bulk("regenerate", { feedback, fields: regenFields }); setFeedback(""); }}>Queue regeneration</Button></>}>
        <div className="space-y-3">
          <Select value={regenFields} onChange={(e) => setRegenFields(e.target.value)}><option value="both">Title and description</option><option value="title">Title only</option><option value="description">Description only</option></Select>
          <Textarea rows={4} placeholder="Optional feedback for the AI, e.g. 'Mention the size range' or 'Less promotional'." value={feedback} onChange={(e) => setFeedback(e.target.value)} />
          <p className="text-xs text-gray-500">Every regenerated proposal goes through validation again and returns to pending review.</p>
        </div>
      </Dialog>
    </Card>
  );
}
