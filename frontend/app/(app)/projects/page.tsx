"use client";
import { Plus, Trash2 } from "lucide-react";
import * as React from "react";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/input";
import { Dialog, PageHeader } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { useApp } from "@/lib/context";
import type { AISettings, CrawlSettings, Project } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

const DEFAULT_CRAWL: CrawlSettings = {
  max_urls: 500, max_depth: 5, concurrency: 4, delay_ms: 500, max_retries: 2, respect_robots: true, use_sitemaps: true,
  follow_links: true, follow_canonicals: true, include_subdomains: false, allowed_hosts: [], render_js: "auto",
  exclude_patterns: [], include_patterns: [], strip_query_params: [], ignore_query_strings: false,
};
const DEFAULT_AI: AISettings = { provider: null, model: null, effort: "medium", max_attempts: 3, concurrency: 3, min_words: 40, include_non_indexable: false };

type Form = Omit<Project, "id" | "domain" | "created_at" | "updated_at" | "crawl_settings" | "ai_settings"> & { crawl_settings: CrawlSettings; ai_settings: AISettings };

const empty: Form = { name: "", base_url: "", primary_market: "", language: "en", target_country: "", target_audience: "", business_category: "", crawl_settings: DEFAULT_CRAWL, ai_settings: DEFAULT_AI };

const lines = (v: string[]) => (v || []).join("\n");
const toLines = (v: string) => v.split("\n").map((s) => s.trim()).filter(Boolean);

