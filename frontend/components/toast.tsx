"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

type Toast = { id: number; message: string; tone: "info" | "error" | "success" };
const Ctx = React.createContext<(message: string, tone?: Toast["tone"]) => void>(() => {});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const push = React.useCallback((message: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 8000 : 4000);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              "rounded-md border px-3 py-2 text-sm shadow-lg",
              t.tone === "error" && "border-red-200 bg-red-50 text-red-800",
              t.tone === "success" && "border-emerald-200 bg-emerald-50 text-emerald-800",
              t.tone === "info" && "border-gray-200 bg-white text-gray-800",
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => React.useContext(Ctx);
