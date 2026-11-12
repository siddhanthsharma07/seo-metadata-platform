"use client";
import { useRouter } from "next/navigation";
import * as React from "react";
import useSWR from "swr";
import { api, fetcher, getToken, setToken } from "./api";
import type { Project, User } from "./types";

type AppCtx = {
  user: User | null;
  projects: Project[];
  project: Project | null;
  setProjectId: (id: number | null) => void;
  refreshProjects: () => Promise<unknown>;
  logout: () => void;
};

const Ctx = React.createContext<AppCtx | null>(null);
const PROJECT_KEY = "smi_project";

export function AppProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = React.useState(false);
  const [projectId, setProjectIdState] = React.useState<number | null>(null);

  React.useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    try {
      const v = localStorage.getItem(PROJECT_KEY);
      if (v) setProjectIdState(Number(v));
    } catch {
      /* ignore */
    }
    setReady(true);
  }, [router]);

  const { data: user } = useSWR<User>(ready ? "/auth/me" : null, fetcher);
  const { data: projects, mutate } = useSWR<Project[]>(ready ? "/projects" : null, fetcher);

  const setProjectId = React.useCallback((id: number | null) => {
    setProjectIdState(id);
    try {
      if (id) localStorage.setItem(PROJECT_KEY, String(id));
      else localStorage.removeItem(PROJECT_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const project = React.useMemo(() => {
    if (!projects?.length) return null;
    return projects.find((p) => p.id === projectId) ?? projects[0];
  }, [projects, projectId]);

  const logout = React.useCallback(() => {
    setToken(null);
    router.replace("/login");
  }, [router]);

  if (!ready || !user || !projects) {
    return <div className="flex h-screen items-center justify-center text-sm text-gray-400">Loading…</div>;
  }
  return (
    <Ctx.Provider value={{ user, projects, project, setProjectId, refreshProjects: mutate, logout }}>{children}</Ctx.Provider>
  );
}

export function useApp() {
  const v = React.useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
}

export { api };
