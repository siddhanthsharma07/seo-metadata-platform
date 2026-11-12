import { AppShell } from "@/components/app-shell";
import { AppProvider } from "@/lib/context";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <AppProvider>
      <AppShell>{children}</AppShell>
    </AppProvider>
  );
}
