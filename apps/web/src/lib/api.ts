/** Typed fetch helpers. All financial numbers come from the backend; the client only formats them. */
import useSWR, { type SWRConfiguration } from "swr";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(path, {
    credentials: "same-origin",
    ...rest,
    headers: { ...(json !== undefined ? { "content-type": "application/json" } : {}), ...(rest.headers ?? {}) },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 401 && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.href = "/login";
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function useApi<T>(path: string | null, config?: SWRConfiguration<T>) {
  return useSWR<T>(path, (p: string) => api<T>(p), { revalidateOnFocus: true, ...config });
}

/* ---- API shapes (subset used by the UI) ---------------------------------- */
export type Money = string; // Decimal serialized by the backend

export interface ExplainLine { label: string; amount: Money | null; op: string; detail: string | null }
export interface Explanation { method: string; lines: ExplainLine[]; confidence: number }

export interface SafeToSpend {
  horizon: "today" | "week" | "until_next_income" | "month";
  end_date: string; days: number; value: Money; per_day: Money; explanation: Explanation;
}

export interface Insight {
  id: string; type: string; section: string; priority: "info" | "useful" | "important" | "critical";
  importance: number; confidence: number; title: string; metrics: Record<string, unknown>;
  suggested_actions: { type: string; label?: string; filter?: Record<string, unknown> }[]; state: string;
}

export interface TimelineEvent {
  expected_date: string; label: string; expected_amount: Money; confidence: number; kind: string;
  prediction_source: string; range_min?: Money; range_max?: Money;
}

export interface DayPoint { date: string; balance: Money; inflow: Money; outflow: Money; pressure: number }

export interface CommandCenter {
  today: string; data_confidence: number; has_data: boolean;
  now: {
    spending_cash: Money; liquid_assets: Money; net_worth: Money;
    cashflow_30d: { income: Money; expenses: Money; net: Money; savings_rate: number | null; invested: Money };
    safe_to_spend: SafeToSpend;
    financial_state: { score: number; grade: string; previous: number | null };
  };
  next: {
    next_income: { date: string; amount: Money; confidence: number; label: string } | null;
    expected_outflows_30d: Money; events: TimelineEvent[]; projected_balance_30d: Money; lowest: DayPoint;
  };
  attention: Insight[]; opportunities: Insight[];
  what_changed: { headline: string; drivers: Driver[] };
}

export interface Driver {
  key: string; label: string; previous: Money; current: Money; delta: Money; delta_pct: number | null;
  share_of_change: number;
}

export interface WhatChanged {
  headline: string; expenses_current: Money; expenses_previous: Money; variable_delta: Money;
  category_drivers: Driver[]; merchant_drivers: Driver[]; recurring_drivers: Driver[];
  current: { start: string; end: string; label: string }; previous: { start: string; end: string; label: string };
  explanation: Explanation;
}

export interface SubScore { key: string; label: string; score: number; weight: number; points: number; metric: string; detail: string }
export interface StateResponse {
  score: { score: number; grade: string; subscores: SubScore[]; explanation: Explanation };
  previous_score: number | null;
  changes: { key: string; label: string; delta_points: number; text: string }[];
}

export interface Transaction {
  id: string; booking_date: string; status: string; amount: Money; currency: string; label: string;
  merchant: string | null; kind: string; category_key: string; category_confidence: Money; category_source: string;
  is_recurring: boolean; is_transfer: boolean; is_excluded: boolean; note: string | null;
}

export interface Category { key: string; name: string; parent_key: string | null; color: string | null; default_kind: string }

export interface WidgetDef { id: string; module: string; title: string; kind: string; endpoint: string; w: number; h: number; min_w: number; min_h: number }
export interface LayoutItem { i: string; widget: string; x: number; y: number; w: number; h: number; hidden?: boolean }
