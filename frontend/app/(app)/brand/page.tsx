"use client";
import { History, Plus, Save, Trash2 } from "lucide-react";
import * as React from "react";
import useSWR from "swr";
import { RequireProject } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/input";
import { Alert, PageHeader } from "@/components/ui/misc";
import { api, fetcher } from "@/lib/api";
import type { Guidelines, Project } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

const PAGE_TYPE_RULES = ["Homepage", "Category", "Product", "Blog/Article", "Service", "Landing Page", "Location Page"];
const LIST_FIELDS: [string, string, string][] = [
  ["must_use_words", "Words that must be used", "Must appear in the title or description of every page."],
  ["never_use_words", "Words that must never be used", "Hard block: generation is rejected and approval is blocked."],
  ["avoid_words", "Words that should be avoided", "Soft rule: flagged as a low-severity issue."],
  ["prohibited_phrases", "Phrases that must not appear", "Hard block."],
  ["prohibited_claims", "Claims that must never be made", "Hard block, e.g. 'free shipping', 'best price'."],
  ["competitor_brands", "Competitor brands (never mention)", "Hard block."],
];

const toList = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);
const listText = (v: unknown) => toList(v).join("\n");
const parseList = (s: string) => s.split(/\n|,/).map((x) => x.trim()).filter(Boolean);

export default function BrandPage() {
  return <RequireProject>{(p) => <Brand key={p.id} project={p} />}</RequireProject>;
}

