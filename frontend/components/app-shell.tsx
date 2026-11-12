"use client";
import {
  BarChart3, Bot, CheckSquare, ClipboardCheck, FileDown, FolderKanban, Globe, LogOut, Settings, ShieldCheck, Spline,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useApp } from "@/lib/context";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard", icon: BarChart3 },
  { href: "/projects", label: "Website Projects", icon: FolderKanban },
  { href: "/crawl", label: "Crawl Manager", icon: Spline },
  { href: "/audit", label: "Metadata Audit", icon: ClipboardCheck },
  { href: "/optimise", label: "AI Optimisation", icon: Bot },
  { href: "/brand", label: "Brand SEO Intelligence", icon: ShieldCheck },
  { href: "/approvals", label: "Approval Queue", icon: CheckSquare },
  { href: "/reports", label: "Reports & Exports", icon: FileDown },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, projects, project, setProjectId, logout } = useApp();
  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-gray-200 bg-white lg:flex">
        <div className="flex h-14 items-center gap-2 border-b border-gray-100 px-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-brand-600 text-white">
            <Globe className="h-4 w-4" />
          </div>
          <div className="leading-tight">
            <p className="text-[13px] font-semibold text-gray-900">Metadata Intelligence</p>
            <p className="text-[10px] uppercase tracking-wider text-gray-400">SEO Platform</p>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] font-medium",
                  active ? "bg-brand-50 text-brand-700" : "text-gray-600 hover:bg-gray-50 hover:text-gray-900",
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-gray-100 p-3">
          <p className="truncate text-xs font-medium text-gray-700">{user?.full_name || user?.email}</p>
          <p className="truncate text-[11px] text-gray-400">{user?.email}</p>
          <button onClick={logout} className="mt-2 inline-flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800">
            <LogOut className="h-3.5 w-3.5" /> Sign out
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col lg:pl-60">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-gray-200 bg-white/90 px-4 backdrop-blur lg:px-6">
          <span className="text-xs font-medium text-gray-500">Website</span>
          {projects.length ? (
            <select
              className="h-8 max-w-xs rounded-md border border-gray-300 bg-white px-2 text-sm"
              value={project?.id ?? ""}
              onChange={(e) => setProjectId(Number(e.target.value))}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {p.domain}
                </option>
              ))}
            </select>
          ) : (
            <button className="text-sm text-brand-600" onClick={() => router.push("/projects")}>
              Add your first website →
            </button>
          )}
          <nav className="ml-auto flex gap-1 overflow-x-auto lg:hidden">
            {NAV.map(({ href, icon: Icon, label }) => (
              <Link key={href} href={href} title={label} className="rounded p-1.5 text-gray-500 hover:bg-gray-100">
                <Icon className="h-4 w-4" />
              </Link>
            ))}
          </nav>
        </header>
        <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 lg:px-6">{children}</main>
      </div>
    </div>
  );
}

export function RequireProject({ children }: { children: (p: NonNullable<ReturnType<typeof useApp>["project"]>) => React.ReactNode }) {
  const { project } = useApp();
  if (!project) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-white px-6 py-14 text-center">
        <p className="text-sm font-medium text-gray-800">No website project yet</p>
        <p className="mt-1 text-sm text-gray-500">Create a project for each website you want to audit.</p>
        <Link href="/projects" className="mt-4 inline-block text-sm font-medium text-brand-600">Go to Website Projects →</Link>
      </div>
    );
  }
  return <>{children(project)}</>;
}
