/** Display formatting only — never arithmetic on financial values beyond sign/abs for presentation. */
const eur0 = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const eur2 = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", minimumFractionDigits: 2 });

export function num(v: string | number | null | undefined): number {
  if (v === null || v === undefined) return 0;
  return typeof v === "number" ? v : Number(v);
}

export function eur(v: string | number | null | undefined, cents = false): string {
  return (cents ? eur2 : eur0).format(num(v));
}

export function signedEur(v: string | number | null | undefined, cents = false): string {
  const n = num(v);
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${(cents ? eur2 : eur0).format(Math.abs(n))}`;
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(digits).replace(".", ",")} %`;
}

export function shortDate(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
}

export function relDays(iso: string, today: string): string {
  const d = Math.round((Date.parse(`${iso}T12:00:00`) - Date.parse(`${today}T12:00:00`)) / 86_400_000);
  if (d === 0) return "aujourd'hui";
  if (d === 1) return "demain";
  return d > 0 ? `dans ${d} j` : `il y a ${-d} j`;
}

export const HORIZON_LABEL: Record<string, string> = {
  today: "Aujourd'hui", week: "Cette semaine", until_next_income: "Jusqu'au salaire", month: "Ce mois-ci",
};
