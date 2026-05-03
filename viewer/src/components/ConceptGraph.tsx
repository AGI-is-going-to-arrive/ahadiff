import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from 'react';
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationNodeDatum,
} from 'd3-force';
import type {
  ConceptGraphEdge,
  ConceptGraphNode,
  FreshnessProjection,
  GraphStatusResponse,
} from '../api/types';
import { useTranslation } from '../i18n/useTranslation';
import { FRESHNESS_LABEL_KEY } from './freshness-utils';
import GraphifySourceCard from './GraphifySourceCard';
import './GraphifyCard.css';
import './ConceptGraph.css';

/* ---------- Public types ---------- */

export interface ConceptGraphProps {
  nodes: ConceptGraphNode[];
  edges: ConceptGraphEdge[];
  status: GraphStatusResponse;
  truncated: boolean;
  onShowAll?: (() => void) | undefined;
}

/* ---------- Simulation types ---------- */

interface SimNode extends SimulationNodeDatum {
  id: string;
  name: string;
  kind: string | null;
  file_path: string | null;
  freshness: FreshnessProjection | null;
}

interface SimEdge {
  id: string;
  source: string;
  target: string;
  relation: string | null;
  weight: number;
}


/* ---------- Constants ---------- */

const SVG_HEIGHT = 560;
const NODE_RADIUS = 14;
const LARGE_GRAPH_THRESHOLD = 200;
const MIN_EDGE_WEIGHT = 0.1;
const MAX_EDGE_WEIGHT = 3.0;

interface KindPalette {
  fill: string;
  stroke: string;
  badge: string;
}

const KIND_PALETTES: Record<string, KindPalette> = {
  code: {
    fill: 'var(--graph-code-fill, #F4E4D9)',
    stroke: 'var(--graph-code-stroke, #D27050)',
    badge: 'var(--graph-code-badge, #D27050)',
  },
  rationale: {
    fill: 'var(--graph-rationale-fill, #F7EED9)',
    stroke: 'var(--graph-rationale-stroke, #B4791F)',
    badge: 'var(--graph-rationale-badge, #B4791F)',
  },
  function: {
    fill: 'var(--graph-code-fill, #F4E4D9)',
    stroke: 'var(--graph-code-stroke, #D27050)',
    badge: 'var(--graph-code-badge, #D27050)',
  },
  class: {
    fill: 'var(--graph-rationale-fill, #F7EED9)',
    stroke: 'var(--graph-rationale-stroke, #B4791F)',
    badge: 'var(--graph-rationale-badge, #B4791F)',
  },
  module: {
    fill: 'var(--graph-module-fill, #E0E8F0)',
    stroke: 'var(--graph-module-stroke, #2E4A6B)',
    badge: 'var(--graph-module-badge, #2E4A6B)',
  },
  variable: {
    fill: 'var(--accent-softest)',
    stroke: 'var(--accent-tint)',
    badge: 'var(--accent-tint)',
  },
  type: {
    fill: 'var(--danger-soft)',
    stroke: 'var(--danger)',
    badge: 'var(--danger)',
  },
};

const DEFAULT_PALETTE: KindPalette = {
  fill: 'var(--accent-softer)',
  stroke: 'var(--accent-tint)',
  badge: 'var(--accent-soft)',
};

function kindPalette(kind: string | null): KindPalette {
  if (!kind) return DEFAULT_PALETTE;
  return KIND_PALETTES[kind.toLowerCase()] ?? DEFAULT_PALETTE;
}

type GraphColorStyle = CSSProperties & {
  '--concept-kind-fill': string;
  '--concept-kind-stroke': string;
  '--concept-kind-badge': string;
};

function kindColorStyle(kind: string | null): GraphColorStyle {
  const p = kindPalette(kind);
  return {
    '--concept-kind-fill': p.fill,
    '--concept-kind-stroke': p.stroke,
    '--concept-kind-badge': p.badge,
  } as GraphColorStyle;
}


