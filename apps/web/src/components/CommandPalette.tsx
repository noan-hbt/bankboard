"use client";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

interface Action { label: string; hint: string; run: (q: string) => void }

export function CommandPalette({ open, setOpen }: { open: boolean; setOpen: (v: boolean) => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(!open); }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);
  useEffect(() => { if (open) { setQ(""); setSel(0); setTimeout(() => input.current?.focus(), 0); } }, [open]);

  const actions: Action[] = useMemo(() => [
    { label: "Poser une question", hint: "Ask your money", run: (t) => router.push(`/ask${t ? `?q=${encodeURIComponent(t)}` : ""}`) },
    { label: "Chercher une transaction", hint: "Explorer", run: (t) => router.push(`/transactions${t ? `?q=${encodeURIComponent(t)}` : ""}`) },
    { label: "Command Center", hint: "Accueil", run: () => router.push("/") },
    { label: "Modifier le dashboard", hint: "Widgets", run: () => router.push("/?edit=1") },
    { label: "Data Health & banques", hint: "Réglages", run: () => router.push("/settings") },
    { label: "Ouvrir une période : ce mois", hint: "Transactions", run: () => {
      const d = new Date(); router.push(`/transactions?start=${d.toISOString().slice(0, 8)}01`);
    } },
  ], [router]);
  const filtered = actions.filter((a) => !q || a.label.toLowerCase().includes(q.toLowerCase()) || a.hint.toLowerCase().includes(q.toLowerCase()));
  const list = filtered.length ? filtered : actions.slice(0, 2);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/40 p-4 pt-[12vh]" onClick={() => setOpen(false)} role="dialog" aria-modal="true" aria-label="Palette de commandes">
      <div className="panel mx-auto max-w-lg overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-[var(--border)] px-3">
          <Search size={16} className="muted" />
          <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setSel(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") setSel((s) => Math.min(s + 1, list.length - 1));
              if (e.key === "ArrowUp") setSel((s) => Math.max(s - 1, 0));
              if (e.key === "Enter") { list[sel]?.run(filtered.length ? "" : q); setOpen(false); }
            }}
            placeholder="Action, transaction ou question…" aria-label="Commande"
            className="h-11 flex-1 bg-transparent text-sm outline-none" />
        </div>
        <ul className="max-h-80 overflow-auto p-1">
          {list.map((a, i) => (
            <li key={a.label}>
              <button onMouseEnter={() => setSel(i)} onClick={() => { a.run(filtered.length ? "" : q); setOpen(false); }}
                className={`flex w-full justify-between rounded px-3 py-2 text-left text-sm ${i === sel ? "bg-[var(--surface-2)]" : ""}`}>
                <span>{filtered.length ? a.label : `${a.label} : « ${q} »`}</span><span className="muted text-xs">{a.hint}</span>
              </button>
            </li>))}
        </ul>
      </div>
    </div>
  );
}
