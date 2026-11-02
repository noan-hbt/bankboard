"use client";
import { useState } from "react";
import { api } from "@/lib/api";

export default function Login() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api(`/api/auth/${mode}`, { method: "POST", json: { email, password } });
      window.location.href = "/";
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <form className="panel w-full max-w-sm p-6" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <h1 className="text-xl font-semibold">bankboard</h1>
        <p className="secondary mb-4 text-sm">Ton cockpit financier personnel.</p>
        <label className="label" htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)}
          className="mb-3 mt-1 w-full rounded-md border border-[var(--border)] bg-transparent px-3 py-2" />
        <label className="label" htmlFor="pw">Mot de passe</label>
        <input id="pw" type="password" required minLength={mode === "register" ? 10 : 1}
          autoComplete={mode === "login" ? "current-password" : "new-password"} value={password}
          onChange={(e) => setPassword(e.target.value)} className="mt-1 w-full rounded-md border border-[var(--border)] bg-transparent px-3 py-2" />
        {error && <p role="alert" className="mt-3 text-sm" style={{ color: "var(--critical)" }}>{error}</p>}
        <button disabled={busy} className="mt-4 w-full rounded-md bg-[var(--accent)] py-2 text-white disabled:opacity-50">
          {mode === "login" ? "Se connecter" : "Créer le compte"}</button>
        <button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")} className="secondary mt-3 w-full text-sm">
          {mode === "login" ? "Créer un compte" : "J'ai déjà un compte"}</button>
      </form>
    </main>
  );
}