function safeEdgeWeight(weight: number): number {
  if (!Number.isFinite(weight)) return 1.0;
  return Math.min(MAX_EDGE_WEIGHT, Math.max(MIN_EDGE_WEIGHT, weight));
}

function clampNodeToViewport(node: SimNode, width: number): void {
  const maxX = Math.max(NODE_RADIUS, width - NODE_RADIUS);
  const maxY = SVG_HEIGHT - NODE_RADIUS;
  node.x = Math.min(maxX, Math.max(NODE_RADIUS, node.x ?? width / 2));
  node.y = Math.min(maxY, Math.max(NODE_RADIUS, node.y ?? SVG_HEIGHT / 2));
}

function toSimEdges(edges: ConceptGraphEdge[]): SimEdge[] {
  return edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    relation: e.relation,
    weight: safeEdgeWeight(e.weight),
  }));
}

function layoutStaticNodes(nodes: ConceptGraphNode[], width: number): SimNode[] {
  if (nodes.length === 0) return [];
  const safeWidth = Math.max(width, NODE_RADIUS * 2);
  const centerX = safeWidth / 2;
  const centerY = SVG_HEIGHT / 2;
  const radiusX = Math.max(NODE_RADIUS * 2, safeWidth / 2 - NODE_RADIUS * 3);
  const radiusY = Math.max(NODE_RADIUS * 2, SVG_HEIGHT / 2 - NODE_RADIUS * 4);
  return nodes.map((node, index) => {
    const angle = (2 * Math.PI * index) / nodes.length - Math.PI / 2;
    return {
      id: node.id,
      name: node.name,
      kind: node.kind,
      file_path: node.file_path,
      freshness: node.freshness,
      x: centerX + Math.cos(angle) * radiusX,
      y: centerY + Math.sin(angle) * radiusY,
    };
  });
}

function emptyMessageKey(
  status: GraphStatusResponse,
): 'Concept.empty' | 'Graph.empty_disabled' | 'Graph.empty_graph' | 'Graph.empty_source_missing' | 'Graph.empty_unavailable' {
  if (!status.enabled) return 'Graph.empty_disabled';
  if (!status.source_exists) return 'Graph.empty_source_missing';
  if (!status.has_graph) return 'Graph.empty_unavailable';
  if (status.node_count === 0) return 'Graph.empty_graph';
  return 'Concept.empty';
}

function usePrefersReducedMotion(): boolean {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handleChange = () => setPrefersReducedMotion(query.matches);
    handleChange();
    query.addEventListener('change', handleChange);
    return () => query.removeEventListener('change', handleChange);
  }, []);

  return prefersReducedMotion;
}

/* ---------- Filter helpers ---------- */

function collectKinds(nodes: ConceptGraphNode[]): string[] {
  const s = new Set<string>();
  for (const n of nodes) {
    if (n.kind) s.add(n.kind);
  }
  return Array.from(s).sort();
}

/* ---------- Truncate label ---------- */

function truncateLabel(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 1) + '…';
}

function copyComputedProperty(
  target: SVGElement,
  style: CSSStyleDeclaration,
  property: string,
  attribute = property,
): void {
  const value = style.getPropertyValue(property).trim();
  if (value) target.setAttribute(attribute, value);
}

function buildExportSvg(sourceSvg: SVGSVGElement): SVGSVGElement {
  const clone = sourceSvg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('version', '1.1');

  const bounds = sourceSvg.getBoundingClientRect();
  if (Number.isFinite(bounds.width) && bounds.width > 0) {
    clone.setAttribute('width', String(Math.round(bounds.width)));
  }
  if (Number.isFinite(bounds.height) && bounds.height > 0) {
    clone.setAttribute('height', String(Math.round(bounds.height)));
  }

  const sourceElements = Array.from(sourceSvg.querySelectorAll<SVGElement>('line,circle,text'));
  const clonedElements = Array.from(clone.querySelectorAll<SVGElement>('line,circle,text'));
  sourceElements.forEach((source, index) => {
    const target = clonedElements[index];
    if (!target) return;
    const style = window.getComputedStyle(source);
    const tagName = source.tagName.toLowerCase();
    if (tagName === 'line') {
      copyComputedProperty(target, style, 'stroke');
      copyComputedProperty(target, style, 'stroke-width');
      copyComputedProperty(target, style, 'stroke-linecap');
      return;
    }
    if (tagName === 'circle') {
      copyComputedProperty(target, style, 'fill');
      copyComputedProperty(target, style, 'stroke');
      copyComputedProperty(target, style, 'stroke-width');
      return;
    }
    if (tagName === 'text') {
      copyComputedProperty(target, style, 'fill');
      copyComputedProperty(target, style, 'font-family');
      copyComputedProperty(target, style, 'font-size');
      copyComputedProperty(target, style, 'font-weight');
      copyComputedProperty(target, style, 'text-anchor');
      copyComputedProperty(target, style, 'dominant-baseline');
    }
  });

  return clone;
}

