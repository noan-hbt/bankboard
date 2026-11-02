"use client";
import { Eye, EyeOff, Plus, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Responsive, WidthProvider, type Layout } from "react-grid-layout";
import { WIDGETS } from "@/components/widgets/registry";
import { api, type LayoutItem, type WidgetDef, useApi } from "@/lib/api";

const Grid = WidthProvider(Responsive);
const ROW = 60;
const MOBILE = "(max-width: 699px)";

/** Below the grid's "md" breakpoint, widgets are stacked with their natural height. */
function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(MOBILE);
    const update = () => setMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return mobile;
}

export function DashboardGrid({ editing }: { editing: boolean }) {
  const { data: catalog } = useApi<WidgetDef[]>("/api/widgets");
  const { data: saved, mutate } = useApi<{ items: LayoutItem[] }>("/api/dashboard/layout");
  const [items, setItems] = useState<LayoutItem[]>([]);
  const mobile = useIsMobile();
  useEffect(() => { if (saved) setItems(saved.items); }, [saved]);

  const available = useMemo(() => new Set((catalog ?? []).map((w) => w.id)), [catalog]);
  const visible = items.filter((i) => !i.hidden && available.has(i.widget) && WIDGETS[i.widget]);

  const persist = useCallback(async (next: LayoutItem[]) => {
    setItems(next);
    await api("/api/dashboard/layout", { method: "PUT", json: { items: next } });
    await mutate();
  }, [mutate]);

  const onLayoutChange = (layout: Layout[]) => {
    if (!editing) return;
    const byId = new Map(layout.map((l) => [l.i, l]));
    const next = items.map((it) => {
      const l = byId.get(it.i);
      return l ? { ...it, x: l.x, y: l.y, w: l.w, h: l.h } : it;
    });
    if (JSON.stringify(next) !== JSON.stringify(items)) void persist(next);
  };

  const add = (w: WidgetDef) => {
    const existing = items.find((i) => i.widget === w.id);
    if (existing) return void persist(items.map((i) => (i.i === existing.i ? { ...i, hidden: false } : i)));
    void persist([...items, { i: `${w.id}-${Date.now().toString(36)}`, widget: w.id, x: 0, y: 999, w: w.w, h: w.h }]);
  };
  const duplicate = (it: LayoutItem) =>
    void persist([...items, { ...it, i: `${it.widget}-${Date.now().toString(36)}`, y: 999 }]);

  return (
    <div>
      {editing && catalog && (
        <div className="panel mb-3 flex flex-wrap items-center gap-1.5 p-2 text-xs">
          <span className="label mr-1">Widgets</span>
          {catalog.map((w) => {
            const shown = visible.some((v) => v.widget === w.id);
            return (
              <button key={w.id} onClick={() => add(w)} disabled={shown}
                className="flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 disabled:opacity-40">
                <Plus size={12} />{w.title}
              </button>);
          })}
          <button onClick={() => void api("/api/dashboard/layout", { method: "DELETE" }).then(() => mutate())}
            className="ml-auto flex items-center gap-1 rounded px-2 py-1 secondary"><RotateCcw size={12} />Réinitialiser</button>
        </div>
      )}
      {mobile && !editing ? (
        <div className="stack flex flex-col gap-3">
          {[...visible].sort((a, b) => a.y - b.y || a.x - b.x).map((it) => {
            const W = WIDGETS[it.widget]!;
            return <div key={it.i}><W /></div>;
          })}
        </div>
      ) : (
      <Grid
        className="-mx-[5px]"
        layouts={{ lg: visible.map((i) => ({ i: i.i, x: i.x, y: i.y, w: i.w, h: i.h, minW: 2, minH: 2 })) }}
        breakpoints={{ lg: 1024, md: 700, sm: 0 }}
        cols={{ lg: 12, md: 6, sm: 1 }}
        rowHeight={ROW}
        margin={[10, 10]}
        isDraggable={editing}
        isResizable={editing}
        draggableHandle=".drag-handle"
        onLayoutChange={onLayoutChange}
      >
        {visible.map((it) => {
          const W = WIDGETS[it.widget]!;
          return (
            <div key={it.i} className="relative">
              {editing && (
                <div className="drag-handle absolute inset-x-0 top-0 z-10 flex cursor-move justify-end gap-1 rounded-t-[14px] bg-[var(--surface-2)]/80 p-1 text-xs">
                  <button onClick={() => duplicate(it)} className="rounded px-1.5" aria-label="Dupliquer">⧉</button>
                  <button onClick={() => void persist(items.map((i) => (i.i === it.i ? { ...i, hidden: true } : i)))}
                    className="rounded px-1.5" aria-label="Masquer"><EyeOff size={12} /></button>
                </div>)}
              <W />
            </div>);
        })}
      </Grid>
      )}
      {editing && items.some((i) => i.hidden) && (
        <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
          {items.filter((i) => i.hidden).map((i) => (
            <button key={i.i} onClick={() => void persist(items.map((x) => (x.i === i.i ? { ...x, hidden: false } : x)))}
              className="flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1"><Eye size={12} />{i.widget}</button>))}
        </div>)}
    </div>
  );
}
