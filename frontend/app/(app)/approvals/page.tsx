"use client";
import * as React from "react";
import { RequireProject } from "@/components/app-shell";
import { type Filters, MetadataTable } from "@/components/metadata-table";
import { PageHeader, Tabs } from "@/components/ui/misc";

const VIEWS: Record<string, { label: string; filters: Filters }> = {
  pending: { label: "Pending review", filters: { approval: "pending", validation: "passed" } },
  failed: { label: "Validation failed", filters: { validation: "failed" } },
  manual: { label: "Needs manual input", filters: { validation: "needs_review" } },
  partial: { label: "Partially approved", filters: { approval: "partially_approved" } },
  approved: { label: "Approved", filters: { approval: "approved" } },
  rejected: { label: "Rejected", filters: { approval: "rejected" } },
};

export default function ApprovalsPage() {
  const [view, setView] = React.useState("pending");
  return (
    <RequireProject>
      {(p) => (
        <div>
          <PageHeader title="Approval Queue" description="Review proposed metadata side by side with the existing version. Approve, edit, reject or regenerate with feedback. Nothing is ever published to the live website." />
          <div className="mb-4"><Tabs value={view} onChange={setView} tabs={Object.entries(VIEWS).map(([key, v]) => ({ key, label: v.label }))} /></div>
          <MetadataTable key={`${p.id}-${view}`} project={p} initial={VIEWS[view].filters} mode="approval" />
        </div>
      )}
    </RequireProject>
  );
}
