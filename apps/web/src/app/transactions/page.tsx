"use client";
import { SlidersHorizontal } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Skeleton } from "@/components/ui";
import { api, type Category, type Transaction, useApi } from "@/lib/api";
import { signedEur } from "@/lib/format";

function dayLabel(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
}

const KINDS = ["consumption", "income", "transfer", "investment", "refund", "fee", "debt_payment"];

function Explorer() {
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [category, setCategory] = useState(params.get("category") ?? "");
  const [kind, setKind] = useState("");
  const [start, setStart] = useState(params.get("start") ?? "");
  const [end, setEnd] = useState("");
  const [recurring, setRecurring] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [page, setPage] = useState(0);
  const [showFilters, setShowFilters] = useState(false);
  const qs = new URLSearchParams({ limit: "50", offset: String(page * 50) });
  if (q) qs.set("q", q);
  if (category) qs.set("category", category);
  if (kind) qs.set("kind", kind);
  if (start) qs.set("start", start);
  if (end) qs.set("end", end);
  if (recurring) qs.set("recurring", recurring);
  if (uncertain) qs.set("max_confidence", "0.6");
  const { data, mutate } = useApi<{ items: Transaction[]; total: number; sum_amount: string }>(`/api/transactions?${qs}`);
  const { data: cats } = useApi<Category[]>("/api/categories");

  const recategorize = async (t: Transaction, key: string, all: boolean) => {
    await api(`/api/transactions/${t.id}`, { method: "PATCH", json: { category_key: key, apply_to_merchant: all } });
    await mutate();
  };
  const input = "field";
  const activeFilters = [category, kind, start, end, recurring, uncertain ? "1" : ""].filter(Boolean).length;
  const groups: { date: string; items: Transaction[] }[] = [];
  for (const t of data?.items ?? []) {
    const last = groups.at(-1);
    if (last && last.date === t.booking_date) last.items.push(t);
    else groups.push({ date: t.booking_date, items: [t] });
  }
  return (
    <>
      <div className="mb-3 flex gap-2 md:hidden">
        <input aria-label="Recherche" placeholder="Marchand, libellé…" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} className={`${input} flex-1`} />
        <button onClick={() => setShowFilters(!showFilters)} aria-expanded={showFilters} aria-controls="tx-filters"
          className={`field flex items-center gap-1.5 ${activeFilters ? "border-[var(--accent)] text-[var(--accent)]" : "secondary"}`}>
          <SlidersHorizontal size={16} aria-hidden /><span className="text-sm">Filtres{activeFilters ? ` · ${activeFilters}` : ""}</span>
        </button>
      </div>
      <div id="tx-filters" className={`panel mb-3 grid-cols-2 gap-2 p-3 md:grid md:grid-cols-4 lg:grid-cols-8 ${showFilters ? "grid" : "hidden"}`}>
        <input aria-label="Recherche" placeholder="Marchand, libellé…" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} className={`${input} col-span-2 hidden md:block`} />
        <select aria-label="Catégorie" value={category} onChange={(e) => { setCategory(e.target.value); setPage(0); }} className={input}>
          <option value="">Toutes catégories</option>{(cats ?? []).map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
        </select>
        <select aria-label="Type" value={kind} onChange={(e) => { setKind(e.target.value); setPage(0); }} className={input}>
          <option value="">Tous types</option>{KINDS.map((k) => <option key={k}>{k}</option>)}
        </select>
        <label className="flex flex-col gap-0.5"><span className="label md:sr-only">Du</span>
          <input aria-label="Début" type="date" value={start} onChange={(e) => setStart(e.target.value)} className={input} /></label>
        <label className="flex flex-col gap-0.5"><span className="label md:sr-only">Au</span>
          <input aria-label="Fin" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={input} /></label>
        <select aria-label="Récurrence" value={recurring} onChange={(e) => setRecurring(e.target.value)} className={input}>
          <option value="">Récurrent ou non</option><option value="true">Récurrents</option><option value="false">Ponctuels</option>
        </select>
        <label className="flex items-center gap-2 text-sm secondary"><input type="checkbox" className="size-4" checked={uncertain} onChange={(e) => setUncertain(e.target.checked)} />Incertaines</label>
      </div>
      {!data ? <div className="h-40"><Skeleton /></div> : (
        <div className="panel overflow-clip">
          <div className="flex justify-between border-b border-[var(--border)] px-3 py-2 text-xs secondary sm:px-4">
            <span>{data.total} transactions</span><span className="num">solde net {signedEur(data.sum_amount, true)}</span>
          </div>
          {groups.map((g) => (
            <section key={g.date} aria-label={dayLabel(g.date)}>
              <h3 className="label sticky top-12 z-10 border-b border-[var(--border)] bg-[var(--surface-2)] px-3 py-1.5 sm:px-4">{dayLabel(g.date)}</h3>
              <ul className="divide-y divide-[var(--border)]">
                {g.items.map((t) => (
                  <li key={t.id} className="flex items-center gap-3 px-3 py-2.5 sm:px-4">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[15px] font-medium sm:text-sm">{t.merchant ?? t.label}</div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs muted">
                        <select aria-label="Catégorie" value={t.category_key}
                          onChange={(e) => void recategorize(t, e.target.value, confirm("Appliquer à toutes les transactions de ce marchand ?"))}
                          className="max-w-40 -ml-0.5 truncate rounded bg-transparent py-0.5 secondary">
                          {(cats ?? []).map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
                        </select>
                        {t.status === "pending" && <span className="chip">en attente</span>}
                        {t.is_recurring && <span className="chip">récurrent</span>}
                        {t.is_transfer && <span className="chip">virement interne</span>}
                        <span className="hidden sm:inline">{t.kind}</span>
                        <span className="hidden sm:inline" title="source · confiance">{t.category_source} · {Math.round(Number(t.category_confidence) * 100)} %</span>
                      </div>
                    </div>
                    <span className="num shrink-0 font-medium">{signedEur(t.amount, true)}</span>
                  </li>))}
              </ul>
            </section>))}
          <div className="flex items-center justify-between border-t border-[var(--border)] px-3 py-2 text-sm">
            <button disabled={page === 0} onClick={() => setPage(page - 1)} className="rounded-md px-2 py-1.5 disabled:opacity-40">← Précédent</button>
            <span className="muted text-xs">page {page + 1} / {Math.max(1, Math.ceil(data.total / 50))}</span>
            <button disabled={(page + 1) * 50 >= data.total} onClick={() => setPage(page + 1)} className="rounded-md px-2 py-1.5 disabled:opacity-40">Suivant →</button>
          </div>
        </div>)}
      <p className="muted mt-2 text-xs">Une correction manuelle est toujours prioritaire et n'est jamais écrasée par le pipeline.</p>
    </>
  );
}

export default function Page() {
  return <AppShell><Suspense><Explorer /></Suspense></AppShell>;
}
