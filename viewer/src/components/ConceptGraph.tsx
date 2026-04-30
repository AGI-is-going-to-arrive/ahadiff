import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
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
import './ConceptGraph.css';

/* ---------- Public types ---------- */

export interface ConceptGraphProps {
  nodes: ConceptGraphNode[];
  edges: ConceptGraphEdge[];
  status: GraphStatusResponse;
  truncated: boolean;
}

/* ---------- Simulation types ---------- */

interface SimNode extends SimulationNodeDatum {
  id: string;
  name: string;
  kind: string | null;
  file_path: string | null;
  freshness: FreshnessProjection | null;
  metadata: Record<string, unknown>;
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

const KIND_COLORS: Record<string, string> = {
  function: 'var(--accent)',
  class: 'var(--success)',
  module: 'var(--warning)',
  variable: 'var(--info)',
  type: 'var(--danger)',
};
const DEFAULT_COLOR = 'var(--accent-soft)';

function kindColor(kind: string | null): string {
  if (!kind) return DEFAULT_COLOR;
  return KIND_COLORS[kind.toLowerCase()] ?? DEFAULT_COLOR;
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

/* ---------- Force graph SVG ---------- */

function ForceGraph({
  nodes,
  edges,
  onSelectNode,
  selectedId,
}: {
  nodes: ConceptGraphNode[];
  edges: ConceptGraphEdge[];
  onSelectNode: (id: string | null) => void;
  selectedId: string | null;
}) {
  const { t } = useTranslation();
  const svgRef = useRef<SVGSVGElement>(null);
  const simulationRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null);
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [simEdges, setSimEdges] = useState<SimEdge[]>([]);
  const [svgWidth, setSvgWidth] = useState(640);
  const tooltipId = useId();

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
    const w = svgWidth;
    const sNodes: SimNode[] = nodes.map((n) => ({
      id: n.id,
      name: n.name,
      kind: n.kind,
      file_path: n.file_path,
      freshness: n.freshness,
      metadata: n.metadata,
      x: w / 2 + (Math.random() - 0.5) * 100,
      y: SVG_HEIGHT / 2 + (Math.random() - 0.5) * 100,
    }));

    const sEdges: SimEdge[] = edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      relation: e.relation,
      weight: e.weight,
    }));

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
          .strength((l) => (l as { weight: number }).weight * 0.3),
      )
      .force('charge', forceManyBody().strength(-120))
      .force('center', forceCenter(w / 2, SVG_HEIGHT / 2))
      .force('collide', forceCollide(NODE_RADIUS + 4))
      .alphaDecay(0.03);

    simulationRef.current = simulation;

    simulation.on('tick', () => {
      const curW = svgRef.current?.getBoundingClientRect().width ?? w;
      for (const n of sNodes) {
        n.x = Math.max(NODE_RADIUS, Math.min(curW - NODE_RADIUS, n.x ?? 0));
        n.y = Math.max(NODE_RADIUS, Math.min(SVG_HEIGHT - NODE_RADIUS, n.y ?? 0));
      }
      setSimNodes([...sNodes]);
      setSimEdges([...sEdges]);
    });

    return () => {
      simulation.stop();
      simulationRef.current = null;
    };
  }, [nodes, edges]); // svgWidth intentionally excluded — resize handled below

  useEffect(() => {
    const sim = simulationRef.current;
    if (sim) {
      sim.force('center', forceCenter(svgWidth / 2, SVG_HEIGHT / 2));
      sim.alpha(0.1).restart();
    }
  }, [svgWidth]);

  const nodeById = useMemo(() => {
    const m = new Map<string, SimNode>();
    for (const n of simNodes) m.set(n.id, n);
    return m;
  }, [simNodes]);

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

  return (
    <svg
      ref={svgRef}
      className="concept-graph__svg"
      viewBox={`0 0 ${svgWidth} ${SVG_HEIGHT}`}
      role="graphics-document"
      aria-label={t('Concept.title')}
      onKeyDown={handleKeyDown}
    >
      {simEdges.map((edge) => {
        const s = nodeById.get(edge.source);
        const t = nodeById.get(edge.target);
        if (!s || !t) return null;
        const isHighlighted =
          selectedId != null && (edge.source === selectedId || edge.target === selectedId);
        return (
          <line
            key={edge.id}
            className={`concept-graph__edge${isHighlighted ? ' concept-graph__edge--highlight' : ''}`}
            x1={s.x ?? 0}
            y1={s.y ?? 0}
            x2={t.x ?? 0}
            y2={t.y ?? 0}
            strokeWidth={Math.max(1, Math.min(3, edge.weight))}
          />
        );
      })}

      {simNodes.map((node) => {
        const isSelected = selectedId === node.id;
        const titleId = `${tooltipId}-${node.id}`;
        return (
          <g
            key={node.id}
            className={`concept-graph__node${isSelected ? ' concept-graph__node--selected' : ''}`}
            tabIndex={0}
            role="button"
            aria-pressed={isSelected}
            aria-labelledby={titleId}
            onClick={() => onSelectNode(isSelected ? null : node.id)}
            onKeyDown={(e) => handleNodeKeyDown(e, node.id)}
          >
            <title id={titleId}>{node.name}</title>
            <circle
              className="concept-graph__circle"
              cx={node.x ?? 0}
              cy={node.y ?? 0}
              r={NODE_RADIUS}
              style={{ fill: kindColor(node.kind) }}
            />
            <text className="concept-graph__label" x={node.x ?? 0} y={node.y ?? 0}>
              {truncateLabel(node.name, 10)}
            </text>
          </g>
        );
      })}
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
            style={{ background: kindColor(node.kind) }}
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
            {t(`Graph.freshness_${node.freshness}` as 'Graph.freshness')}
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
            style={{ background: kindColor(k) }}
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
            style={{ background: kindColor(k) }}
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
            <span className="concept-graph__lnode-kind" style={{ color: kindColor(n.kind) }}>
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

/* ---------- Graphify source card ---------- */

function SourceCard({ status }: { status: GraphStatusResponse }) {
  const { t } = useTranslation();
  if (!status.has_graph) return null;

  return (
    <div className="concept-graph__src-card">
      <div className="concept-graph__src-card-header">
        <span aria-hidden="true">◈</span>
        <span>{t('Graph.source_title')}</span>
        {status.freshness && (
          <span className={`concept-graph__freshness concept-graph__freshness--${status.freshness}`}>
            {t(`Graph.freshness_${status.freshness}` as 'Graph.freshness')}
          </span>
        )}
      </div>
      <div className="concept-graph__src-card-stats">
        {t('Graph.node_count', { count: String(status.node_count) })} ·{' '}
        {t('Graph.edge_count', { count: String(status.edge_count) })}
      </div>
      {status.source_path && (
        <code className="concept-graph__src-card-path">{status.source_path}</code>
      )}
    </div>
  );
}

/* ---------- Empty state ---------- */

function EmptyState() {
  const { t } = useTranslation();

  return (
    <div className="concept-graph__empty" role="status">
      <span className="concept-graph__empty-icon" aria-hidden="true">◇</span>
      <span className="concept-graph__empty-text">{t('Concept.empty')}</span>
    </div>
  );
}

/* ---------- Main component ---------- */

export default function ConceptGraph({ nodes, edges, status, truncated }: ConceptGraphProps) {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeKinds, setActiveKinds] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<'graph' | 'list'>(
    nodes.length > LARGE_GRAPH_THRESHOLD ? 'list' : 'graph',
  );

  const allKinds = useMemo(() => collectKinds(nodes), [nodes]);

  useEffect(() => {
    setActiveKinds(new Set());
    setSelectedId(null);
  }, [nodes]);

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

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedId) ?? null,
    [nodes, selectedId],
  );

  const handleToggleKind = useCallback((kind: string) => {
    setActiveKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }, []);

  if (!status.has_graph || nodes.length === 0) {
    return (
      <div className="concept-graph">
        <EmptyState />
      </div>
    );
  }

  return (
    <div className="concept-graph">
      <SourceCard status={status} />

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
      </div>

      <div className={`concept-graph__body${selectedNode ? ' concept-graph__body--with-panel' : ''}`}>
        <div className="concept-graph__main">
          {viewMode === 'graph' ? (
            <div className="concept-graph__graph-wrap">
              <ForceGraph
                nodes={filteredNodes}
                edges={filteredEdges}
                onSelectNode={setSelectedId}
                selectedId={selectedId}
              />
              <Legend kinds={allKinds} />
            </div>
          ) : (
            <ListFallback nodes={filteredNodes} onSelectNode={setSelectedId} />
          )}

          {truncated && (
            <div className="concept-graph__truncated" role="status">
              {t('Graph.truncated', { count: String(status.node_count) })}
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
            edges={edges}
            allNodes={nodes}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  );
}
