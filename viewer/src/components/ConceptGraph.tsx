import {
  memo,
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

interface GraphViewport {
  panX: number;
  panY: number;
  zoom: number;
}


/* ---------- Constants ---------- */

const SVG_HEIGHT = 560;
const NODE_RADIUS = 14;
const LARGE_GRAPH_THRESHOLD = 200;
const VERY_LARGE_GRAPH_THRESHOLD = 500;
const EXTREMELY_LARGE_GRAPH_THRESHOLD = 1000;
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
    stroke: 'var(--graph-rationale-stroke, var(--warning))',
    badge: 'var(--graph-rationale-badge, var(--warning))',
  },
  function: {
    fill: 'var(--graph-code-fill, #F4E4D9)',
    stroke: 'var(--graph-code-stroke, #D27050)',
    badge: 'var(--graph-code-badge, #D27050)',
  },
  class: {
    fill: 'var(--graph-rationale-fill, #F7EED9)',
    stroke: 'var(--graph-rationale-stroke, var(--warning))',
    badge: 'var(--graph-rationale-badge, var(--warning))',
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

function formatGraphTransform(viewport: GraphViewport): string {
  return `translate(${viewport.panX}, ${viewport.panY}) scale(${viewport.zoom})`;
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
  const radius = Math.max(NODE_RADIUS * 6, Math.sqrt(nodes.length) * (NODE_RADIUS + 10));
  return nodes.map((node, index) => {
    const angle = (2 * Math.PI * index) / nodes.length - Math.PI / 2;
    return {
      id: node.id,
      name: node.name,
      kind: node.kind,
      file_path: node.file_path,
      freshness: node.freshness,
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * radius,
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

/**
 * Strip absolute home/system path prefix from a file path so the UI never
 * leaks the user's username or local FS layout. Recognizes:
 *   - POSIX home: `/Users/<name>/...`, `/home/<name>/...`, `/root/...`
 *   - Windows home: `C:\Users\<name>\...`, `C:/Users/<name>/...`
 *   - Generic absolute roots — falls back to last 3 path segments.
 * Repo-relative paths (no leading `/` or drive letter) pass through unchanged.
 */
function shortenFilePath(filePath: string): string {
  if (!filePath) return filePath;
  const normalized = filePath.replace(/\\/g, '/');
  // Bare home root without child content — redact entirely
  if (/^\/(?:Users|home)\/[^/]+\/?$/.test(normalized)) return '~';
  if (/^\/root\/?$/.test(normalized)) return '~';
  if (/^[A-Za-z]:\/Users\/[^/]+\/?$/.test(normalized)) return '~';
  // POSIX home patterns: /Users/<name>/..., /home/<name>/...
  const posixHome = normalized.match(/^\/(?:Users|home)\/[^/]+\/(.+)$/);
  if (posixHome) return posixHome[1];
  const rootHome = normalized.match(/^\/root\/(.+)$/);
  if (rootHome) return rootHome[1];
  // Windows: C:/Users/<name>/...
  const winHome = normalized.match(/^[A-Za-z]:\/Users\/[^/]+\/(.+)$/);
  if (winHome) return winHome[1];
  // Other absolute paths: keep last 3 segments to avoid leaking arbitrary roots.
  if (normalized.startsWith('/') || /^[A-Za-z]:\//.test(normalized)) {
    const parts = normalized.split('/').filter(Boolean);
    if (parts.length > 3) return parts.slice(-3).join('/');
    return parts.join('/');
  }
  return filePath;
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
  const viewportFrameRef = useRef<number | null>(null);
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [simEdges, setSimEdges] = useState<SimEdge[]>([]);
  const [svgWidth, setSvgWidth] = useState(640);
  const titleId = useId();
  const prefersReducedMotion = usePrefersReducedMotion();

  const viewportRef = useRef<GraphViewport>({ panX: 0, panY: 0, zoom: 1 });
  const dragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const applyViewportTransform = useCallback(() => {
    viewportFrameRef.current = null;
    gRef.current?.setAttribute('transform', formatGraphTransform(viewportRef.current));
  }, []);

  const scheduleViewportTransform = useCallback(() => {
    if (viewportFrameRef.current !== null) return;
    viewportFrameRef.current = window.requestAnimationFrame(applyViewportTransform);
  }, [applyViewportTransform]);

  const setViewport = useCallback((next: GraphViewport) => {
    viewportRef.current = next;
    scheduleViewportTransform();
  }, [scheduleViewportTransform]);

  const suspendSimulation = useCallback(() => {
    simulationRef.current?.stop();
    if (animationFrameRef.current !== null) {
      window.cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
  }, []);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const viewport = viewportRef.current;
      const factor = e.deltaY > 0 ? 0.9 : 1.1;
      const newZ = viewport.zoom * factor;
      if (!Number.isFinite(newZ) || newZ <= 0) return;
      setViewport({
        panX: mx - (mx - viewport.panX) * (newZ / viewport.zoom),
        panY: my - (my - viewport.panY) * (newZ / viewport.zoom),
        zoom: newZ,
      });
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onWheel);
  }, [setViewport]);

  useEffect(() => {
    if (viewBoxOverride == null) return;
    viewportRef.current = { panX: 0, panY: 0, zoom: 1 };
    gRef.current?.setAttribute('transform', formatGraphTransform(viewportRef.current));
  }, [viewBoxOverride]);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if ((e.target as Element).closest('.concept-graph__node')) return;
    const svg = svgRef.current;
    if (!svg) return;
    svg.setPointerCapture(e.pointerId);
    suspendSimulation();
    const viewport = viewportRef.current;
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      panX: viewport.panX,
      panY: viewport.panY,
    };
    setIsDragging(true);
  }, [suspendSimulation]);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    setViewport({
      panX: dragRef.current.panX + dx,
      panY: dragRef.current.panY + dy,
      zoom: viewportRef.current.zoom,
    });
  }, [setViewport]);

  const handlePointerUp = useCallback(() => {
    dragRef.current = null;
    setIsDragging(false);
  }, []);

  useEffect(() => {
    return () => {
      if (viewportFrameRef.current !== null) {
        window.cancelAnimationFrame(viewportFrameRef.current);
        viewportFrameRef.current = null;
      }
    };
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
    const initialSpread = Math.max(100, Math.sqrt(nodes.length) * NODE_RADIUS * 4);
    const sNodes: SimNode[] = nodes.map((n) => ({
      id: n.id,
      name: n.name,
      kind: n.kind,
      file_path: n.file_path,
      freshness: n.freshness,
      x: w / 2 + (Math.random() - 0.5) * initialSpread,
      y: SVG_HEIGHT / 2 + (Math.random() - 0.5) * initialSpread,
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

  const handleNodeClick = useCallback(
    (e: React.MouseEvent<SVGGElement>) => {
      const id = e.currentTarget.dataset.nodeId;
      if (!id) return;
      onSelectNode(selectedId === id ? null : id);
    },
    [onSelectNode, selectedId],
  );

  const handleNodeKeyDown = useCallback(
    (e: React.KeyboardEvent<SVGGElement>) => {
      if (e.key === 'Enter' || e.key === ' ') {
        const id = e.currentTarget.dataset.nodeId;
        if (!id) return;
        e.preventDefault();
        onSelectNode(selectedId === id ? null : id);
      }
    },
    [onSelectNode, selectedId],
  );

  const transform = formatGraphTransform(viewportRef.current);

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
      onPointerCancel={handlePointerUp}
      style={{ cursor: isDragging ? 'grabbing' : 'grab', touchAction: 'none' }}
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
              data-node-id={node.id}
              className={`concept-graph__node${isSelected ? ' concept-graph__node--selected' : ''}`}
              tabIndex={0}
              role="button"
              aria-pressed={isSelected}
              aria-label={node.name}
              onClick={handleNodeClick}
              onKeyDown={handleNodeKeyDown}
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
          <code className="concept-graph__detail-code">{shortenFilePath(node.file_path)}</code>
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
  const handleChipClick = useCallback(
    (e: React.MouseEvent<HTMLButtonElement>) => {
      const kind = e.currentTarget.dataset.kind;
      if (!kind) return;
      onToggle(kind);
    },
    [onToggle],
  );
  if (kinds.length <= 1) return null;

  return (
    <div className="concept-graph__filters" role="group" aria-label={t('Graph.filter')}>
      {kinds.map((k) => (
        <button
          key={k}
          type="button"
          data-kind={k}
          className={`concept-graph__filter-chip${active.has(k) ? ' concept-graph__filter-chip--active' : ''}`}
          onClick={handleChipClick}
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
  const handleNodeClick = useCallback(
    (e: React.MouseEvent<HTMLButtonElement>) => {
      const id = e.currentTarget.dataset.nodeId;
      if (!id) return;
      onSelectNode(id);
    },
    [onSelectNode],
  );
  return (
    <div className="concept-graph__listg">
      {nodes.map((n) => (
        <button
          key={n.id}
          type="button"
          data-node-id={n.id}
          className="concept-graph__lnode"
          onClick={handleNodeClick}
        >
          <span className="concept-graph__lnode-name">{n.name}</span>
          {n.kind && (
            <span className="concept-graph__lnode-kind" style={kindColorStyle(n.kind)}>
              {n.kind}
            </span>
          )}
          {n.file_path && (
            <span className="concept-graph__lnode-file">{shortenFilePath(n.file_path)}</span>
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

function ConceptGraph({ nodes, edges, status, truncated, onShowAll }: ConceptGraphProps) {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeKinds, setActiveKinds] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<'graph' | 'list'>(
    nodes.length > LARGE_GRAPH_THRESHOLD ? 'list' : 'graph',
  );
  const [viewBoxOverride, setViewBoxOverride] = useState<string | null>(null);
  const [allowExtremeGraphRender, setAllowExtremeGraphRender] = useState(false);
  const graphWrapRef = useRef<HTMLDivElement>(null);

  const handleFit = useCallback(() => {
    const svg = graphWrapRef.current?.querySelector('svg');
    if (!svg) return;
    const graphLayer = svg.querySelector<SVGGElement>('g');
    let bbox: DOMRect;
    try {
      bbox = (graphLayer ?? svg).getBBox();
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
    const nextViewBox = `${bbox.x - pad} ${bbox.y - pad} ${bbox.width + pad * 2} ${bbox.height + pad * 2}`;
    setViewBoxOverride(null);
    window.requestAnimationFrame(() => setViewBoxOverride(nextViewBox));
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
    setAllowExtremeGraphRender(false);
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
  const isExtremelyLargeGraph = filteredNodes.length >= EXTREMELY_LARGE_GRAPH_THRESHOLD;
  const shouldBlockExtremeGraph =
    viewMode === 'graph' && isExtremelyLargeGraph && !allowExtremeGraphRender;

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
            onClick={() => {
              setAllowExtremeGraphRender(false);
              setViewMode('graph');
            }}
            aria-pressed={viewMode === 'graph'}
          >
            {t('Concept.mode_full')}
          </button>
          <button
            type="button"
            className={`concept-graph__view-btn${viewMode === 'list' ? ' concept-graph__view-btn--active' : ''}`}
            onClick={() => {
              setAllowExtremeGraphRender(false);
              setViewMode('list');
            }}
            aria-pressed={viewMode === 'list'}
          >
            {t('Concept.mode_learning_only')}
          </button>
        </div>
        {viewMode === 'graph' && !shouldBlockExtremeGraph && (
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
            <>
              {shouldBlockExtremeGraph ? (
                <div
                  className="concept-graph__large-warning concept-graph__large-warning--severe"
                  role="status"
                  aria-live="polite"
                >
                  <span className="concept-graph__large-warning-text">
                    {t('Concept.very_large_graph_warning', {
                      count: String(filteredNodes.length),
                    })}
                  </span>
                  <button
                    type="button"
                    className="concept-graph__large-warning-action"
                    onClick={() => setViewMode('list')}
                  >
                    {t('Concept.switch_to_list')}
                  </button>
                  <button
                    type="button"
                    className="concept-graph__large-warning-action"
                    onClick={() => setAllowExtremeGraphRender(true)}
                  >
                    {t('Concept.render_anyway')}
                  </button>
                </div>
              ) : filteredNodes.length >= VERY_LARGE_GRAPH_THRESHOLD ? (
                <div
                  className="concept-graph__large-warning"
                  role="status"
                  aria-live="polite"
                >
                  <span className="concept-graph__large-warning-text">
                    {t('Concept.large_graph_warning', {
                      count: String(filteredNodes.length),
                    })}
                  </span>
                  <button
                    type="button"
                    className="concept-graph__large-warning-action"
                    onClick={() => setViewMode('list')}
                  >
                    {t('Concept.switch_to_list')}
                  </button>
                </div>
              ) : null}
              {!shouldBlockExtremeGraph && (
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
              )}
            </>
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

export default memo(ConceptGraph);
