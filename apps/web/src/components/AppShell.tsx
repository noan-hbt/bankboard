"use client";
import { Command, LayoutDashboard, List, MessageCircle, Moon, Settings, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { CommandPalette } from "@/components/CommandPalette";

const NAV = [
  { href: "/", label: "Cockpit", icon: LayoutDashboard },
  { href: "/transactions", label: "Transactions", icon: List },
  { href: "/ask", label: "Ask", icon: MessageCircle },
  { href: "/settings", label: "Réglages", icon: Settings },
];

function ThemeToggle() {
  const [theme, setTheme] = useState<string | null>(null);
  useEffect(() => { setTheme(document.documentElement.dataset.theme ?? null); }, []);
  const toggle = () => {
    const dark = theme ? theme === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("bb-theme", next); } catch { /* private mode */ }
    setTheme(next);
  };
  return <button onClick={toggle} aria-label="Changer de thème" className="muted p-2"><Sun size={16} className="hidden dark:block" /><Moon size={16} className="dark:hidden" /></button>;
}

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [palette, setPalette] = useState(false);
  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      void navigator.serviceWorker.register("/sw.js");
    }
  }, []);
  return (
    <div className="mx-auto min-h-screen max-w-[1400px] px-4 pb-24 sm:pb-8">
      <header className="sticky top-0 z-30 -mx-4 mb-3 flex items-center gap-3 border-b border-[var(--border)] bg-[var(--bg)]/90 px-4 py-2 backdrop-blur">
        <Link href="/" className="font-semibold tracking-tight">bankboard</Link>
        <nav className="hidden gap-1 sm:flex" aria-label="Navigation principale">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href}
              className={`rounded px-2.5 py-1 text-sm ${path === n.href ? "bg-[var(--surface-2)]" : "secondary"}`}>{n.label}</Link>))}
        </nav>
        <div className="ml-auto flex items-center">
          <button onClick={() => setPalette(true)} className="muted hidden items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-xs sm:flex">
            <Command size={12} />K
          </button>
          <ThemeToggle />
        </div>
      </header>
      <main>{children}</main>
      <nav aria-label="Navigation" className="safe-bottom fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-[var(--border)] bg-[var(--surface-1)] sm:hidden">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href} className={`flex flex-col items-center gap-0.5 py-2 text-[11px] ${path === n.href ? "" : "muted"}`}>
            <n.icon size={18} aria-hidden />{n.label}
          </Link>))}
      </nav>
      <CommandPalette open={palette} setOpen={setPalette} />
    </div>
  );
}
