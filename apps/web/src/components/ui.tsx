"use client";
import { HelpCircle, X } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { Explanation, Insight } from "@/lib/api";
import { eur } from "@/lib/format";

export function Panel({ title, action, children, className = "" }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`panel flex h-full min-h-0 flex-col p-3 sm:p-4 ${className}`}>
      {(title || action) && (
        <header className="mb-2 flex items-center justify-between gap-2">
          <h2 className="label">{title}</h2>
          {action}
        </header>
      )}
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, why }: { label: string; value: ReactNode; sub?: ReactNode; why?: Explanation }) {
  return (
    <div className="min-w-0">
      <div className="label flex items-center gap-1">{label}{why && <Why explanation={why} title={label} />}</div>
      <div className="num mt-0.5 truncate text-2xl font-semibold sm:text-[26px]">{value}</div>
      {sub && <div className="secondary mt-0.5 truncate text-xs">{sub}</div>}
    </div>
  );
}

/** "Why?" — shows the exact deterministic decomposition behind a number. */
export function Why({ explanation, title }: { explanation: Explanation; title: string }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  return (
    <>
      <button aria-label={`Pourquoi : ${title}`} onClick={() => setOpen(true)}
        className="muted rounded p-0.5 hover:text-[var(--text-primary)]">
        <HelpCircle size={13} />
      </button>
      {open && createPortal(
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4"
          onClick={() => setOpen(false)} role="dialog" aria-modal="true" aria-label={`Pourquoi : ${title}`}>
          <div className="panel safe-bottom w-full max-w-md rounded-b-none p-4 sm:rounded-b-[10px]"
            onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="font-semibold">Pourquoi — {title}</h3>
              <button aria-label="Fermer" onClick={() => setOpen(false)}><X size={16} /></button>
            </div>
            <table className="w-full text-sm">
              <tbody>
                {explanation.lines.map((l, i) => (
                  <tr key={i} className={l.op === "=" ? "border-t border-[var(--border)] font-semibold" : ""}>
                    <td className="py-1 pr-2 align-top">
                      <span className="muted mr-1 inline-block w-3">{l.op === "·" ? "" : l.op}</span>{l.label}
                      {l.detail && <div className="muted ml-4 text-xs">{l.detail}</div>}
                    </td>
                    <td className="num py-1 text-right align-top whitespace-nowrap">
                      {l.amount !== null ? eur(l.amount, true) : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted mt-3 text-xs">{explanation.method}</p>
            <p className="muted mt-1 text-xs">Confiance : {Math.round(explanation.confidence * 100)} %</p>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}

const PRIORITY: Record<Insight["priority"], { color: string; label: string; icon: string }> = {
  critical: { color: "var(--critical)", label: "Critique", icon: "▲" },
  important: { color: "var(--serious)", label: "Important", icon: "●" },
  useful: { color: "var(--warning)", label: "Utile", icon: "◆" },
  info: { color: "var(--text-muted)", label: "Info", icon: "○" },
};

export function PriorityTag({ p }: { p: Insight["priority"] }) {
  const s = PRIORITY[p];
  return (
    <span className="inline-flex items-center gap-1 text-[11px] secondary">
      <span aria-hidden style={{ color: s.color }}>{s.icon}</span>{s.label}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="muted flex h-full items-center justify-center p-4 text-center text-sm">{children}</div>;
}

export function Skeleton() {
  return <div className="h-full min-h-16 animate-pulse rounded bg-[var(--surface-2)]" />;
}
