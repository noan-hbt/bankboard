"use client";
import { useMemo } from "react";
import { Chart, baseOption, useTokens } from "@/components/Chart";
import { Empty, Panel, Skeleton } from "@/components/ui";
import { type DayPoint, useApi } from "@/lib/api";
import { eur, num, shortDate } from "@/lib/format";

interface Snapshot { date: string; net_worth: string; cash: string; financial_score: string | null; reconstructed: boolean }
interface Monthly { month: string; income: string; expenses: string; net: string; savings_rate: number | null }

const euroAxis = (v: number) => `${Math.round(v / 1000)}k`;

export function WealthTrajectory() {
  const t = useTokens();
  const { data } = useApi<Snapshot[]>("/api/snapshots?days=365");
  const option = useMemo(() => {
    if (!t || !data) return null;
    return {
      ...baseOption(t),
      xAxis: { type: "category", data: data.map((d) => d.date), boundaryGap: false,
        axisLine: { lineStyle: { color: t.grid } }, axisTick: { show: false },
        axisLabel: { formatter: (v: string) => shortDate(v), hideOverlap: true } },
      yAxis: { type: "value", scale: true, splitLine: { lineStyle: { color: t.grid } },
        axisLabel: { formatter: euroAxis } },
      tooltip: { ...(baseOption(t).tooltip as object),
        valueFormatter: (v: number) => eur(v) },
      series: [{ name: "Patrimoine net", type: "line", data: data.map((d) => num(d.net_worth)), showSymbol: false,
        symbolSize: 8, lineStyle: { width: 2, color: t.s1 }, itemStyle: { color: t.s1 },
        areaStyle: { color: t.s1, opacity: 0.08 } }],
    };
  }, [t, data]);
  const last = data?.at(-1);
  return (
    <Panel title="Trajectoire du patrimoine" action={last && (
      <span className="num text-xs secondary">{eur(last.net_worth)} aujourd&apos;hui</span>)}>
      {!data ? <Skeleton /> : data.length === 0 ? <Empty>Aucun snapshot pour l&apos;instant.</Empty>
        : option && <Chart option={option} label="Évolution du patrimoine net sur 12 mois" />}
    </Panel>
  );
}

export function CashflowMonthly() {
  const t = useTokens();
  const { data } = useApi<Monthly[]>("/api/metrics/cashflow/monthly?months=12");
  const option = useMemo(() => {
    if (!t || !data) return null;
    return {
      ...baseOption(t),
      grid: { left: 8, right: 12, top: 28, bottom: 4, containLabel: true },
      legend: { top: 0, left: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: t.muted } },
      tooltip: { ...(baseOption(t).tooltip as object), axisPointer: { type: "shadow" },
        valueFormatter: (v: number) => eur(v) },
      xAxis: { type: "category", data: data.map((d) => d.month.slice(5) + "/" + d.month.slice(2, 4)),
        axisTick: { show: false }, axisLine: { lineStyle: { color: t.grid } } },
      yAxis: { type: "value", splitLine: { lineStyle: { color: t.grid } }, axisLabel: { formatter: euroAxis } },
      series: [
        { name: "Revenus", type: "bar", data: data.map((d) => num(d.income)), barGap: "15%", barMaxWidth: 14,
          itemStyle: { color: t.s1, borderRadius: [4, 4, 0, 0] } },
        { name: "Dépenses", type: "bar", data: data.map((d) => num(d.expenses)), barMaxWidth: 14,
          itemStyle: { color: t.s2, borderRadius: [4, 4, 0, 0] } },
      ],
    };
  }, [t, data]);
  return (
    <Panel title="Cashflow mensuel">
      {!data ? <Skeleton /> : option && <Chart option={option} label="Revenus et dépenses par mois sur 12 mois" />}
    </Panel>
  );
}

export function LiquidityChart({ days }: { days: DayPoint[] }) {
  const t = useTokens();
  const option = useMemo(() => {
    if (!t) return null;
    const lowest = days.reduce((a, b) => (num(b.balance) < num(a.balance) ? b : a), days[0]!);
    return {
      ...baseOption(t),
      grid: { left: 4, right: 8, top: 18, bottom: 0, containLabel: true },
      tooltip: { ...(baseOption(t).tooltip as object), valueFormatter: (v: number) => eur(v) },
      xAxis: { type: "category", data: days.map((d) => d.date), boundaryGap: false, axisTick: { show: false },
        axisLine: { lineStyle: { color: t.grid } }, axisLabel: { formatter: (v: string) => shortDate(v), hideOverlap: true } },
      yAxis: { type: "value", scale: true, splitLine: { lineStyle: { color: t.grid } }, axisLabel: { formatter: euroAxis } },
      series: [{
        name: "Solde prévu", type: "line", data: days.map((d) => num(d.balance)), step: "end", showSymbol: false,
        lineStyle: { width: 2, color: t.s1 }, itemStyle: { color: t.s1 },
        markPoint: lowest ? {
          symbol: "circle", symbolSize: 9, itemStyle: { color: t.s1, borderColor: t.surface, borderWidth: 2 },
          label: { show: true, position: "bottom", color: t.text, fontSize: 11, formatter: `point bas ${eur(lowest.balance)}` },
          data: [{ coord: [lowest.date, num(lowest.balance)] }],
        } : undefined,
      }],
    };
  }, [t, days]);
  return option ? <Chart option={option} label="Projection du solde des comptes courants jour par jour" /> : null;
}
