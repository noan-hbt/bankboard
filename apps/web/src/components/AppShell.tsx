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
  return <button onClick={toggle} aria-label="Changer de thème" className="muted rounded-md p-2"><Sun size={16} className="hidden dark:block" /><Moon size={16} className="dark:hidden" /></button>;
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
    <div className="mx-auto min-h-screen max-w-[1400px] px-4 pb-[calc(5rem+env(safe-area-inset-bottom))] sm:pb-8">
      <header className="safe-top sticky top-0 z-30 -mx-4 mb-4 border-b border-[var(--border)] bg-[var(--bg)]/85 backdrop-blur-md">
        <div className="flex h-12 items-center gap-3 px-4">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span aria-hidden className="grid size-6 place-items-center rounded-md bg-[var(--accent)] text-[13px] font-bold text-white">b</span>
            bankboard
          </Link>
          <nav className="ml-4 hidden gap-1 sm:flex" aria-label="Navigation principale">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} aria-current={path === n.href ? "page" : undefined}
                className={`rounded-md px-2.5 py-1 text-sm ${path === n.href ? "bg-[var(--surface-2)] font-medium" : "secondary hover:text-[var(--text-primary)]"}`}>{n.label}</Link>))}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <button onClick={() => setPalette(true)} aria-label="Palette de commandes"
              className="muted flex items-center gap-1 rounded-md border border-[var(--border)] p-2 text-xs sm:px-2 sm:py-1">
              <Command size={14} /><span className="hidden sm:inline">K</span>
            </button>
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main>{children}</main>
      <nav aria-label="Navigation" className="safe-bottom fixed inset-x-0 bottom-0 z-30 border-t border-[var(--border)] bg-[var(--surface-1)]/90 backdrop-blur-md sm:hidden">
        <div className="grid grid-cols-4">
          {NAV.map((n) => {
            const active = path === n.href;
            return (
              <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}
                className={`flex flex-col items-center gap-1 pt-2 pb-1.5 text-[11px] ${active ? "font-medium text-[var(--accent)]" : "muted"}`}>
                <span className={`grid h-7 w-12 place-items-center rounded-full ${active ? "bg-[var(--accent)]/12" : ""}`}>
                  <n.icon size={19} aria-hidden strokeWidth={active ? 2.2 : 1.8} />
                </span>
                {n.label}
              </Link>);
          })}
        </div>
      </nav>
      <CommandPalette open={palette} setOpen={setPalette} />
    </div>
  );
}
