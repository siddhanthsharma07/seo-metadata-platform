"use client";
import { FileSpreadsheet, FileText } from "lucide-react";
import * as React from "react";
import useSWR from "swr";
import { RequireProject } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/misc";
import { download, fetcher } from "@/lib/api";
import type { Project } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

const DESCRIPTIONS: Record<string, string> = {
  complete_audit: "All crawled pages with existing and proposed metadata, scores, issues, validation and approval status. Includes Issues and Crawl Errors sheets.",
  approved: "Only metadata you approved, ready for implementation. Titles and descriptions can be approved independently.",
  needs_improvement: "Pages whose existing metadata scores below 70 or has a high/critical issue.",
  missing: "Pages with a missing title and/or meta description.",
  duplicate: "",
  duplicates: "Exact and near-duplicate titles/descriptions plus pages sharing a primary keyword, for existing and proposed metadata.",
  crawl_errors: "4xx/5xx responses, network failures, robots.txt blocks, redirects, skipped and duplicate URL variants.",
};

export default function ReportsPage() {
  return <RequireProject>{(p) => <Reports project={p} />}</RequireProject>;
}

function Reports({ project }: { project: Project }) {
  const toast = useToast();
  const { data: types } = useSWR<{ key: string; label: string }[]>(`/projects/${project.id}/exports/types`, fetcher);
  const { data: history, mutate } = useSWR<{ id: number; label: string; file_format: string; row_count: number; filename: string; created_at: string }[]>(`/projects/${project.id}/exports/history`, fetcher);
  const [busy, setBusy] = React.useState<string | null>(null);

  async function get(key: string, format: "xlsx" | "csv") {
    setBusy(key + format);
    try {
      await download(`/projects/${project.id}/exports/${key}?format=${format}`);
      mutate();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <PageHeader title="Reports & Exports" description="Excel exports include structured worksheets, filters, frozen headers and readable column widths. Full URLs and metadata are never truncated. CSV is UTF-8 and opens in Excel." />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(types ?? []).map((t) => (
          <Card key={t.key}>
            <CardContent>
              <p className="font-semibold">{t.label}</p>
              <p className="mt-1 min-h-[48px] text-xs text-gray-500">{DESCRIPTIONS[t.key]}</p>
              <div className="mt-3 flex gap-2">
                <Button size="sm" disabled={!!busy} onClick={() => get(t.key, "xlsx")}><FileSpreadsheet /> {busy === t.key + "xlsx" ? "Preparing…" : "Excel"}</Button>
                <Button size="sm" variant="secondary" disabled={!!busy} onClick={() => get(t.key, "csv")}><FileText /> CSV</Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <Card className="mt-6">
        <CardHeader><CardTitle>Export history</CardTitle></CardHeader>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs text-gray-500"><tr><th className="px-5 py-2 font-medium">Report</th><th className="px-3 font-medium">Format</th><th className="px-3 font-medium">Rows</th><th className="px-3 font-medium">File</th><th className="px-3 font-medium">Exported</th></tr></thead>
          <tbody>{(history ?? []).map((h) => <tr key={h.id} className="border-t border-gray-100"><td className="px-5 py-2">{h.label}</td><td className="px-3 uppercase">{h.file_format}</td><td className="px-3 tabular">{h.row_count}</td><td className="px-3 text-xs text-gray-500">{h.filename}</td><td className="px-3 text-xs">{fmtDate(h.created_at)}</td></tr>)}</tbody>
        </table>
        {!history?.length ? <p className="px-5 py-6 text-sm text-gray-400">No exports yet.</p> : null}
      </Card>
    </div>
  );
}
