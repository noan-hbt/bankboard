"use client";
/**
 * Thin ECharts wrapper. Colors are read from CSS tokens at render time so light/dark each use
 * their own validated steps (not an automatic flip). Re-renders on theme change.
 */
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, MarkPointComponent, TooltipComponent, LegendComponent, MarkLineComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import { useEffect, useRef, useState } from "react";

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, MarkPointComponent,
  MarkLineComponent, SVGRenderer]);

export type Tokens = Record<"surface" | "text" | "muted" | "grid" | "s1" | "s2" | "s3" | "critical", string>;

function readTokens(): Tokens {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return { surface: v("--surface-1"), text: v("--text-primary"), muted: v("--text-muted"), grid: v("--grid"),
    s1: v("--series-1"), s2: v("--series-2"), s3: v("--series-3"), critical: v("--critical") };
}

export function useTokens(): Tokens | null {
  const [t, setT] = useState<Tokens | null>(null);
  useEffect(() => {
    const update = () => setT(readTokens());
    update();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => { mq.removeEventListener("change", update); obs.disconnect(); };
  }, []);
  return t;
}

export function baseOption(t: Tokens): echarts.EChartsCoreOption {
  return {
    animationDuration: 300,
    textStyle: { color: t.muted, fontFamily: "inherit", fontSize: 11 },
    grid: { left: 8, right: 12, top: 12, bottom: 4, containLabel: true },
    tooltip: {
      trigger: "axis", backgroundColor: t.surface, borderColor: t.grid, textStyle: { color: t.text, fontSize: 12 },
      axisPointer: { type: "line", lineStyle: { color: t.muted, width: 1, type: "dashed" } },
    },
  };
}

export function Chart({ option, label, height }: {
  option: echarts.EChartsCoreOption; label: string; height?: string | number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    inst.current = echarts.init(ref.current, undefined, { renderer: "svg" });
    const ro = new ResizeObserver(() => inst.current?.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); inst.current?.dispose(); inst.current = null; };
  }, []);
  useEffect(() => { inst.current?.setOption(option, true); }, [option]);
  return <div ref={ref} role="img" aria-label={label} className="chart-box" style={height !== undefined ? { height } : undefined} />;
}
