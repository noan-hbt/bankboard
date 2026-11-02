"use client";
import { ArrowDownRight, ArrowUpRight, EyeOff, Send } from "lucide-react";
import { useState } from "react";
import { LiquidityChart } from "@/components/widgets/charts";
import { Empty, Panel, PriorityTag, Skeleton, Why } from "@/components/ui";
import {
  api, type DayPoint, type Insight, type SafeToSpend, type StateResponse, type TimelineEvent, type WhatChanged,
  useApi,
} from "@/lib/api";
import { HORIZON_LABEL, eur, num, pct, relDays, shortDate, signedEur } from "@/lib/format";

export function FinancialState() {
  const { data } = useApi<StateResponse>("/api/state");
  if (!data) return <Panel title="Financial State"><Skeleton /></Panel>;
  const s = data.score;
  const delta = data.previous_score !== null ? s.score - data.previous_score : null;
  return (
    <Panel title={<span className="flex items-center gap-1">Financial State <Why explanation={s.explanation} title="Financial State" /></span>}>
      <div className="flex items-baseline gap-2">
        <span className="num text-4xl font-semibold">{Math.round(s.score)}</span>
        <span className="muted">/ 100 · {s.grade}</span>
        {delta !== null && Math.abs(delta) >= 0.5 && (
          <span className="num text-xs secondary">{delta > 0 ? "+" : ""}{delta.toFixed(0)} pts / 7 j</span>)}
      </div>
      <ul className="mt-3 space-y-1.5">
        {s.subscores.map((sub) => (
          <li key={sub.key} className="text-xs" title={sub.detail}>
            <div className="flex justify-between"><span className="secondary">{sub.label}</span>
              <span className="num muted">{sub.metric}</span></div>
            <div className="mt-0.5 h-1 rounded-full bg-[var(--surface-2)]">
              <div className="h-1 rounded-full" style={{ width: `${sub.score}%`, background: "var(--series-1)" }} />
            </div>
          </li>
        ))}
      </ul>
      {data.changes.length > 0 && (
        <ul className="mt-3 space-y-0.5 text-xs secondary">{data.changes.slice(0, 3).map((c) => <li key={c.key}>{c.text}</li>)}</ul>)}
    </Panel>
  );
}

export function SafeToSpendWidget() {
  const { data } = useApi<SafeToSpend[]>("/api/safe-to-spend");
  const [h, setH] = useState<SafeToSpend["horizon"]>("until_next_income");
  if (!data) return <Panel title="Safe to spend"><Skeleton /></Panel>;
  const cur = data.find((d) => d.horizon === h) ?? data[0]!;
  const negative = num(cur.value) < 0;
  return (
    <Panel title={<span className="flex items-center gap-1">Safe to spend <Why explanation={cur.explanation} title={`Safe to spend — ${HORIZON_LABEL[cur.horizon]}`} /></span>}>
      <div className="num text-4xl font-semibold">{eur(cur.value)}</div>
      <div className="secondary text-xs">
        {negative ? "Engagements supérieurs au disponible : prudence." : `≈ ${eur(cur.per_day)}/jour jusqu'au ${shortDate(cur.end_date)}`}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-1" role="tablist" aria-label="Horizon">
        {data.map((d) => (
          <button key={d.horizon} role="tab" aria-selected={d.horizon === h} onClick={() => setH(d.horizon)}
            className={`rounded-md border px-2 py-1.5 text-left text-xs ${d.horizon === h ? "border-[var(--accent)]" : "border-[var(--border)]"}`}>
            <div className="muted">{HORIZON_LABEL[d.horizon]}</div>
            <div className="num font-medium">{eur(d.value)}</div>
          </button>
        ))}
      </div>
    </Panel>
  );
}

