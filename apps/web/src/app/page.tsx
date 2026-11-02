"use client";
import { Pencil } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { DashboardGrid } from "@/components/DashboardGrid";
import { Skeleton, Stat } from "@/components/ui";
import { api, type CommandCenter, useApi } from "@/lib/api";
import { eur, pct, shortDate, signedEur } from "@/lib/format";

function NowStrip({ cc }: { cc: CommandCenter }) {
  const n = cc.now;
  const next = cc.next.next_income;
  return (
    <section aria-label="Maintenant" className="panel grid grid-cols-2 gap-x-4 gap-y-4 p-4 md:grid-cols-3 lg:grid-cols-6">
      <Stat hero label="Safe to spend" value={eur(n.safe_to_spend.value)} why={n.safe_to_spend.explanation}
        sub={`jusqu'au ${shortDate(n.safe_to_spend.end_date)}`}
        className="col-span-2 border-b border-[var(--border)] pb-4 md:col-span-1 md:border-0 md:pb-0" />
      <Stat label="Cash dispo" value={eur(n.spending_cash)} sub={`liquidités ${eur(n.liquid_assets)}`} />
      <Stat label="Patrimoine net" value={eur(n.net_worth)} sub="comptes suivis" />
      <Stat label="Cashflow 30 j" value={signedEur(n.cashflow_30d.net)}
        sub={`${eur(n.cashflow_30d.income)} in · ${eur(n.cashflow_30d.expenses)} out`} />
      <Stat label="Taux d'épargne" value={pct(n.cashflow_30d.savings_rate)} sub={`dont investi ${eur(n.cashflow_30d.invested)}`} />
      <Stat label="Financial State" value={`${Math.round(n.financial_state.score)}/100`}
        sub={next ? `prochain revenu ${shortDate(next.date)} · ${eur(next.amount)}` : n.financial_state.grade} />
    </section>
  );
}

function Onboarding({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const connect = async (provider: string) => {
    setBusy(provider); setError(null);
    try {
      const { url } = await api<{ url: string }>("/api/bank/connect", { method: "POST",
        json: { provider, institution_name: provider === "demo" ? "Revolut (démo)" : "Revolut", institution_country: "FR" } });
      window.location.href = url;
    } catch (e) { setBusy(null); setError((e as Error).message); onDone(); }
  };
  return (
    <div className="panel mx-auto mt-6 max-w-md p-6 text-center sm:mt-10">
      <h1 className="text-lg font-semibold">Connecte ta banque</h1>
      <p className="secondary mt-1 text-sm">Lecture seule via Enable Banking (PSD2). Aucun mouvement d&apos;argent n&apos;est jamais effectué.</p>
      <div className="mt-4 flex flex-col gap-2">
        <button disabled={!!busy} onClick={() => void connect("enable_banking")} className="rounded-[10px] bg-[var(--accent)] py-2.5 font-medium text-white disabled:opacity-50">
          {busy === "enable_banking" ? "Redirection…" : "Connecter Revolut"}</button>
        <button disabled={!!busy} onClick={() => void connect("demo")} className="rounded-[10px] border border-[var(--border)] py-2.5 disabled:opacity-50">
          {busy === "demo" ? "Préparation…" : "Essayer avec 12 mois de démo"}</button>
      </div>
      {error && <p role="alert" className="mt-4 text-left text-xs leading-relaxed">
        <span style={{ color: "var(--critical)" }}>▲ Connexion impossible.</span> {error}</p>}
    </div>
  );
}

function CommandCenterPage() {
  const params = useSearchParams();
  const [editing, setEditing] = useState(params.get("edit") === "1");
  const { data, mutate } = useApi<CommandCenter>("/api/command-center", { refreshInterval: 60_000 });
  return (
    <AppShell>
      {!data ? <div className="h-28"><Skeleton /></div> : !data.has_data ? <Onboarding onDone={() => void mutate()} /> : (
        <>
          <NowStrip cc={data} />
          <div className="my-3 flex items-center gap-3 px-1">
            <p className="text-sm leading-snug secondary">{data.what_changed.headline}</p>
            {data.data_confidence < 0.8 && <span className="text-xs" style={{ color: "var(--serious)" }}>● données incomplètes</span>}
            <button onClick={() => setEditing(!editing)} aria-pressed={editing}
              className="muted ml-auto hidden items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-xs md:flex">
              <Pencil size={12} />{editing ? "Terminer" : "Personnaliser"}
            </button>
          </div>
          <DashboardGrid editing={editing} />
        </>
      )}
    </AppShell>
  );
}

export default function Page() {
  return <Suspense><CommandCenterPage /></Suspense>;
}