function ProjectForm({ value, onChange, isNew }: { value: Form; onChange: (f: Form) => void; isNew: boolean }) {
  const set = (k: keyof Form, v: unknown) => onChange({ ...value, [k]: v });
  const c = value.crawl_settings;
  const a = value.ai_settings;
  const setC = (k: keyof CrawlSettings, v: unknown) => onChange({ ...value, crawl_settings: { ...c, [k]: v } });
  const setA = (k: keyof AISettings, v: unknown) => onChange({ ...value, ai_settings: { ...a, [k]: v } });
  return (
    <div className="space-y-6">
      <section>
        <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">Website</h4>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Website name *"><Input value={value.name} onChange={(e) => set("name", e.target.value)} required /></Field>
          <Field label="Website URL *" hint={isNew ? "The crawl starts here. Only this domain is crawled." : "The domain cannot be changed after creation."}>
            <Input value={value.base_url} disabled={!isNew} placeholder="https://www.example.com" onChange={(e) => set("base_url", e.target.value)} required />
          </Field>
          <Field label="Primary market"><Input value={value.primary_market} onChange={(e) => set("primary_market", e.target.value)} placeholder="e.g. UK retail" /></Field>
          <Field label="Language" hint="BCP-47 code, e.g. en-GB, de-DE"><Input value={value.language} onChange={(e) => set("language", e.target.value)} /></Field>
          <Field label="Target country"><Input value={value.target_country} onChange={(e) => set("target_country", e.target.value)} /></Field>
          <Field label="Business category"><Input value={value.business_category} onChange={(e) => set("business_category", e.target.value)} placeholder="e.g. Outdoor footwear" /></Field>
          <Field label="Target audience" className="md:col-span-2"><Textarea value={value.target_audience} onChange={(e) => set("target_audience", e.target.value)} /></Field>
        </div>
      </section>
      <section>
        <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">Crawl settings</h4>
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Max URLs"><Input type="number" min={1} max={100000} value={c.max_urls} onChange={(e) => setC("max_urls", Number(e.target.value))} /></Field>
          <Field label="Max depth"><Input type="number" min={0} max={50} value={c.max_depth} onChange={(e) => setC("max_depth", Number(e.target.value))} /></Field>
          <Field label="Concurrency"><Input type="number" min={1} max={32} value={c.concurrency} onChange={(e) => setC("concurrency", Number(e.target.value))} /></Field>
          <Field label="Delay between requests (ms)"><Input type="number" min={0} value={c.delay_ms} onChange={(e) => setC("delay_ms", Number(e.target.value))} /></Field>
          <Field label="Retries"><Input type="number" min={0} max={5} value={c.max_retries} onChange={(e) => setC("max_retries", Number(e.target.value))} /></Field>
          <Field label="JavaScript rendering" hint="Auto renders pages that look client-side rendered (Playwright).">
            <Select value={c.render_js} onChange={(e) => setC("render_js", e.target.value)}><option value="auto">Auto</option><option value="never">Never</option><option value="always">Always</option></Select>
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
          <Checkbox label="Respect robots.txt" checked={c.respect_robots} onChange={(v) => setC("respect_robots", v)} />
          <Checkbox label="Use XML sitemaps" checked={c.use_sitemaps} onChange={(v) => setC("use_sitemaps", v)} />
          <Checkbox label="Follow internal links" checked={c.follow_links} onChange={(v) => setC("follow_links", v)} />
          <Checkbox label="Follow canonical URLs" checked={c.follow_canonicals} onChange={(v) => setC("follow_canonicals", v)} />
          <Checkbox label="Include subdomains" checked={c.include_subdomains} onChange={(v) => setC("include_subdomains", v)} />
          <Checkbox label="Ignore query strings" checked={c.ignore_query_strings} onChange={(v) => setC("ignore_query_strings", v)} />
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <Field label="Exclude URL patterns (regex, one per line)"><Textarea value={lines(c.exclude_patterns)} onChange={(e) => setC("exclude_patterns", toLines(e.target.value))} placeholder={"/cart\n/account/"} /></Field>
          <Field label="Only include patterns (optional)"><Textarea value={lines(c.include_patterns)} onChange={(e) => setC("include_patterns", toLines(e.target.value))} placeholder="/products/" /></Field>
          <Field label="Extra query params to strip"><Textarea value={lines(c.strip_query_params)} onChange={(e) => setC("strip_query_params", toLines(e.target.value))} placeholder={"sort\nview"} /></Field>
        </div>
      </section>
      <section>
        <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">AI settings</h4>
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Provider"><Select value={a.provider ?? ""} onChange={(e) => setA("provider", e.target.value || null)}><option value="">Server default</option><option value="anthropic">Anthropic Claude</option><option value="openai">OpenAI</option></Select></Field>
          <Field label="Model" hint="Blank = provider default"><Input value={a.model ?? ""} onChange={(e) => setA("model", e.target.value || null)} placeholder="claude-opus-5-5" /></Field>
          <Field label="Reasoning effort (Claude)"><Select value={a.effort} onChange={(e) => setA("effort", e.target.value)}>{["low", "medium", "high", "xhigh", "max"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
          <Field label="Max validation attempts"><Input type="number" min={1} max={6} value={a.max_attempts} onChange={(e) => setA("max_attempts", Number(e.target.value))} /></Field>
          <Field label="AI concurrency"><Input type="number" min={1} max={10} value={a.concurrency} onChange={(e) => setA("concurrency", Number(e.target.value))} /></Field>
          <Field label="Min. words for AI" hint="Thinner pages without an H1 are flagged for manual review."><Input type="number" min={0} value={a.min_words} onChange={(e) => setA("min_words", Number(e.target.value))} /></Field>
        </div>
        <Checkbox className="mt-3" label="Also generate metadata for non-indexable pages" checked={a.include_non_indexable} onChange={(v) => setA("include_non_indexable", v)} />
      </section>
    </div>
  );
}

export default function ProjectsPage() {
  const { projects, refreshProjects, setProjectId, project: current } = useApp();
  const toast = useToast();
  const [editing, setEditing] = React.useState<{ id: number | null; form: Form } | null>(null);
  const [confirmDelete, setConfirmDelete] = React.useState<Project | null>(null);
  const [busy, setBusy] = React.useState(false);

  function edit(p: Project | null) {
    setEditing(p ? { id: p.id, form: { ...empty, ...p, crawl_settings: { ...DEFAULT_CRAWL, ...p.crawl_settings }, ai_settings: { ...DEFAULT_AI, ...p.ai_settings } } } : { id: null, form: empty });
  }

  async function save() {
    if (!editing) return;
    setBusy(true);
    try {
      const { form } = editing;
      if (editing.id) {
        const { base_url: _b, ...rest } = form;
        await api(`/projects/${editing.id}`, { method: "PATCH", json: rest });
        toast("Project saved", "success");
      } else {
        const p = await api<Project>("/projects", { method: "POST", json: form });
        setProjectId(p.id);
        toast("Project created. Next: configure Brand SEO Intelligence, then crawl.", "success");
      }
      await refreshProjects();
      setEditing(null);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function remove(p: Project) {
    try {
      await api(`/projects/${p.id}`, { method: "DELETE" });
      toast(`Deleted ${p.name}`, "success");
      if (current?.id === p.id) setProjectId(null);
      await refreshProjects();
    } catch (e) {
      toast((e as Error).message, "error");
    }
    setConfirmDelete(null);
  }

  return (
    <div>
      <PageHeader title="Website Projects" description="Each website has its own isolated context, guidelines, guardrails, crawl data and approvals."
        actions={<Button onClick={() => edit(null)}><Plus /> Add website</Button>} />
      {editing ? (
        <Card className="mb-6">
          <CardHeader><div><CardTitle>{editing.id ? `Edit ${editing.form.name}` : "New website project"}</CardTitle><CardDescription>Settings are saved and reused for future crawls.</CardDescription></div></CardHeader>
          <CardContent>
            <ProjectForm value={editing.form} isNew={!editing.id} onChange={(form) => setEditing({ ...editing, form })} />
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setEditing(null)}>Cancel</Button>
              <Button onClick={save} disabled={busy || !editing.form.name || !editing.form.base_url}>{busy ? "Saving…" : "Save project"}</Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {projects.map((p) => (
          <Card key={p.id} className={current?.id === p.id ? "ring-2 ring-brand-500/30" : ""}>
            <CardContent>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate font-semibold">{p.name}</p>
                  <p className="truncate text-xs text-gray-500">{p.base_url}</p>
                </div>
                <button className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600" onClick={() => setConfirmDelete(p)} aria-label="Delete"><Trash2 className="h-4 w-4" /></button>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-y-1 text-xs">
                <dt className="text-gray-500">Language</dt><dd>{p.language || "—"}</dd>
                <dt className="text-gray-500">Country</dt><dd>{p.target_country || "—"}</dd>
                <dt className="text-gray-500">Category</dt><dd className="truncate">{p.business_category || "—"}</dd>
                <dt className="text-gray-500">Created</dt><dd>{fmtDate(p.created_at)}</dd>
              </dl>
              <div className="mt-4 flex gap-2">
                <Button size="sm" variant={current?.id === p.id ? "secondary" : "default"} onClick={() => setProjectId(p.id)}>{current?.id === p.id ? "Selected" : "Select"}</Button>
                <Button size="sm" variant="secondary" onClick={() => edit(p)}>Edit settings</Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <Dialog open={!!confirmDelete} onClose={() => setConfirmDelete(null)} title="Delete project?"
        footer={<><Button variant="secondary" onClick={() => setConfirmDelete(null)}>Cancel</Button><Button variant="destructive" onClick={() => confirmDelete && remove(confirmDelete)}>Delete permanently</Button></>}>
        <p className="text-sm text-gray-600">This permanently deletes <b>{confirmDelete?.name}</b> with all crawl data, guidelines, recommendations and approval history.</p>
      </Dialog>
    </div>
  );
}
