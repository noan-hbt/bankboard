"use client";
import { Send } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";

interface Msg { role: "user" | "assistant"; text: string; tools?: string[]; unverified?: string[]; provider?: string }
const SUGGESTIONS = [
  "Pourquoi ai-je dépensé plus ce mois-ci ?", "Combien puis-je dépenser ce week-end ?",
  "Quels abonnements je paie ?", "Combien ai-je dépensé chez Amazon ?", "Qu'est-ce qui est prévu ce mois-ci ?",
];

function Chat() {
  const params = useSearchParams();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [conv, setConv] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const ask = async (question: string) => {
    if (question.trim().length < 2 || busy) return;
    setMsgs((m) => [...m, { role: "user", text: question }]); setQ(""); setBusy(true);
    try {
      const r = await api<{ conversation_id: string; answer: string; tools_used: string[]; unverified_numbers: string[]; provider: string }>(
        "/api/ask", { method: "POST", json: { question, conversation_id: conv } });
      setConv(r.conversation_id);
      setMsgs((m) => [...m, { role: "assistant", text: r.answer, tools: r.tools_used, unverified: r.unverified_numbers, provider: r.provider }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", text: `Erreur : ${(e as Error).message}` }]);
    } finally { setBusy(false); }
  };
  useEffect(() => { const q0 = params.get("q"); if (q0) void ask(q0); /* eslint-disable-next-line */ }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);
  return (
    <div className="mx-auto flex max-w-2xl flex-col">
      <div className="space-y-3 pb-28">
        {msgs.length === 0 && (
          <div className="panel p-4">
            <h1 className="font-semibold">Ask your money</h1>
            <p className="secondary text-sm">Les chiffres viennent toujours du moteur de calcul, jamais du modèle de langage.</p>
            <div className="mt-3 flex flex-wrap gap-2">{SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => void ask(s)} className="rounded-full border border-[var(--border)] px-3 py-1 text-xs">{s}</button>))}</div>
          </div>)}
        {msgs.map((m, i) => (
          <div key={i} className={m.role === "user" ? "ml-10 rounded-lg bg-[var(--surface-2)] p-3 text-sm" : "panel p-3 text-sm whitespace-pre-line"}>
            {m.text}
            {m.tools && <div className="muted mt-2 text-[11px]">{m.provider} · outils : {m.tools.join(", ") || "aucun"}</div>}
            {m.unverified && m.unverified.length > 0 && (
              <div className="mt-1 text-[11px]" style={{ color: "var(--serious)" }}>⚠ nombres non vérifiés : {m.unverified.join(", ")}</div>)}
          </div>))}
        {busy && <div className="muted text-sm">Analyse…</div>}
        <div ref={end} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); void ask(q); }}
        className="fixed inset-x-0 bottom-16 z-20 mx-auto flex max-w-2xl gap-2 px-4 sm:bottom-6">
        <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Question" placeholder="Pose une question sur tes finances…"
          className="panel min-w-0 flex-1 px-3 py-2.5 text-sm" />
        <button disabled={busy} aria-label="Envoyer" className="rounded-[10px] bg-[var(--accent)] px-4 text-white disabled:opacity-50"><Send size={16} /></button>
      </form>
    </div>
  );
}

export default function Page() {
  return <AppShell><Suspense><Chat /></Suspense></AppShell>;
}
