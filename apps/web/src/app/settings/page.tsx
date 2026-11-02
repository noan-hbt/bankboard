"use client";
import { RefreshCw, Trash2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { DataHealthWidget } from "@/components/widgets/cards";
import { Panel } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { eur } from "@/lib/format";

interface Conn { id: string; provider: string; institution_name: string; status: string; consent_valid_until: string | null; last_synced_at: string | null; last_error: string | null }
interface Acc { id: string; name: string; iban_masked: string | null; account_type: string; is_spending: boolean; is_liquid: boolean; balance: string | null }
interface Mod { key: string; title: string; tier: string; description: string; enabled: boolean }
interface Prefs { min_buffer: string | null }

function Settings() {
  const params = useSearchParams();
  const { data: conns, mutate: mConns } = useApi<Conn[]>("/api/bank/connections", { refreshInterval: 5000 });
  const { data: accs, mutate: mAccs } = useApi<Acc[]>("/api/accounts");
  const { data: mods, mutate: mMods } = useApi<Mod[]>("/api/modules");
  const { data: prefs, mutate: mPrefs } = useApi<Prefs>("/api/preferences");
  const bank = params.get("bank");
  const [connectError, setConnectError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState<string | null>(null);
  // Back from the bank (on iOS the bank flow ends in Safari, outside the installed app): reset and refresh.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      setConnecting(null);
      void mConns(); void mAccs();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pageshow", onVisible);
    return () => { document.removeEventListener("visibilitychange", onVisible); window.removeEventListener("pageshow", onVisible); };
  }, [mConns, mAccs]);

  const connect = async (provider: string) => {
    setConnectError(null); setConnecting(provider);
    try {
      const { url } = await api<{ url: string }>("/api/bank/connect", { method: "POST",
        json: { provider, institution_name: provider === "demo" ? "Revolut (démo)" : "Revolut", institution_country: "FR" } });
      window.location.href = url;
    } catch (e) {
      setConnectError((e as Error).message);
      setConnecting(null);
    }
  };
  const [deleting, setDeleting] = useState<string | null>(null);
  const removeConnection = async (c: Conn) => {
    if (!confirm(`Supprimer « ${c.institution_name} » ? Ses comptes et toutes ses transactions seront effacés, et les indicateurs recalculés avec les autres banques.`)) return;
    setDeleting(c.id);
    try {
      await api(`/api/bank/connections/${c.id}?delete_data=true`, { method: "DELETE" });
      await Promise.all([mConns(), mAccs()]);
    } catch (e) {
      alert((e as Error).message);
    } finally { setDeleting(null); }
  };
  const patchAccount = async (id: string, body: Partial<Acc>) => {
    await api(`/api/accounts/${id}`, { method: "PATCH", json: body }); await mAccs();
  };
  const row = "flex items-center justify-between gap-2 border-b border-[var(--border)] py-2 last:border-0 text-sm";
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {bank && <p role="status" className="panel p-3 text-sm md:col-span-2">
        {bank === "connected" ? "Banque connectée — synchronisation en cours…" : "La connexion bancaire a échoué ou a expiré. Réessaie."}</p>}
      <Panel title="Connexions bancaires">
        {(conns ?? []).map((c) => (
          <div key={c.id} className={row}>
            <div><div>{c.institution_name} <span className="muted text-xs">· {c.provider}</span></div>
              <div className="muted text-xs">{c.status}{c.last_synced_at ? ` · sync ${new Date(c.last_synced_at).toLocaleString("fr-FR")}` : ""}
                {c.consent_valid_until ? ` · consentement jusqu'au ${new Date(c.consent_valid_until).toLocaleDateString("fr-FR")}` : ""}</div>
              {c.last_error && <div className="text-xs" style={{ color: "var(--critical)" }}>{c.last_error}</div>}</div>
            <div className="flex gap-1">
              <button aria-label="Synchroniser" onClick={() => void api(`/api/bank/connections/${c.id}/sync`, { method: "POST" }).then(() => mConns())} className="rounded border border-[var(--border)] p-1.5"><RefreshCw size={14} /></button>
              {c.status === "reauth_required" && <button onClick={() => void connect(c.provider)} className="rounded border border-[var(--border)] px-2 text-xs">Reconnecter</button>}
              {c.status !== "revoked" && (
                <button onClick={() => confirm("Révoquer l'accès à cette banque ? Les données déjà importées sont conservées.") && void api(`/api/bank/connections/${c.id}`, { method: "DELETE" }).then(() => mConns())} className="rounded border border-[var(--border)] px-2 text-xs">Révoquer</button>)}
              <button aria-label="Supprimer la connexion et ses données" title="Supprimer la connexion et ses données"
                disabled={deleting === c.id}
                onClick={() => void removeConnection(c)}
                className="rounded border border-[var(--border)] p-1.5 disabled:opacity-40" style={{ color: "var(--critical)" }}><Trash2 size={14} /></button>
            </div>
          </div>))}
        <div className="mt-3 flex flex-wrap gap-2">
          <button disabled={!!connecting} onClick={() => void connect("enable_banking")} className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm text-white disabled:opacity-50">
            {connecting === "enable_banking" ? "Redirection…" : "Connecter Revolut"}</button>
          <button disabled={!!connecting} onClick={() => void connect("demo")} className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm disabled:opacity-50">Données démo</button>
        </div>
        {connectError && (
          <p role="alert" className="mt-3 rounded-md border px-3 py-2 text-xs leading-relaxed"
            style={{ borderColor: "var(--critical)", color: "var(--text-primary)" }}>
            <span style={{ color: "var(--critical)" }}>▲ Connexion impossible.</span> {connectError}
          </p>)}
      </Panel>
      <Panel title="Comptes">
        {(accs ?? []).map((a) => (
          <div key={a.id} className={row}>
            <div><div>{a.name}</div><div className="muted text-xs">{a.iban_masked ?? ""} · {a.account_type} · {eur(a.balance)}</div></div>
            <div className="flex flex-col items-end gap-0.5 text-xs">
              <label className="flex items-center gap-1"><input type="checkbox" checked={a.is_spending} onChange={(e) => void patchAccount(a.id, { is_spending: e.target.checked })} />dépenses</label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={a.is_liquid} onChange={(e) => void patchAccount(a.id, { is_liquid: e.target.checked })} />liquide</label>
            </div>
          </div>))}
      </Panel>
      <div className="stack"><DataHealthWidget /></div>
      <Panel title="Préférences">
        <label className="text-sm">Buffer minimum (€) — vide = calculé automatiquement
          <input type="number" min={0} defaultValue={prefs?.min_buffer ?? ""} key={prefs?.min_buffer ?? "auto"}
            onBlur={(e) => void api("/api/preferences", { method: "PUT", json: { min_buffer: e.target.value === "" ? null : e.target.value } }).then(() => mPrefs())}
            className="field mt-1 block w-40" />
        </label>
        <h3 className="label mt-4 mb-1">Modules</h3>
        {(mods ?? []).map((m) => (
          <label key={m.key} className={`${row} cursor-pointer`}>
            <span>{m.title} <span className="muted text-xs">{m.tier} · {m.description}</span></span>
            <input type="checkbox" checked={m.enabled} onChange={(e) => void api("/api/preferences", { method: "PUT", json: { modules: { [m.key]: e.target.checked } } }).then(() => mMods())} />
          </label>))}
        <h3 className="label mt-4 mb-1">Données</h3>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => void api("/api/auth/logout", { method: "POST" }).then(() => { window.location.href = "/login"; })} className="rounded border border-[var(--border)] px-3 py-1 text-sm">Se déconnecter</button>
          <button onClick={() => confirm("Supprimer définitivement toutes tes données ?") && void api("/api/me", { method: "DELETE" }).then(() => { window.location.href = "/login"; })}
            className="rounded px-3 py-1 text-sm text-white" style={{ background: "var(--critical)" }}>Supprimer toutes mes données</button>
        </div>
      </Panel>
    </div>
  );
}

export default function Page() {
  return <AppShell><Suspense><Settings /></Suspense></AppShell>;
}