/* ---------- Force graph SVG ---------- */

function ForceGraph({
  nodes,
  edges,
  onSelectNode,
  selectedId,
  viewBoxOverride,
}: {
  nodes: ConceptGraphNode[];
  edges: ConceptGraphEdge[];
  onSelectNode: (id: string | null) => void;
  selectedId: string | null;
  viewBoxOverride: string | null;
}) {
  const { t } = useTranslation();
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);
  const simulationRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [simEdges, setSimEdges] = useState<SimEdge[]>([]);
  const [svgWidth, setSvgWidth] = useState(640);
  const titleId = useId();
  const prefersReducedMotion = usePrefersReducedMotion();

  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const panRef = useRef(pan);
  const zoomRef = useRef(zoom);
  panRef.current = pan;
  zoomRef.current = zoom;
  const dragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const oldZ = zoomRef.current;
      const factor = e.deltaY > 0 ? 0.9 : 1.1;
      const newZ = Math.min(5, Math.max(0.1, oldZ * factor));
      const p = panRef.current;
      setPan({
        x: mx - (mx - p.x) * (newZ / oldZ),
        y: my - (my - p.y) * (newZ / oldZ),
      });
      setZoom(newZ);
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onWheel);
  }, []);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if ((e.target as Element).closest('.concept-graph__node')) return;
    const svg = svgRef.current;
    if (!svg) return;
    svg.setPointerCapture(e.pointerId);
    dragRef.current = { startX: e.clientX, startY: e.clientY, panX: pan.x, panY: pan.y };
  }, [pan]);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    setPan({ x: dragRef.current.panX + dx, y: dragRef.current.panY + dy });
  }, []);

  const handlePointerUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setSvgWidth(entry.contentRect.width);
      }
    });
    observer.observe(svg);
    setSvgWidth(svg.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!prefersReducedMotion) return;
    simulationRef.current?.stop();
    simulationRef.current = null;
    setSimNodes(layoutStaticNodes(nodes, svgWidth));
    setSimEdges(toSimEdges(edges));
  }, [edges, nodes, prefersReducedMotion, svgWidth]);

  useEffect(() => {
    if (prefersReducedMotion) return;
    const w = svgWidth;
    const sNodes: SimNode[] = nodes.map((n) => ({
      id: n.id,
      name: n.name,
      kind: n.kind,
      file_path: n.file_path,
      freshness: n.freshness,
      x: w / 2 + (Math.random() - 0.5) * 100,
      y: SVG_HEIGHT / 2 + (Math.random() - 0.5) * 100,
    }));

    const sEdges: SimEdge[] = toSimEdges(edges);

    const nodeMap = new Map(sNodes.map((n) => [n.id, n]));

    const linkData = sEdges
      .filter((e) => nodeMap.has(e.source) && nodeMap.has(e.target))
      .map((e) => ({
        source: e.source,
        target: e.target,
        weight: e.weight,
      }));

    const simulation = forceSimulation(sNodes)
      .force(
        'link',
        forceLink(linkData)
          .id((d) => (d as SimNode).id)
          .distance(80)
          .strength((l) => Math.min(1, (l as { weight: number }).weight * 0.3)),
      )
      .force('charge', forceManyBody().strength(-120))
      .force('center', forceCenter(w / 2, SVG_HEIGHT / 2))
      .force('collide', forceCollide(NODE_RADIUS + 4))
      .alphaDecay(0.03);

    simulationRef.current = simulation;
    setSimNodes([...sNodes]);
    setSimEdges([...sEdges]);

    const flushNodePositions = () => {
      animationFrameRef.current = null;
      setSimNodes([...sNodes]);
    };

    simulation.on('tick', () => {
      for (const node of sNodes) clampNodeToViewport(node, w);
      if (animationFrameRef.current === null) {
        animationFrameRef.current = window.requestAnimationFrame(flushNodePositions);
      }
    });

    return () => {
      simulation.stop();
      simulationRef.current = null;
      if (animationFrameRef.current !== null) {
        window.cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };
  }, [nodes, edges, prefersReducedMotion, svgWidth]);

  useEffect(() => {
    if (prefersReducedMotion) return;
    const sim = simulationRef.current;
    if (sim) {
      sim.force('center', forceCenter(svgWidth / 2, SVG_HEIGHT / 2));
      sim.alpha(0.1).restart();
    }
  }, [prefersReducedMotion, svgWidth]);

  const nodeById = useMemo(() => {
    const m = new Map<string, SimNode>();
    for (const n of simNodes) m.set(n.id, n);
    return m;
  }, [simNodes]);

  const connectedIds = useMemo(() => {
    if (selectedId == null) return null;
    const ids = new Set<string>([selectedId]);
    for (const e of simEdges) {
      if (e.source === selectedId) ids.add(e.target);
      if (e.target === selectedId) ids.add(e.source);
    }
    return ids;
  }, [selectedId, simEdges]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') onSelectNode(null);
    },
    [onSelectNode],
  );

  const handleNodeKeyDown = useCallback(
    (e: React.KeyboardEvent, id: string) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onSelectNode(selectedId === id ? null : id);
      }
    },
    [onSelectNode, selectedId],
  );

  const transform = `translate(${pan.x}, ${pan.y}) scale(${zoom})`;

  return (
    <svg
      ref={svgRef}
      className="concept-graph__svg"
      viewBox={viewBoxOverride ?? `0 0 ${svgWidth} ${SVG_HEIGHT}`}
      role="graphics-document"
      aria-labelledby={titleId}
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
      style={{ cursor: dragRef.current ? 'grabbing' : 'grab', touchAction: 'none' }}
    >
      <title id={titleId}>{t('Concept.title')}</title>
      <g ref={gRef} transform={transform}>
        {simEdges.map((edge) => {
          const s = nodeById.get(edge.source);
          const tgt = nodeById.get(edge.target);
          if (!s || !tgt) return null;
          const isHighlighted =
            selectedId != null && (edge.source === selectedId || edge.target === selectedId);
          const isDimmed = connectedIds != null && !isHighlighted;
          return (
            <line
              key={edge.id}
              className={`concept-graph__edge${isHighlighted ? ' concept-graph__edge--highlight' : ''}`}
              x1={s.x ?? 0}
              y1={s.y ?? 0}
              x2={tgt.x ?? 0}
              y2={tgt.y ?? 0}
              strokeWidth={Math.max(1, Math.min(3, edge.weight))}
              opacity={isDimmed ? 0.08 : 1}
            />
          );
        })}

        {simNodes.map((node) => {
          const isSelected = selectedId === node.id;
          const isDimmed = connectedIds != null && !connectedIds.has(node.id);
          return (
            <g
              key={node.id}
              className={`concept-graph__node${isSelected ? ' concept-graph__node--selected' : ''}`}
              tabIndex={0}
              role="button"
              aria-pressed={isSelected}
              aria-label={node.name}
              onClick={() => onSelectNode(isSelected ? null : node.id)}
              onKeyDown={(e) => handleNodeKeyDown(e, node.id)}
              opacity={isDimmed ? 0.12 : 1}
            >
              <title>{node.name}</title>
              <circle
                className="concept-graph__circle"
                cx={node.x ?? 0}
                cy={node.y ?? 0}
                r={NODE_RADIUS}
                style={kindColorStyle(node.kind)}
              />
              <text className="concept-graph__label" x={node.x ?? 0} y={node.y ?? 0}>
                {truncateLabel(node.name, 10)}
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

/* ---------- Detail panel ---------- */

function DetailPanel({
  node,
  edges,
  allNodes,
  onClose,
}: {
  node: ConceptGraphNode;
  edges: ConceptGraphEdge[];
  allNodes: ConceptGraphNode[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const nodeMap = useMemo(() => new Map(allNodes.map((n) => [n.id, n])), [allNodes]);

  const connected = useMemo(() => {
    const ids = new Set<string>();
    for (const e of edges) {
      if (e.source === node.id) ids.add(e.target);
      if (e.target === node.id) ids.add(e.source);
    }
    return Array.from(ids)
      .map((id) => nodeMap.get(id))
      .filter((n): n is ConceptGraphNode => n != null);
  }, [edges, node.id, nodeMap]);

  return (
    <aside className="concept-graph__detail" role="complementary" aria-label={node.name}>
      <div className="concept-graph__detail-header">
        <h3 className="concept-graph__detail-name">{node.name}</h3>
        <button
          type="button"
          className="concept-graph__detail-close"
          onClick={onClose}
          aria-label={t('A11y.close')}
        >
          ✕
        </button>
      </div>

      {node.kind && (
        <div className="concept-graph__detail-row">
          <span className="concept-graph__detail-label">{t('Graph.kind')}</span>
          <span
            className="concept-graph__kind-badge"
            style={kindColorStyle(node.kind)}
          >
            {node.kind}
          </span>
        </div>
      )}

      {node.file_path && (
        <div className="concept-graph__detail-row">
          <span className="concept-graph__detail-label">{t('Graph.file')}</span>
          <code className="concept-graph__detail-code">{node.file_path}</code>
        </div>
      )}

      {node.freshness && (
        <div className="concept-graph__detail-row">
          <span className="concept-graph__detail-label">{t('Graph.freshness')}</span>
          <span className={`concept-graph__freshness concept-graph__freshness--${node.freshness}`}>
            {t(FRESHNESS_LABEL_KEY[node.freshness])}
          </span>
        </div>
      )}

      {connected.length > 0 && (
        <div className="concept-graph__detail-section">
          <span className="concept-graph__detail-label">
            {t('Graph.connected')} ({connected.length})
          </span>
          <ul className="concept-graph__detail-connections">
            {connected.map((c) => (
              <li key={c.id}>{c.name}</li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}

/* ---------- Legend ---------- */

function Legend({ kinds }: { kinds: string[] }) {
  const { t } = useTranslation();
  if (kinds.length === 0) return null;

  return (
    <div className="concept-graph__legend" role="img" aria-label={t('Graph.legend')}>
      <span className="concept-graph__legend-label">{t('Graph.legend')}</span>
      {kinds.map((k) => (
        <span key={k} className="concept-graph__legend-item">
          <span
            className="concept-graph__legend-swatch"
            style={kindColorStyle(k)}
            aria-hidden="true"
          />
          {k}
        </span>
      ))}
    </div>
  );
}

/* ---------- Filter chips ---------- */

function FilterChips({
  kinds,
  active,
  onToggle,
}: {
  kinds: string[];
  active: Set<string>;
  onToggle: (kind: string) => void;
}) {
  const { t } = useTranslation();
  if (kinds.length <= 1) return null;

  return (
    <div className="concept-graph__filters" role="group" aria-label={t('Graph.filter')}>
      {kinds.map((k) => (
        <button
          key={k}
          type="button"
          className={`concept-graph__filter-chip${active.has(k) ? ' concept-graph__filter-chip--active' : ''}`}
          onClick={() => onToggle(k)}
          aria-pressed={active.has(k)}
        >
          <span
            className="concept-graph__filter-swatch"
            style={kindColorStyle(k)}
            aria-hidden="true"
          />
          {k}
        </button>
      ))}
    </div>
  );
}

/* ---------- List fallback (large graphs) ---------- */

function ListFallback({
  nodes,
  onSelectNode,
}: {
  nodes: ConceptGraphNode[];
  onSelectNode: (id: string) => void;
}) {
  return (
    <div className="concept-graph__listg">
      {nodes.map((n) => (
        <button
          key={n.id}
          type="button"
          className="concept-graph__lnode"
          onClick={() => onSelectNode(n.id)}
        >
          <span className="concept-graph__lnode-name">{n.name}</span>
          {n.kind && (
            <span className="concept-graph__lnode-kind" style={kindColorStyle(n.kind)}>
              {n.kind}
            </span>
          )}
          {n.file_path && (
            <span className="concept-graph__lnode-file">{n.file_path}</span>
          )}
        </button>
      ))}
    </div>
  );
}

/* ---------- Filtered-empty state ---------- */

function FilteredEmptyState() {
  const { t } = useTranslation();

  return (
    <div className="concept-graph__empty concept-graph__empty--compact" role="status">
      <span className="concept-graph__empty-icon" aria-hidden="true">◇</span>
      <span className="concept-graph__empty-text">{t('Graph.empty_filtered')}</span>
    </div>
  );
}

/* ---------- Graphify source card (shared presentational component) ---------- */

/* ---------- Empty state ---------- */

function EmptyState({ status }: { status: GraphStatusResponse }) {
  const { t } = useTranslation();

  return (
    <div className="concept-graph__empty" role="status">
      <span className="concept-graph__empty-icon" aria-hidden="true">◇</span>
      <span className="concept-graph__empty-text">{t(emptyMessageKey(status))}</span>
    </div>
  );
}

/* ---------- Main component ---------- */

export default function ConceptGraph({ nodes, edges, status, truncated, onShowAll }: ConceptGraphProps) {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeKinds, setActiveKinds] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<'graph' | 'list'>(
    nodes.length > LARGE_GRAPH_THRESHOLD ? 'list' : 'graph',
  );
  const [viewBoxOverride, setViewBoxOverride] = useState<string | null>(null);
  const graphWrapRef = useRef<HTMLDivElement>(null);

  const handleFit = useCallback(() => {
    const svg = graphWrapRef.current?.querySelector('svg');
    if (!svg) return;
    let bbox: DOMRect;
    try {
      bbox = svg.getBBox();
    } catch {
      return;
    }
    if (
      !Number.isFinite(bbox.x) ||
      !Number.isFinite(bbox.y) ||
      !Number.isFinite(bbox.width) ||
      !Number.isFinite(bbox.height) ||
      bbox.width <= 0 ||
      bbox.height <= 0
    ) {
      return;
    }
    const pad = 40;
    setViewBoxOverride(`${bbox.x - pad} ${bbox.y - pad} ${bbox.width + pad * 2} ${bbox.height + pad * 2}`);
  }, []);

  const handleExport = useCallback(() => {
    const svg = graphWrapRef.current?.querySelector('svg');
    if (!svg) return;
    const serializer = new XMLSerializer();
    const svgStr = serializer.serializeToString(buildExportSvg(svg));
    const blob = new Blob([svgStr], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'concept-graph.svg';
    a.style.display = 'none';
    document.body.appendChild(a);
    try {
      a.click();
    } finally {
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    }
  }, []);

  const allKinds = useMemo(() => collectKinds(nodes), [nodes]);

  useEffect(() => {
    setActiveKinds(new Set());
    setSelectedId(null);
  }, [nodes]);

  useEffect(() => {
    setViewMode(nodes.length > LARGE_GRAPH_THRESHOLD ? 'list' : 'graph');
  }, [nodes.length]);

  const filteredNodes = useMemo(() => {
    if (activeKinds.size === 0) return nodes;
    return nodes.filter((n) => n.kind != null && activeKinds.has(n.kind));
  }, [nodes, activeKinds]);

  const filteredNodeIds = useMemo(
    () => new Set(filteredNodes.map((n) => n.id)),
    [filteredNodes],
  );

  const filteredEdges = useMemo(() => {
    return edges.filter(
      (e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target),
    );
  }, [edges, filteredNodeIds]);

  useEffect(() => {
    setViewBoxOverride(null);
  }, [filteredEdges, filteredNodes, viewMode]);

  const selectedNode = useMemo(
    () => filteredNodes.find((n) => n.id === selectedId) ?? null,
    [filteredNodes, selectedId],
  );

  useEffect(() => {
    if (selectedId != null && !filteredNodeIds.has(selectedId)) {
      setSelectedId(null);
    }
  }, [filteredNodeIds, selectedId]);

  const handleToggleKind = useCallback((kind: string) => {
    setActiveKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }, []);

  useEffect(() => {
    if (selectedId == null) return;
    const handleWindowKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest('[role="dialog"][aria-modal="true"]')) return;
      if (event.key === 'Escape') {
        setSelectedId(null);
      }
    };
    window.addEventListener('keydown', handleWindowKeyDown);
    return () => window.removeEventListener('keydown', handleWindowKeyDown);
  }, [selectedId]);

  if (!status.has_graph || nodes.length === 0) {
    return (
      <div className="concept-graph">
        <EmptyState status={status} />
      </div>
    );
  }

  return (
    <div className="concept-graph">
      <GraphifySourceCard status={status} className="concept-graph__src-card" />

      <div className="concept-graph__toolbar">
        <FilterChips kinds={allKinds} active={activeKinds} onToggle={handleToggleKind} />
        <div className="concept-graph__view-toggle">
          <button
            type="button"
            className={`concept-graph__view-btn${viewMode === 'graph' ? ' concept-graph__view-btn--active' : ''}`}
            onClick={() => setViewMode('graph')}
            aria-pressed={viewMode === 'graph'}
          >
            {t('Concept.mode_full')}
          </button>
          <button
            type="button"
            className={`concept-graph__view-btn${viewMode === 'list' ? ' concept-graph__view-btn--active' : ''}`}
            onClick={() => setViewMode('list')}
            aria-pressed={viewMode === 'list'}
          >
            {t('Concept.mode_learning_only')}
          </button>
        </div>
        {viewMode === 'graph' && (
          <div className="concept-graph__actions">
            <button
              type="button"
              className="concept-graph__action-btn"
              onClick={handleFit}
              aria-label={t('Concept.fit')}
            >
              {t('Concept.fit')}
            </button>
            <button
              type="button"
              className="concept-graph__action-btn"
              onClick={handleExport}
              aria-label={t('Concept.export')}
            >
              {t('Concept.export')}
            </button>
          </div>
        )}
      </div>

      <div className={`concept-graph__body${selectedNode ? ' concept-graph__body--with-panel' : ''}`}>
        <div className="concept-graph__main">
          {filteredNodes.length === 0 ? (
            <FilteredEmptyState />
          ) : viewMode === 'graph' ? (
            <div className="concept-graph__graph-wrap" ref={graphWrapRef}>
              <ForceGraph
                nodes={filteredNodes}
                edges={filteredEdges}
                onSelectNode={setSelectedId}
                selectedId={selectedId}
                viewBoxOverride={viewBoxOverride}
              />
              <Legend kinds={allKinds} />
            </div>
          ) : (
            <ListFallback nodes={filteredNodes} onSelectNode={setSelectedId} />
          )}

          {truncated && (
            <div className="concept-graph__truncated" role="status">
              {t('Graph.truncated', { count: String(status.node_count) })}
              {onShowAll && (
                <button
                  type="button"
                  className="concept-graph__show-all-btn"
                  onClick={onShowAll}
                >
                  {t('Graph.show_all')}
                </button>
              )}
            </div>
          )}

          <div className="concept-graph__counts">
            {t('Graph.showing', {
              shown: String(filteredNodes.length),
              total: String(nodes.length),
            })}
          </div>
        </div>

        {selectedNode && (
          <DetailPanel
            node={selectedNode}
            edges={filteredEdges}
            allNodes={filteredNodes}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  );
}