export function InsightList({ section, title }: { section: "attention" | "opportunity"; title: string }) {
  const { data, mutate } = useApi<Insight[]>(`/api/insights?section=${section}&limit=${section === "attention" ? 5 : 3}`);
  const ignore = async (id: string) => {
    await api(`/api/insights/${id}`, { method: "PATCH", json: { state: "ignored" } });
    await mutate();
  };
  return (
    <Panel title={title}>
      {!data ? <Skeleton /> : data.length === 0 ? <Empty>Rien d&apos;important à signaler.</Empty> : (
        <ul className="divide-y divide-[var(--border)] overflow-auto">
          {data.map((i) => (
            <li key={i.id} className="flex items-start gap-2 py-2 first:pt-0">
              <div className="min-w-0 flex-1">
                <div className="text-sm leading-snug">{i.title}</div>
                <div className="mt-0.5 flex items-center gap-2">
                  <PriorityTag p={i.priority} />
                  <span className="muted text-[11px]">confiance {Math.round(i.confidence * 100)} %</span>
                  {i.suggested_actions[0]?.filter?.category ? (
                    <a className="text-[11px] text-[var(--accent)]"
                      href={`/transactions?category=${String(i.suggested_actions[0].filter.category)}`}>voir</a>) : null}
                </div>
              </div>
              <button aria-label="Ignorer" title="Ignorer" onClick={() => void ignore(i.id)} className="muted -m-1 p-2">
                <EyeOff size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function WhatChangedWidget() {
  const [preset, setPreset] = useState("30d");
  const { data } = useApi<WhatChanged>(`/api/what-changed?preset=${preset}`);
  const max = Math.max(1, ...(data?.category_drivers ?? []).map((d) => Math.abs(num(d.delta))));
  return (
    <Panel title="Ce qui a changé" action={
      <select aria-label="Période" value={preset} onChange={(e) => setPreset(e.target.value)}
        className="rounded-md border border-[var(--border)] bg-transparent px-1.5 py-1 text-xs">
        <option value="yesterday">Depuis hier</option><option value="7d">7 jours</option>
        <option value="30d">30 jours</option><option value="mtd">Ce mois</option>
        <option value="since_salary">Depuis le salaire</option>
      </select>}>
      {!data ? <Skeleton /> : (
        <div className="flex h-full flex-col">
          <p className="text-sm">{data.headline} <Why explanation={data.explanation} title="Ce qui a changé" /></p>
          <ul className="mt-2 space-y-1.5 overflow-auto">
            {data.category_drivers.slice(0, 6).map((d) => {
              const up = num(d.delta) > 0;
              return (
                <li key={d.key} className="text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1 truncate">
                      {up ? <ArrowUpRight size={12} aria-hidden /> : <ArrowDownRight size={12} aria-hidden />}{d.label}
                    </span>
                    <span className="num">{signedEur(d.delta)} <span className="muted">({eur(d.previous)} → {eur(d.current)})</span></span>
                  </div>
                  <div className="mt-0.5 h-1 rounded-full bg-[var(--surface-2)]">
                    <div className="h-1 rounded-full" style={{ width: `${(Math.abs(num(d.delta)) / max) * 100}%`,
                      background: up ? "var(--series-2)" : "var(--series-1)" }} />
                  </div>
                </li>);
            })}
          </ul>
          {data.recurring_drivers.length > 0 && (
            <p className="muted mt-auto pt-2 text-[11px]">Récurrents isolés (effet calendrier) : {data.recurring_drivers
              .slice(0, 2).map((d) => `${d.label} ${signedEur(d.delta)}`).join(", ")}</p>)}
        </div>
      )}
    </Panel>
  );
}

interface TimelineResponse { events: TimelineEvent[]; projection: { days: DayPoint[]; lowest: DayPoint; end_balance: string } }

export function Next30Days() {
  const { data } = useApi<TimelineResponse>("/api/timeline?days=30");
  const today = data?.projection.days[0]?.date ?? "";
  return (
    <Panel title="30 prochains jours" action={data && (
      <span className="num text-xs secondary">point bas {eur(data.projection.lowest.balance)} le {shortDate(data.projection.lowest.date)}</span>)}>
      {!data ? <Skeleton /> : data.events.length === 0 ? <Empty>Pas encore de récurrence détectée.</Empty> : (
        <table className="w-full text-xs">
          <caption className="sr-only">Événements financiers attendus</caption>
          <tbody>
            {data.events.slice(0, 12).map((e, i) => (
              <tr key={i} className="border-b border-[var(--border)] last:border-0">
                <td className="num muted py-1 pr-2 whitespace-nowrap">{shortDate(e.expected_date)}</td>
                <td className="py-1 pr-2 truncate">{e.label}<span className="muted"> · {relDays(e.expected_date, today)}</span></td>
                <td className="num py-1 pr-2 text-right whitespace-nowrap">{signedEur(e.expected_amount)}</td>
                <td className="num muted py-1 text-right">{Math.round(e.confidence * 100)} %</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

export function Liquidity() {
  const { data } = useApi<TimelineResponse>("/api/timeline?days=45");
  return (
    <Panel title="Liquidité future (comptes courants)">
      {!data ? <Skeleton /> : <LiquidityChart days={data.projection.days} />}
    </Panel>
  );
}

interface Cashflow { by_category: { category_key: string; amount: string; share: number }[]; expenses: string; savings_rate: number | null }

export function SpendingBreakdown() {
  const { data } = useApi<Cashflow>("/api/metrics/cashflow?days=30");
  const { data: cats } = useApi<{ key: string; name: string }[]>("/api/categories");
  const names = Object.fromEntries((cats ?? []).map((c) => [c.key, c.name]));
  const max = Math.max(1, ...(data?.by_category ?? []).map((c) => num(c.amount)));
  return (
    <Panel title="Dépenses 30 j" action={data && <span className="num text-xs secondary">{eur(data.expenses)}</span>}>
      {!data ? <Skeleton /> : (
        <ul className="space-y-1.5 overflow-auto">
          {data.by_category.slice(0, 10).map((c) => (
            <li key={c.category_key} className="text-xs">
              <div className="flex justify-between"><span>{names[c.category_key] ?? c.category_key}</span>
                <span className="num">{eur(c.amount)} <span className="muted">{pct(c.share)}</span></span></div>
              <div className="mt-0.5 h-1 rounded-full bg-[var(--surface-2)]">
                <div className="h-1 rounded-full" style={{ width: `${(num(c.amount) / max) * 100}%`, background: "var(--series-1)" }} />
              </div>
            </li>))}
        </ul>)}
    </Panel>
  );
}

interface Pattern { id: string; label: string; cadence: string; amount: string; is_subscription: boolean; next_expected_date: string; annual_amount: string; direction: string }

export function Subscriptions() {
  const { data } = useApi<Pattern[]>("/api/recurring");
  const subs = (data ?? []).filter((p) => p.direction === "out");
  return (
    <Panel title="Récurrents & abonnements" action={data && <span className="num text-xs secondary">
      {subs.filter((s) => s.is_subscription).length} abonnements</span>}>
      {!data ? <Skeleton /> : (
        <ul className="divide-y divide-[var(--border)] overflow-auto text-xs">
          {subs.map((p) => (
            <li key={p.id} className="flex justify-between gap-2 py-1.5">
              <span className="truncate">{p.label} {p.is_subscription && <span className="muted">· abonnement</span>}</span>
              <span className="num whitespace-nowrap">{eur(-num(p.amount), true)} <span className="muted">· {shortDate(p.next_expected_date)}</span></span>
            </li>))}
        </ul>)}
    </Panel>
  );
}

interface Health { confidence: number; issues: { key: string; severity: string; title: string; count: number; amount: string | null; action: string | null }[] }

export function DataHealthWidget() {
  const { data } = useApi<Health>("/api/data-health");
  return (
    <Panel title="Data Health" action={data && <span className="num text-xs secondary">confiance {Math.round(data.confidence * 100)} %</span>}>
      {!data ? <Skeleton /> : data.issues.length === 0 ? <Empty>Données complètes et à jour.</Empty> : (
        <ul className="space-y-1.5 text-xs">
          {data.issues.map((i) => (
            <li key={i.key}>
              <span aria-hidden style={{ color: i.severity === "critical" ? "var(--critical)" : i.severity === "warning" ? "var(--serious)" : "var(--text-muted)" }}>●</span>{" "}
              {i.title}{i.count ? ` (${i.count})` : ""}{i.amount ? ` · ${eur(i.amount)}` : ""}
              {i.action && <div className="muted ml-3">{i.action}</div>}
            </li>))}
        </ul>)}
    </Panel>
  );
}

interface Feed { id: string; occurred_at: string; title: string; priority: string }

export function FeedWidget() {
  const { data } = useApi<Feed[]>("/api/feed?limit=30");
  return (
    <Panel title="Feed">
      {!data ? <Skeleton /> : data.length === 0 ? <Empty>Le système observe… rien de nouveau.</Empty> : (
        <ol className="space-y-2 overflow-auto text-xs">
          {data.map((f) => (
            <li key={f.id}>
              <div className="num muted">{new Date(f.occurred_at).toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</div>
              <div>{f.title}</div>
            </li>))}
        </ol>)}
    </Panel>
  );
}

export function AskWidget() {
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState<{ answer: string; tools_used: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (q.trim().length < 2) return;
    setBusy(true);
    try {
      setAnswer(await api("/api/ask", { method: "POST", json: { question: q } }));
    } finally { setBusy(false); }
  };
  return (
    <Panel title="Ask your money">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Pourquoi ai-je dépensé plus ce mois-ci ?"
          aria-label="Question" className="field flex-1" />
        <button disabled={busy} aria-label="Envoyer" className="rounded-[10px] bg-[var(--accent)] px-3 text-white disabled:opacity-50"><Send size={14} /></button>
      </form>
      {answer && (
        <div className="mt-2 overflow-auto text-sm whitespace-pre-line">{answer.answer}
          <div className="muted mt-1 text-[11px]">outils : {answer.tools_used.join(", ")}</div></div>)}
    </Panel>
  );
}