function Brand({ project }: { project: Project }) {
  const toast = useToast();
  const { data: current, mutate } = useSWR<Guidelines>(`/projects/${project.id}/guidelines`, fetcher);
  const { data: versions, mutate: mutateVersions } = useSWR<Guidelines[]>(`/projects/${project.id}/guidelines/versions`, fetcher);
  const [g, setG] = React.useState<Guidelines | null>(null);
  const [lists, setLists] = React.useState<Record<string, string>>({});
  const [note, setNote] = React.useState("");
  const [dirty, setDirty] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [viewing, setViewing] = React.useState<Guidelines | null>(null);

  React.useEffect(() => {
    if (current && !dirty) {
      setG(current);
      setLists(Object.fromEntries(LIST_FIELDS.map(([k]) => [k, listText(current.guardrails[k])])));
    }
  }, [current, dirty]);

  if (!g) return <p className="text-sm text-gray-400">Loading…</p>;
  const upd = (patch: Partial<Guidelines>) => { setG({ ...g, ...patch }); setDirty(true); };
  const brand = (k: string, v: string) => upd({ brand_context: { ...g.brand_context, [k]: v } });
  const seo = (k: string, v: unknown) => upd({ seo_guidelines: { ...g.seo_guidelines, [k]: v } });
  const guard = (k: string, v: unknown) => upd({ guardrails: { ...g.guardrails, [k]: v } });
  const fmt = g.guardrails.formatting ?? {};
  const ptr = g.seo_guidelines.page_type_rules ?? {};

  async function save() {
    if (!g) return;
    setBusy(true);
    try {
      const guardrails = { ...g.guardrails, ...Object.fromEntries(Object.entries(lists).map(([k, v]) => [k, parseList(v)])) };
      const saved = await api<Guidelines>(`/projects/${project.id}/guidelines`, { method: "POST", json: {
        brand_context: g.brand_context, seo_guidelines: { ...g.seo_guidelines, title_min: Number(g.seo_guidelines.title_min), title_max: Number(g.seo_guidelines.title_max), description_min: Number(g.seo_guidelines.description_min), description_max: Number(g.seo_guidelines.description_max) },
        guardrails, keywords: g.keywords.filter((k) => k.keyword.trim()), custom_instructions: g.custom_instructions, change_note: note,
      } });
      toast(`Saved as version ${saved.version}. New AI runs use these guidelines; existing proposals are re-generated when you run generation again.`, "success");
      setDirty(false);
      setNote("");
      await mutate();
      await mutateVersions();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function restore(v: number) {
    try {
      await api(`/projects/${project.id}/guidelines/${v}/restore`, { method: "POST" });
      toast(`Version ${v} restored as a new version`, "success");
      setDirty(false);
      setViewing(null);
      await mutate();
      await mutateVersions();
    } catch (e) { toast((e as Error).message, "error"); }
  }

  return (
    <div>
      <PageHeader title="Brand SEO Intelligence" description={<>Guidelines and guardrails for <b>{project.name}</b> only. They are never applied to any other website. Current: version {current?.version}.</>}
        actions={<><Input className="w-64" placeholder="Change note (optional)" value={note} onChange={(e) => setNote(e.target.value)} /><Button onClick={save} disabled={busy || !dirty}><Save /> {busy ? "Saving…" : "Save new version"}</Button></>} />
      {dirty ? <Alert className="mb-4">You have unsaved changes.</Alert> : null}
      <div className="grid gap-4 xl:grid-cols-[1fr_300px]">
        <div className="space-y-4">
          <Card>
            <CardHeader><div><CardTitle>A. Brand context</CardTitle><CardDescription>How the brand presents itself. Used by every AI stage for this website.</CardDescription></div></CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-2">
              <Field label="Brand name (exact spelling)"><Input value={g.brand_context.brand_name ?? ""} onChange={(e) => brand("brand_name", e.target.value)} /></Field>
              <Field label="Brand category"><Input value={g.brand_context.brand_category ?? ""} onChange={(e) => brand("brand_category", e.target.value)} /></Field>
              <Field label="Target audience"><Input value={g.brand_context.target_audience ?? ""} onChange={(e) => brand("target_audience", e.target.value)} /></Field>
              <Field label="Target geography"><Input value={g.brand_context.target_geography ?? ""} onChange={(e) => brand("target_geography", e.target.value)} /></Field>
              <Field label="Tone of voice"><Input value={g.brand_context.tone_of_voice ?? ""} onChange={(e) => brand("tone_of_voice", e.target.value)} placeholder="e.g. premium, expert, understated" /></Field>
              <Field label="Communication style"><Input value={g.brand_context.communication_style ?? ""} onChange={(e) => brand("communication_style", e.target.value)} placeholder="e.g. concise, benefit-led, no hype" /></Field>
              <Field label="Brand positioning" className="md:col-span-2"><Textarea value={g.brand_context.positioning ?? ""} onChange={(e) => brand("positioning", e.target.value)} /></Field>
              <Field label="Product and service terminology" className="md:col-span-2" hint="Preferred names and terms, e.g. 'use “trail shoes”, not “sneakers”'."><Textarea value={g.brand_context.terminology ?? ""} onChange={(e) => brand("terminology", e.target.value)} /></Field>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><div><CardTitle>B. SEO guidelines</CardTitle><CardDescription>Length targets are optimisation targets, not Google display limits.</CardDescription></div></CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-3 md:grid-cols-4">
                <Field label="Title min chars"><Input type="number" value={String(g.seo_guidelines.title_min ?? 50)} onChange={(e) => seo("title_min", e.target.value)} /></Field>
                <Field label="Title max chars"><Input type="number" value={String(g.seo_guidelines.title_max ?? 60)} onChange={(e) => seo("title_max", e.target.value)} /></Field>
                <Field label="Description min chars"><Input type="number" value={String(g.seo_guidelines.description_min ?? 140)} onChange={(e) => seo("description_min", e.target.value)} /></Field>
                <Field label="Description max chars"><Input type="number" value={String(g.seo_guidelines.description_max ?? 160)} onChange={(e) => seo("description_max", e.target.value)} /></Field>
                <Field label="Brand name placement in titles">
                  <Select value={String(g.seo_guidelines.brand_name_placement ?? "end")} onChange={(e) => seo("brand_name_placement", e.target.value)}>
                    <option value="end">At the end</option><option value="start">At the start</option><option value="auto">Only when it fits</option><option value="homepage_only">Homepage only</option><option value="none">Never</option>
                  </Select>
                </Field>
                <Field label="Brand separator"><Input value={String(g.seo_guidelines.brand_separator ?? " | ")} onChange={(e) => seo("brand_separator", e.target.value)} /></Field>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="Primary keyword rules"><Textarea value={String(g.seo_guidelines.primary_keyword_rules ?? "")} onChange={(e) => seo("primary_keyword_rules", e.target.value)} /></Field>
                <Field label="Secondary keyword rules"><Textarea value={String(g.seo_guidelines.secondary_keyword_rules ?? "")} onChange={(e) => seo("secondary_keyword_rules", e.target.value)} /></Field>
                <Field label="Keyword frequency preferences"><Textarea value={String(g.seo_guidelines.keyword_frequency ?? "")} onChange={(e) => seo("keyword_frequency", e.target.value)} /></Field>
                <Field label="Product naming rules"><Textarea value={String(g.seo_guidelines.product_naming_rules ?? "")} onChange={(e) => seo("product_naming_rules", e.target.value)} placeholder="e.g. '[Model name] [Gender] [Category]'" /></Field>
                <Field label="Internal linking / naming rules" className="md:col-span-2"><Textarea value={String(g.seo_guidelines.internal_linking_rules ?? "")} onChange={(e) => seo("internal_linking_rules", e.target.value)} /></Field>
              </div>
              <h4 className="pt-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Page-type-specific rules</h4>
              <div className="grid gap-3 md:grid-cols-2">
                {PAGE_TYPE_RULES.map((t) => (
                  <Field key={t} label={`${t} rules`}><Textarea rows={2} value={ptr[t] ?? ""} onChange={(e) => seo("page_type_rules", { ...ptr, [t]: e.target.value })} /></Field>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><div><CardTitle>Mandatory keywords & priorities</CardTitle><CardDescription>Used only where they genuinely match a page. Never forced into irrelevant pages.</CardDescription></div>
              <Button size="sm" variant="secondary" onClick={() => upd({ keywords: [...g.keywords, { keyword: "", priority: "medium", applies_to: "" }] })}><Plus /> Add keyword</Button></CardHeader>
            <CardContent className="space-y-2">
              {g.keywords.map((k, i) => (
                <div key={i} className="grid grid-cols-[1fr_120px_1fr_36px] gap-2">
                  <Input placeholder="Keyword" value={k.keyword} onChange={(e) => upd({ keywords: g.keywords.map((x, j) => (j === i ? { ...x, keyword: e.target.value } : x)) })} />
                  <Select value={k.priority} onChange={(e) => upd({ keywords: g.keywords.map((x, j) => (j === i ? { ...x, priority: e.target.value } : x)) })}><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></Select>
                  <Input placeholder="Applies to (URL part or page type, optional)" value={k.applies_to} onChange={(e) => upd({ keywords: g.keywords.map((x, j) => (j === i ? { ...x, applies_to: e.target.value } : x)) })} />
                  <Button size="icon" variant="ghost" onClick={() => upd({ keywords: g.keywords.filter((_, j) => j !== i) })} aria-label="Remove"><Trash2 /></Button>
                </div>
              ))}
              {!g.keywords.length ? <p className="text-xs text-gray-400">No mandatory keywords.</p> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><div><CardTitle>C. Mandatory guardrails</CardTitle><CardDescription>Measurable rules are enforced by code before and after AI generation. Metadata violating them can never be approved. One entry per line.</CardDescription></div></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 md:grid-cols-3">
                {LIST_FIELDS.map(([k, label, hint]) => (
                  <Field key={k} label={label} hint={hint}><Textarea rows={4} value={lists[k] ?? ""} onChange={(e) => { setLists({ ...lists, [k]: e.target.value }); setDirty(true); }} /></Field>
                ))}
              </div>
              <div>
                <p className="mb-2 text-xs font-medium text-gray-700">Formatting restrictions</p>
                <div className="flex flex-wrap gap-x-6 gap-y-2">
                  {[["no_em_dash", "No em/en dashes"], ["no_exclamation", "No exclamation marks"], ["no_emoji", "No emoji"], ["no_all_caps", "No ALL-CAPS words"], ["no_pipes_in_description", "No '|' in descriptions"]].map(([k, l]) => (
                    <Checkbox key={k} label={l} checked={!!fmt[k]} onChange={(v) => guard("formatting", { ...fmt, [k]: v })} />
                  ))}
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <Field label="Other formatting notes"><Textarea value={String(g.guardrails.formatting_notes ?? "")} onChange={(e) => guard("formatting_notes", e.target.value)} /></Field>
                <Field label="Country-specific language rules"><Textarea value={String(g.guardrails.country_language_rules ?? "")} onChange={(e) => guard("country_language_rules", e.target.value)} placeholder="e.g. British English spelling (colour, optimise)" /></Field>
                <Field label="Brand naming restrictions"><Textarea value={String(g.guardrails.brand_naming_restrictions ?? "")} onChange={(e) => guard("brand_naming_restrictions", e.target.value)} /></Field>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><div><CardTitle>D. Custom instructions</CardTitle><CardDescription>Treated as mandatory constraints by the generator and checked by the independent validator.</CardDescription></div></CardHeader>
            <CardContent>
              <Textarea rows={10} value={g.custom_instructions} onChange={(e) => upd({ custom_instructions: e.target.value })}
                placeholder="For this website, maintain a premium brand voice. Avoid the words affordable and luxurious. Use the primary keyword naturally. Do not use em dashes. Do not invent product features. Ensure product page titles follow the approved brand naming convention. Avoid repetitive descriptions." />
            </CardContent>
          </Card>
        </div>

        <Card className="h-fit xl:sticky xl:top-20">
          <CardHeader><CardTitle className="flex items-center gap-2"><History className="h-4 w-4" />Versions</CardTitle></CardHeader>
          <div className="max-h-[70vh] divide-y divide-gray-100 overflow-y-auto">
            {(versions ?? []).map((v) => (
              <div key={v.id} className="px-4 py-2.5 text-sm">
                <div className="flex items-center gap-2"><b>v{v.version}</b>{v.is_active ? <Badge tone="green">active</Badge> : null}<span className="ml-auto text-[11px] text-gray-400">{fmtDate(v.created_at)}</span></div>
                {v.change_note ? <p className="text-xs text-gray-500">{v.change_note}</p> : null}
                <div className="mt-1 flex gap-2">
                  <button className="text-xs text-brand-600" onClick={() => setViewing(viewing?.id === v.id ? null : v)}>{viewing?.id === v.id ? "Hide" : "View"}</button>
                  {!v.is_active ? <button className="text-xs text-brand-600" onClick={() => restore(v.version)}>Restore</button> : null}
                </div>
                {viewing?.id === v.id ? <pre className="mt-2 max-h-64 overflow-auto rounded bg-gray-50 p-2 text-[10px] leading-snug">{JSON.stringify({ brand_context: v.brand_context, seo_guidelines: v.seo_guidelines, guardrails: v.guardrails, keywords: v.keywords, custom_instructions: v.custom_instructions }, null, 1)}</pre> : null}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
