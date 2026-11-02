"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Skeleton } from "@/components/ui";
import { api, type Category, type Transaction, useApi } from "@/lib/api";
import { signedEur } from "@/lib/format";

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
  const input = "rounded-md border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm";
  return (
    <>
      <div className="panel mb-3 grid grid-cols-2 gap-2 p-3 md:grid-cols-4 lg:grid-cols-8">
        <input aria-label="Recherche" placeholder="Marchand, libellé…" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} className={`${input} col-span-2`} />
        <select aria-label="Catégorie" value={category} onChange={(e) => { setCategory(e.target.value); setPage(0); }} className={input}>
          <option value="">Toutes catégories</option>{(cats ?? []).map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
        </select>
        <select aria-label="Type" value={kind} onChange={(e) => { setKind(e.target.value); setPage(0); }} className={input}>
          <option value="">Tous types</option>{KINDS.map((k) => <option key={k}>{k}</option>)}
        </select>
        <input aria-label="Début" type="date" value={start} onChange={(e) => setStart(e.target.value)} className={input} />
        <input aria-label="Fin" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={input} />
        <select aria-label="Récurrence" value={recurring} onChange={(e) => setRecurring(e.target.value)} className={input}>
          <option value="">Récurrent ou non</option><option value="true">Récurrents</option><option value="false">Ponctuels</option>
        </select>
        <label className="flex items-center gap-1 text-xs secondary"><input type="checkbox" checked={uncertain} onChange={(e) => setUncertain(e.target.checked)} />Incertaines</label>
      </div>
      {!data ? <div className="h-40"><Skeleton /></div> : (
        <div className="panel overflow-hidden">
          <div className="flex justify-between border-b border-[var(--border)] px-3 py-2 text-xs secondary">
            <span>{data.total} transactions</span><span className="num">solde net {signedEur(data.sum_amount, true)}</span>
          </div>
          <ul className="divide-y divide-[var(--border)]">
            {data.items.map((t) => (
              <li key={t.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                <span className="num muted w-20 shrink-0 text-xs">{t.booking_date}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate">{t.merchant ?? t.label}{t.status === "pending" && <span className="muted text-xs"> · en attente</span>}</div>
                  <div className="flex flex-wrap items-center gap-x-2 text-xs muted">
                    <select aria-label="Catégorie" value={t.category_key}
                      onChange={(e) => void recategorize(t, e.target.value, confirm("Appliquer à toutes les transactions de ce marchand ?"))}
                      className="max-w-40 bg-transparent">
                      {(cats ?? []).map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
                    </select>
                    <span>{t.kind}</span>
                    <span title="source · confiance">{t.category_source} · {Math.round(Number(t.category_confidence) * 100)} %</span>
                    {t.is_recurring && <span>récurrent</span>}{t.is_transfer && <span>virement interne</span>}
                  </div>
                </div>
                <span className="num shrink-0 font-medium">{signedEur(t.amount, true)}</span>
              </li>))}
          </ul>
          <div className="flex justify-between border-t border-[var(--border)] px-3 py-2 text-xs">
            <button disabled={page === 0} onClick={() => setPage(page - 1)} className="disabled:opacity-40">← Précédent</button>
            <span className="muted">page {page + 1} / {Math.max(1, Math.ceil(data.total / 50))}</span>
            <button disabled={(page + 1) * 50 >= data.total} onClick={() => setPage(page + 1)} className="disabled:opacity-40">Suivant →</button>
          </div>
        </div>)}
      <p className="muted mt-2 text-xs">Une correction manuelle est toujours prioritaire et n'est jamais écrasée par le pipeline.</p>
    </>
  );
}

export default function Page() {
  return <AppShell><Suspense><Explorer /></Suspense></AppShell>;
}
