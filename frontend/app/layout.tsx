import type { Metadata } from "next";
import { ToastProvider } from "@/components/toast";
import "./globals.css";

export const metadata: Metadata = {
  title: "SEO Metadata Intelligence Platform",
  description: "Crawl, audit and optimise meta titles and descriptions with AI, under your brand guardrails.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
