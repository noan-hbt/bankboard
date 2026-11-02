"use client";
import type { ComponentType } from "react";
import {
  AskWidget, DataHealthWidget, FeedWidget, FinancialState, InsightList, Liquidity, Next30Days, SafeToSpendWidget,
  SpendingBreakdown, Subscriptions, WhatChangedWidget,
} from "@/components/widgets/cards";
import { CashflowMonthly, WealthTrajectory } from "@/components/widgets/charts";

/** Widget id (from the backend module catalog) -> component. */
export const WIDGETS: Record<string, ComponentType> = {
  financial_state: FinancialState,
  safe_to_spend: SafeToSpendWidget,
  attention: () => <InsightList section="attention" title="Attention" />,
  opportunities: () => <InsightList section="opportunity" title="Opportunités" />,
  wealth_trajectory: WealthTrajectory,
  cashflow_monthly: CashflowMonthly,
  spending_breakdown: SpendingBreakdown,
  what_changed: WhatChangedWidget,
  next_30_days: Next30Days,
  liquidity: Liquidity,
  subscriptions: Subscriptions,
  data_health: DataHealthWidget,
  feed: FeedWidget,
  ask: AskWidget,
};
