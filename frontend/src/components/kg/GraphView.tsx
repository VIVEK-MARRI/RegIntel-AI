import { useMemo, useRef, useState } from "react";
import { clsx } from "clsx";

export interface GraphViewNode {
  id: string;
  label: string;
  type: string;
  /** 0 = center/selected, 1 = direct neighbor, 2+ = further ring. */
  depth: number;
}

export interface GraphViewEdge {
  id: string;
  source: string;
  target: string;
  type: string;
}

interface GraphViewProps {
  nodes: GraphViewNode[];
  edges: GraphViewEdge[];
  selectedId: string | null;
  /** Impact-affected ids get an accent outline (with textual depth list alongside). */
  highlightedIds?: ReadonlySet<string>;
  onSelectNode: (id: string) => void;
  className?: string;
}

/** Muted analytical fills keyed by the backend entity taxonomy. */
const TYPE_TONES: Record<string, string> = {
  regulation: "fill-brand-100 stroke-brand-500 dark:fill-brand-950/50 dark:stroke-brand-400",
  circular: "fill-sky-100 stroke-sky-500 dark:fill-sky-950/50 dark:stroke-sky-400",
  amendment: "fill-amber-100 stroke-amber-500 dark:fill-amber-950/50 dark:stroke-amber-400",
  institution: "fill-emerald-100 stroke-emerald-500 dark:fill-emerald-950/50 dark:stroke-emerald-400",
  topic: "fill-slate-200 stroke-slate-500 dark:fill-slate-800 dark:stroke-slate-400",
  requirement: "fill-violet-100 stroke-violet-500 dark:fill-violet-950/50 dark:stroke-violet-400",
};

const DEFAULT_TONE = "fill-slate-200 stroke-slate-500 dark:fill-slate-800 dark:stroke-slate-400";
const RING_1 = 95;
const RING_2 = 175;

interface PlacedNode extends GraphViewNode {
  x: number;
  y: number;
}

/**
 * Deterministic radial layout: selected node centered, direct neighbors on
 * an inner ring (sorted by id for stability), deeper nodes on an outer
 * ring. No physics, no motion — the graph is an instrument, and rings ARE
 * traversal depth (also listed textually beside the graph).
 */
export function GraphView({
  nodes,
  edges,
  selectedId,
  highlightedIds,
  onSelectNode,
  className,
}: GraphViewProps) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ x: number; y: number; px: number; py: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const placed = useMemo<PlacedNode[]>(() => {
    const center = nodes.find((n) => n.id === selectedId) ?? nodes[0];
    if (!center) return [];
    const rest = nodes.filter((n) => n.id !== center.id);
    const ring1 = rest.filter((n) => n.depth <= 1).sort((a, b) => (a.id < b.id ? -1 : 1));
    const ring2 = rest.filter((n) => n.depth > 1).sort((a, b) => (a.id < b.id ? -1 : 1));
    const out: PlacedNode[] = [{ ...center, x: 0, y: 0 }];
    ring1.forEach((n, i) => {
      const a = (2 * Math.PI * i) / Math.max(1, ring1.length) - Math.PI / 2;
      out.push({ ...n, x: RING_1 * Math.cos(a), y: RING_1 * Math.sin(a) });
    });
    ring2.forEach((n, i) => {
      const a = (2 * Math.PI * i) / Math.max(1, ring2.length) - Math.PI / 2 + 0.3;
      out.push({ ...n, x: RING_2 * Math.cos(a), y: RING_2 * Math.sin(a) });
    });
    return out;
  }, [nodes, selectedId]);

  const byId = useMemo(() => new Map(placed.map((n) => [n.id, n])), [placed]);

  const zoomIn = () => setZoom((k) => Math.min(3, +(k * 1.25).toFixed(2)));
  const zoomOut = () => setZoom((k) => Math.max(0.5, +(k / 1.25).toFixed(2)));
  const reset = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  const onPointerDown = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    dragRef.current = { x: pan.x, y: pan.y, px: e.clientX, py: e.clientY };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const scale = 400 / zoom / Math.max(1, rect.width);
    setPan({ x: d.x - (e.clientX - d.px) * scale, y: d.y - (e.clientY - d.py) * scale });
  };
  const onPointerUp = () => {
    dragRef.current = null;
  };

  const vbW = 400 / zoom;
  const vbH = 320 / zoom;

  return (
    <div className={clsx("flex flex-col", className)}>
      <div className="mb-2 flex items-center gap-1">
        <span className="meta-text mr-auto">
          {nodes.length} shown · drag to pan
        </span>
        <button type="button" onClick={zoomIn} aria-label="Zoom in"
          className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">+</button>
        <button type="button" onClick={zoomOut} aria-label="Zoom out"
          className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">−</button>
        <button type="button" onClick={reset} aria-label="Reset view"
          className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">Reset</button>
      </div>
      <svg
        ref={svgRef}
        viewBox={`${-200 / zoom + pan.x} ${-160 / zoom + pan.y} ${vbW} ${vbH}`}
        className="h-[300px] w-full touch-none select-none rounded-xl border border-slate-200 bg-white lg:h-[420px] dark:border-slate-800 dark:bg-surface-dark-2"
        role="img"
        aria-label={`Relationship graph: ${nodes.length} entities, ${edges.length} relationships around the selected entity.`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        <defs>
          <marker id="kg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 1 L 9 5 L 0 9" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-slate-400 dark:text-slate-500" />
          </marker>
        </defs>
        {edges.map((e) => {
          const a = byId.get(e.source);
          const b = byId.get(e.target);
          if (!a || !b) return null;
          return (
            <line
              key={e.id}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              className="stroke-slate-300 dark:stroke-slate-600"
              strokeWidth={1.2}
              markerEnd="url(#kg-arrow)"
            >
              <title>{e.type}: {a.label} → {b.label}</title>
            </line>
          );
        })}
        {placed.map((n) => {
          const selected = n.id === selectedId;
          const highlighted = highlightedIds?.has(n.id) ?? false;
          const r = n.depth === 0 ? 17 : 13;
          return (
            <g
              key={n.id}
              transform={`translate(${n.x},${n.y})`}
              role="button"
              tabIndex={0}
              aria-label={`${n.label}, ${n.type}${selected ? ", selected" : ""}`}
              aria-pressed={selected}
              className="cursor-pointer focus:outline-none"
              onClick={() => onSelectNode(n.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelectNode(n.id);
                }
              }}
            >
              <title>{`${n.label} (${n.type})`}</title>
              <circle
                r={r}
                strokeWidth={selected ? 3 : highlighted ? 2.5 : 1.5}
                className={clsx(
                  TYPE_TONES[n.type] ?? DEFAULT_TONE,
                  selected && "stroke-brand-700 dark:stroke-brand-300",
                  !selected && highlighted && "stroke-amber-500",
                  "focus-visible:stroke-brand-500 focus-visible:stroke-[3px]"
                )}
              />
              <text y={r + 13} textAnchor="middle" fontSize={11} fontWeight={selected ? 700 : 500}
                className="fill-slate-800 dark:fill-slate-100">
                {n.label.length > 18 ? `${n.label.slice(0, 17)}…` : n.label}
              </text>
              <text y={r + 25} textAnchor="middle" fontSize={9}
                className="fill-slate-500 dark:fill-slate-400">
                {n.type}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
