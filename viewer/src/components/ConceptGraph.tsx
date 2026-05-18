import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import type {
  ForceGraphMethods,
  GraphData,
  LinkObject,
  NodeObject,
} from 'react-force-graph-2d';
import type {
  ConceptGraphEdge,
  ConceptGraphNode,
  FreshnessProjection,
  GraphStatusResponse,
} from '../api/types';
import { useTranslation } from '../i18n/useTranslation';
import { FRESHNESS_LABEL_KEY } from './freshness-utils';
import GraphifySourceCard from './GraphifySourceCard';
import { OPEN_SEARCH_EVENT, type OpenSearchEventDetail } from './open-search-event';
import './GraphifyCard.css';
import './ConceptGraph.css';

/* ---------- Public types ---------- */

export interface ConceptGraphProps {
  nodes: ConceptGraphNode[];
  edges: ConceptGraphEdge[];
  status: GraphStatusResponse;
  truncated: boolean;
  focusNodeId?: string | null;
  onShowAll?: (() => void) | undefined;
  /**
   * Optional run id used to build cross-view quick links in the detail panel.
   * When provided, per-run links (Diff, Lesson) become available.
   */
  currentRun?: string | undefined;
}

/* ---------- Simulation types ---------- */

interface GraphNode {
  id: string;
  name: string;
  displayLabel: string;
  kind: string | null;
  file_path: string | null;
  freshness: FreshnessProjection | null;
  radius: number;
  degree: number;
  communityFillColor: string;
  kindStrokeColor: string;
}

interface GraphLink {
  id: string;
  source: string;
  target: string;
  relation: string | null;
  weight: number;
}


/* ---------- Constants ---------- */

const GRAPH_CANVAS_HEIGHT = 560;
const NODE_RADIUS_MIN = 4;
const NODE_RADIUS_MAX = 15;
const NODE_RADIUS_BASE = 4;
const LARGE_GRAPH_THRESHOLD = 150;
const VERY_LARGE_GRAPH_THRESHOLD = 300;
const EXTREMELY_LARGE_GRAPH_THRESHOLD = 500;
const LIST_INITIAL_LIMIT = 500;
const MAX_COMMUNITY_FILTER_CHIPS = 50;
const MIN_EDGE_WEIGHT = 0.1;
const MAX_EDGE_WEIGHT = 3.0;
const METADATA_DISPLAY_KEYS = new Set<string>([
  'community',
  'confidence',
  'confidence_score',
  'norm_label',
  'source_location',
  'weight',
]);

interface KindPalette {
  fill: string;
  stroke: string;
  badge: string;
}

/**
 * Botanical editorial palette — 12 de-saturated earth tones.
 * Each carries built-in gray undertone to harmonize with cream (#FAF8F5).
 * code = solid fill, rationale = 15% tint + solid stroke.
 */
const COMMUNITY_COLORS: readonly string[] = [
  '#B85D43', // rust
  '#4A7056', // forest
  '#D4A35C', // mustard
  '#4D6D85', // slate
  '#765C77', // aubergine
  '#CD7253', // terracotta
  '#8B9E7A', // sage
  '#394B61', // indigo
  '#6B705C', // olive
  '#A65746', // burnt orange
  '#3F6366', // teal
  '#A37B7E', // muted rose
];

function communityColor(id: string | number | null): string | null {
  if (id == null) return null;
  const key = String(id);
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }
  return COMMUNITY_COLORS[hash % COMMUNITY_COLORS.length] ?? null;
}


/**
 * Read a node's community id from metadata, normalised to string|null.
 */
function readCommunity(node: ConceptGraphNode): string | null {
  const meta = node.metadata;
  if (!meta || typeof meta !== 'object') return null;
  const v = (meta as Record<string, unknown>).community;
  if (typeof v === 'string' && v.trim()) return v;
  if (typeof v === 'number' && Number.isFinite(v)) return String(v);
  return null;
}

/** Maximum displayed length for a derived community label. */
const COMMUNITY_LABEL_MAX_LEN = 16;

/** Output of {@link deriveCommunityLabel} — label + the source it was derived from. */
interface CommunityLabelInfo {
  /** Truncated label suitable for chip text (≤16 chars, may end with "…"). */
  label: string;
  /** Untruncated source name (basename or node name) used to derive the label, or null when nothing better than the id existed. */
  sourceFile: string | null;
}

interface CommunitySummary extends CommunityLabelInfo {
  count: number;
}

/**
 * Derive a human-meaningful label for a community.
 *
 * Strategy (in order):
 *   1. Use the most common file basename (stripped of extension) among the
 *      community's nodes — this surfaces the dominant module, e.g. `transport`.
 *   2. Fall back to the shortest node name (proxy for class/file root) — short
 *      names tend to be the canonical entity in a cluster.
 *   3. Final fallback: return the raw community id (numeric).
 *
 * The returned `label` is truncated to {@link COMMUNITY_LABEL_MAX_LEN} chars
 * with an ellipsis when needed; `sourceFile` is the untruncated source so
 * tooltips can show the full string.
 */
function deriveCommunityLabel(
  communityId: string,
  nodes: ConceptGraphNode[],
): CommunityLabelInfo {
  const communityNodes = nodes.filter(
    (n) => readCommunity(n) === communityId,
  );
  if (communityNodes.length === 0) {
    return { label: communityId, sourceFile: null };
  }

  // 1) Most common file basename (strip extension).
  const fileCounts = new Map<string, number>();
  for (const n of communityNodes) {
    if (!n.file_path) continue;
    const basename = fileStem(n.file_path);
    if (!basename) continue;
    fileCounts.set(basename, (fileCounts.get(basename) ?? 0) + 1);
  }
  if (fileCounts.size > 0) {
    const sorted = [...fileCounts.entries()].sort((a, b) => b[1] - a[1]);
    const topFile = sorted[0][0];
    return { label: truncateLabel(topFile, COMMUNITY_LABEL_MAX_LEN), sourceFile: topFile };
  }

  // 2) Shortest node name as proxy for canonical entity.
  const sorted = [...communityNodes].sort((a, b) => a.name.length - b.name.length);
  const candidate = sorted[0]?.name;
  if (candidate) {
    return {
      label: truncateLabel(candidate, COMMUNITY_LABEL_MAX_LEN),
      sourceFile: candidate,
    };
  }

  // 3) Numeric id fallback.
  return { label: communityId, sourceFile: null };
}

/**
 * Build adjacency list once for efficient BFS.
 * Each entry maps a node id to the set of directly connected node ids.
 * Self-loops are skipped.
 */
function buildAdjacency(edges: ConceptGraphEdge[]): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>();
  for (const e of edges) {
    if (e.source === e.target) continue;
    let a = adj.get(e.source);
    if (!a) {
      a = new Set<string>();
      adj.set(e.source, a);
    }
    a.add(e.target);
    let b = adj.get(e.target);
    if (!b) {
      b = new Set<string>();
      adj.set(e.target, b);
    }
    b.add(e.source);
  }
  return adj;
}

/**
 * BFS from rootId on a pre-built adjacency map, expanding `maxHops` levels.
 * Result includes `rootId` itself.
 */
function getNeighborsAtHops(
  rootId: string,
  adjacency: Map<string, Set<string>>,
  maxHops: number,
): Set<string> {
  const visited = new Set<string>([rootId]);
  let frontier: string[] = [rootId];
  for (let hop = 0; hop < maxHops && frontier.length > 0; hop += 1) {
    const next: string[] = [];
    for (const id of frontier) {
      const neighbors = adjacency.get(id);
      if (!neighbors) continue;
      for (const nid of neighbors) {
        if (!visited.has(nid)) {
          visited.add(nid);
          next.push(nid);
        }
      }
    }
    frontier = next;
  }
  return visited;
}

const KIND_PALETTES: Record<string, KindPalette> = {
  code:      { fill: '#F4E4D9', stroke: '#D27050', badge: '#B04E28' },
  function:  { fill: '#E8E0F0', stroke: '#6B4E8B', badge: '#553C72' },
  class:     { fill: '#E0E8F0', stroke: '#2E4A6B', badge: '#1E3654' },
  module:    { fill: '#E0EDE4', stroke: '#2F6F4F', badge: '#1E5A3A' },
  rationale: { fill: '#F7EED9', stroke: '#B4791F', badge: '#8B5E18' },
  variable:  { fill: '#FDF1EC', stroke: '#A33D2B', badge: '#8B2E1E' },
  type:      { fill: '#E8EDF2', stroke: '#4A6B8A', badge: '#3A5670' },
  document:  { fill: '#F0EDE8', stroke: '#8E8778', badge: '#6A6456' },
  paper:     { fill: '#F5F0E8', stroke: '#9E8B6E', badge: '#7A6B50' },
  image:     { fill: '#F0E8EE', stroke: '#8B4A7A', badge: '#6E3A60' },
};

const DEFAULT_PALETTE: KindPalette = {
  fill: '#F2EFE7',
  stroke: '#8E8778',
  badge: '#6A6456',
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

/**
 * Compute degree (number of incident edges) for each node id.
 * Self-loops count once.
 */
function computeDegrees(
  nodes: ConceptGraphNode[],
  edges: ConceptGraphEdge[],
): Map<string, number> {
  const degree = new Map<string, number>();
  for (const n of nodes) degree.set(n.id, 0);
  for (const e of edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    if (e.source !== e.target) {
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    }
  }
  return degree;
}

/**
 * Map degree to a node radius using log1p scaling.
 * Range: 4 (leaf) → 15 (hub). Tight, controlled variance.
 */
function radiusForDegree(degree: number): number {
  if (degree <= 0) return NODE_RADIUS_BASE;
  const r = 3 + Math.log1p(degree) * 2.5;
  return Math.max(NODE_RADIUS_MIN, Math.min(NODE_RADIUS_MAX, r));
}

/**
 * Build a stable parallel-edge index for each edge.
 * Parallel = same unordered (source, target) pair.
 */
function emptyMessageKey(
  status: GraphStatusResponse,
): 'Concept.empty' | 'Graph.empty_disabled' | 'Graph.empty_graph' | 'Graph.empty_source_missing' | 'Graph.empty_unavailable' {
  if (!status.enabled) return 'Graph.empty_disabled';
  if (!status.source_exists) return 'Graph.empty_source_missing';
  if (!status.has_graph) return 'Graph.empty_unavailable';
  if (status.node_count === 0) return 'Graph.empty_graph';
  return 'Concept.empty';
}

/* ---------- Filter helpers ---------- */

function collectKinds(nodes: ConceptGraphNode[]): string[] {
  const s = new Set<string>();
  for (const n of nodes) {
    if (n.kind) s.add(n.kind);
  }
  return Array.from(s).sort();
}

function collectFreshness(nodes: ConceptGraphNode[]): FreshnessProjection[] {
  const s = new Set<FreshnessProjection>();
  for (const n of nodes) {
    if (n.freshness === 'fresh' || n.freshness === 'stale') s.add(n.freshness);
  }
  return Array.from(s);
}

/* ---------- Truncate label ---------- */

function truncateLabel(text: string, maxLen: number): string {
  const chars = Array.from(text);
  if (chars.length <= maxLen) return text;
  if (maxLen <= 1) return '…';
  return chars.slice(0, maxLen - 1).join('') + '…';
}

function normalizeFocusValue(value: string): string {
  return value.normalize('NFKC').trim().toLocaleLowerCase();
}

function normalizeFocusLoose(value: string): string {
  return normalizeFocusValue(value).replace(/[^\p{Letter}\p{Number}]+/gu, '');
}

export function conceptGraphNodeMatchesFocus(
  node: Pick<ConceptGraphNode, 'id' | 'name'>,
  focus: string,
): boolean {
  const needle = normalizeFocusValue(focus);
  if (!needle) return false;
  const candidates = [node.id, node.name].filter(Boolean);
  if (candidates.some((candidate) => candidate === focus)) return true;
  if (candidates.some((candidate) => normalizeFocusValue(candidate) === needle)) return true;
  const looseNeedle = normalizeFocusLoose(focus);
  return Boolean(
    looseNeedle &&
      candidates.some((candidate) => normalizeFocusLoose(candidate) === looseNeedle),
  );
}

function escapeHtml(text: string): string {
  return text.replace(
    /[&<>"']/g,
    (ch) =>
      ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      })[ch] ?? ch,
  );
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

function fileStem(filePath: string): string | null {
  const safePath = shortenFilePath(filePath).replace(/\\/g, '/');
  const tail = safePath.split('/').pop();
  if (!tail) return null;
  const stem = tail.replace(/\.[^.]+$/, '');
  return stem || null;
}

type ForceGraphNodeInput = NodeObject<GraphNode>;
type ForceGraphLinkInput = LinkObject<GraphNode, GraphLink>;
type FGNode = NodeObject<ForceGraphNodeInput>;
type FGLink = LinkObject<ForceGraphNodeInput, ForceGraphLinkInput>;
type ForceGraphData = GraphData<ForceGraphNodeInput, ForceGraphLinkInput>;
type ForceGraphRef = ForceGraphMethods<ForceGraphNodeInput, ForceGraphLinkInput> | undefined;

function isGraphNode(value: unknown): value is FGNode {
  return typeof value === 'object' && value !== null && 'id' in value;
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const media = window.matchMedia(query);
    const sync = () => setMatches(media.matches);
    sync();
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', sync);
      return () => media.removeEventListener('change', sync);
    }
    media.addListener(sync);
    return () => media.removeListener(sync);
  }, [query]);

  return matches;
}

function buildCommunitySummaries(
  communityIds: string[],
  nodes: ConceptGraphNode[],
): Map<string, CommunitySummary> {
  const byCommunity = new Map<
    string,
    { count: number; fileCounts: Map<string, number>; shortestName: string | null }
  >();
  for (const id of communityIds) {
    byCommunity.set(id, { count: 0, fileCounts: new Map(), shortestName: null });
  }
  for (const node of nodes) {
    const community = readCommunity(node);
    if (community == null) continue;
    const entry = byCommunity.get(community);
    if (!entry) continue;
    entry.count += 1;
    if (node.file_path) {
      const stem = fileStem(node.file_path);
      if (stem) entry.fileCounts.set(stem, (entry.fileCounts.get(stem) ?? 0) + 1);
    }
    if (!entry.shortestName || node.name.length < entry.shortestName.length) {
      entry.shortestName = node.name;
    }
  }

  const summaries = new Map<string, CommunitySummary>();
  for (const [id, entry] of byCommunity) {
    if (entry.fileCounts.size > 0) {
      const [topFile] = [...entry.fileCounts.entries()].sort((a, b) => b[1] - a[1])[0];
      summaries.set(id, {
        count: entry.count,
        label: truncateLabel(topFile, COMMUNITY_LABEL_MAX_LEN),
        sourceFile: topFile,
      });
      continue;
    }
    if (entry.shortestName) {
      summaries.set(id, {
        count: entry.count,
        label: truncateLabel(entry.shortestName, COMMUNITY_LABEL_MAX_LEN),
        sourceFile: entry.shortestName,
      });
      continue;
    }
    summaries.set(id, { count: entry.count, label: id, sourceFile: null });
  }
  return summaries;
}

/* ---------- Canvas Force graph (react-force-graph-2d) ---------- */

function ForceGraph({
  nodes,
  edges,
  onSelectNode,
  selectedId,
  focusedIds,
  communityById,
  fgRef,
}: {
  nodes: ConceptGraphNode[];
  edges: ConceptGraphEdge[];
  onSelectNode: (id: string | null) => void;
  selectedId: string | null;
  focusedIds: Set<string> | null;
  communityById: Map<string, string | null>;
  fgRef: React.MutableRefObject<ForceGraphRef>;
}) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const forcedColors = useMediaQuery('(forced-colors: active)');
  const prefersDark = useMediaQuery('(prefers-color-scheme: dark)');
  const explicitTheme = typeof document !== 'undefined' ? document.documentElement.getAttribute('data-theme') : null;
  const isDark = explicitTheme === 'dark' || (explicitTheme !== 'light' && prefersDark);
  const [dimensions, setDimensions] = useState({
    width: 800,
    height: GRAPH_CANVAS_HEIGHT,
  });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const updateSize = () => {
      setDimensions({
        width: el.clientWidth || 800,
        height: el.clientHeight || GRAPH_CANVAS_HEIGHT,
      });
    };
    updateSize();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(updateSize);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const degrees = useMemo(() => computeDegrees(nodes, edges), [nodes, edges]);

  const graphData = useMemo<ForceGraphData>(() => {
    const gNodes: GraphNode[] = nodes.map((n) => {
      const community = communityById.get(n.id) ?? null;
      const palette = kindPalette(n.kind);
      const deg = degrees.get(n.id) ?? 0;
      return {
        id: n.id,
        name: n.name,
        displayLabel: truncateLabel(n.name, 16),
        kind: n.kind,
        file_path: n.file_path,
        freshness: n.freshness,
        radius: radiusForDegree(deg),
        degree: deg,
        communityFillColor: communityColor(community) ?? palette.fill,
        kindStrokeColor: palette.stroke,
      };
    });
    const gLinks: GraphLink[] = edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      relation: e.relation,
      weight: safeEdgeWeight(e.weight),
    }));
    return { nodes: gNodes, links: gLinks };
  }, [nodes, edges, communityById, degrees]);

  const connectedIds = useMemo(() => {
    if (selectedId == null) return null;
    const ids = new Set<string>([selectedId]);
    for (const e of edges) {
      if (e.source === selectedId) ids.add(e.target);
      if (e.target === selectedId) ids.add(e.source);
    }
    return ids;
  }, [selectedId, edges]);

  const nodeCanvasObject = useCallback(
    (node: FGNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const nodeId = String(node.id ?? '');
      const r = node.radius ?? 12;
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const isSelected = selectedId === nodeId;

      let opacity = 1;
      if (focusedIds != null) {
        opacity = focusedIds.has(nodeId) ? 1 : 0.08;
      } else if (connectedIds != null && !connectedIds.has(nodeId)) {
        opacity = 0.25;
      }

      ctx.globalAlpha = opacity;

      const baseColor = node.communityFillColor;
      const bgColor = isDark ? '#1C1B18' : '#FAF8F5';

      // Step 1: Negative-space cutout — separates overlapping nodes cleanly
      ctx.beginPath();
      ctx.arc(x, y, r + 1.5 / globalScale, 0, 2 * Math.PI);
      ctx.fillStyle = forcedColors ? 'Canvas' : bgColor;
      ctx.fill();

      // Step 2: Node body — solid (code) vs outline (rationale)
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      if (node.kind === 'rationale') {
        const savedAlpha = ctx.globalAlpha;
        ctx.globalAlpha = savedAlpha * 0.15;
        ctx.fillStyle = forcedColors ? 'Canvas' : baseColor;
        ctx.fill();
        ctx.globalAlpha = savedAlpha;
        ctx.lineWidth = 1.5 / globalScale;
        ctx.strokeStyle = forcedColors ? 'CanvasText' : baseColor;
        ctx.stroke();
      } else {
        ctx.fillStyle = forcedColors ? 'Canvas' : baseColor;
        ctx.fill();
        if (forcedColors) {
          ctx.lineWidth = 1.5 / globalScale;
          ctx.strokeStyle = 'CanvasText';
          ctx.stroke();
        }
      }

      // Step 3: Selection / hover ring
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(x, y, r + 3.5 / globalScale, 0, 2 * Math.PI);
        ctx.lineWidth = 1.5 / globalScale;
        ctx.strokeStyle = forcedColors ? 'Highlight' : (isDark ? '#E6E3D8' : '#2C2A28');
        ctx.stroke();
      }

      // Step 4: Progressive label — NYT-style text stroke for legibility
      const deg = node.degree ?? 0;
      const showLabel = globalScale >= 3.0 || (globalScale >= 1.2 && deg > 5) || isSelected;
      if (showLabel) {
        const fontSize = Math.max(4, 11 / globalScale);
        const label = node.displayLabel;
        ctx.font = `500 ${fontSize}px "Inter", -apple-system, BlinkMacSystemFont, sans-serif`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        const labelX = x + r + 4 / globalScale;
        if (!forcedColors) {
          ctx.lineWidth = 3 / globalScale;
          ctx.strokeStyle = bgColor;
          ctx.lineJoin = 'round';
          ctx.strokeText(label, labelX, y);
        }
        ctx.fillStyle = forcedColors ? 'CanvasText' : (isDark ? '#E6E3D8' : '#3A3835');
        ctx.fillText(label, labelX, y);
      }

      ctx.globalAlpha = 1;
    },
    [selectedId, focusedIds, connectedIds, forcedColors, isDark],
  );

  const nodePointerAreaPaint = useCallback(
    (node: FGNode, color: string, ctx: CanvasRenderingContext2D) => {
      const r = (node.radius ?? 12) + 2;
      ctx.beginPath();
      ctx.arc(node.x ?? 0, node.y ?? 0, r, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
    },
    [],
  );

  const linkCanvasObject = useCallback(
    (link: FGLink, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const src = link.source;
      const tgt = link.target;
      if (!isGraphNode(src) || !isGraphNode(tgt)) return;
      const sx = src.x ?? 0;
      const sy = src.y ?? 0;
      const tx = tgt.x ?? 0;
      const ty = tgt.y ?? 0;

      const isHighlighted =
        selectedId != null &&
        ((src.id === selectedId) || (tgt.id === selectedId));

      let edgeOpacity = 1;
      if (focusedIds != null) {
        const sIn = focusedIds.has(String(src.id ?? ''));
        const tIn = focusedIds.has(String(tgt.id ?? ''));
        if (!(sIn && tIn)) {
          edgeOpacity = (sIn || tIn) ? 0.08 : 0.03;
        }
      } else if (connectedIds != null && !isHighlighted) {
        edgeOpacity = 0.08;
      }

      ctx.globalAlpha = edgeOpacity;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(tx, ty);
      ctx.strokeStyle = forcedColors
        ? (isHighlighted ? 'Highlight' : 'CanvasText')
        : (isHighlighted ? (isDark ? '#D97757' : '#D27050') : (isDark ? '#3A3832' : '#DED9CE'));
      ctx.lineWidth = (isHighlighted ? 1.5 : 1) / globalScale;
      ctx.stroke();

      if (isHighlighted && link.relation && globalScale > 0.8) {
        const mx = (sx + tx) / 2;
        const my = (sy + ty) / 2;
        const fontSize = Math.max(9 / globalScale, 3);
        ctx.font = `${fontSize}px -apple-system, BlinkMacSystemFont, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.globalAlpha = 0.85;
        ctx.strokeStyle = forcedColors ? 'Canvas' : (isDark ? 'rgba(28, 27, 24, 0.85)' : 'rgba(242, 239, 231, 0.9)');
        ctx.lineWidth = 3 / globalScale;
        ctx.lineJoin = 'round';
        ctx.strokeText(link.relation, mx, my);
        ctx.fillStyle = forcedColors ? 'CanvasText' : (isDark ? '#D0CABF' : '#6A6456');
        ctx.fillText(link.relation, mx, my);
      }

      ctx.globalAlpha = 1;
    },
    [selectedId, focusedIds, connectedIds, forcedColors, isDark],
  );

  const handleNodeClick = useCallback(
    (node: FGNode) => {
      const nodeId = String(node.id ?? '');
      if (!nodeId) return;
      onSelectNode(selectedId === nodeId ? null : nodeId);
    },
    [onSelectNode, selectedId],
  );

  const handleBackgroundClick = useCallback(() => {
    if (selectedId != null) onSelectNode(null);
  }, [onSelectNode, selectedId]);

  return (
    <div
      ref={containerRef}
      className="concept-graph__canvas"
      role="img"
      aria-label={t('Graph.canvas_label', {
        nodes: String(nodes.length),
        edges: String(edges.length),
      })}
    >
      <ForceGraph2D
        ref={fgRef}
        graphData={graphData}
        width={dimensions.width}
        height={dimensions.height}
        backgroundColor="rgba(0,0,0,0)"
        nodeCanvasObject={nodeCanvasObject}
        nodeCanvasObjectMode={() => 'replace' as const}
        nodePointerAreaPaint={nodePointerAreaPaint}
        linkCanvasObject={linkCanvasObject}
        linkCanvasObjectMode={() => 'replace' as const}
        nodeLabel={(node) => escapeHtml(String(node.name ?? ''))}
        linkLabel={(link) => escapeHtml(String(link.relation ?? ''))}
        onNodeClick={handleNodeClick}
        onBackgroundClick={handleBackgroundClick}
        d3AlphaDecay={0.05}
        d3AlphaMin={0.01}
        d3VelocityDecay={0.3}
        cooldownTime={3000}
        enableNodeDrag={true}
        enableZoomInteraction={true}
        enablePanInteraction={true}
      />
    </div>
  );
}

/* ---------- Detail panel ---------- */

interface RelationGroup {
  relation: string;
  nodes: ConceptGraphNode[];
}

function groupConnectedByRelation(
  selfId: string,
  edges: ConceptGraphEdge[],
  nodeMap: Map<string, ConceptGraphNode>,
  unlabeledLabel: string,
): { groups: RelationGroup[]; total: number } {
  const buckets = new Map<string, Map<string, ConceptGraphNode>>();
  for (const e of edges) {
    if (e.source !== selfId && e.target !== selfId) continue;
    const otherId = e.source === selfId ? e.target : e.source;
    const other = nodeMap.get(otherId);
    if (!other) continue;
    const key = e.relation && e.relation.trim() ? e.relation : unlabeledLabel;
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = new Map<string, ConceptGraphNode>();
      buckets.set(key, bucket);
    }
    bucket.set(other.id, other);
  }
  const groups: RelationGroup[] = Array.from(buckets.entries())
    .map(([relation, m]) => ({ relation, nodes: Array.from(m.values()) }))
    .sort((a, b) => a.relation.localeCompare(b.relation));
  let total = 0;
  for (const g of groups) total += g.nodes.length;
  return { groups, total };
}

function isRenderableMetadataValue(v: unknown): v is string | number | boolean {
  return (
    typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'
  );
}

function DetailPanel({
  node,
  edges,
  allNodes,
  onClose,
  onActivateCommunity,
  focusHops,
  onSetFocusHops,
  currentRun,
}: {
  node: ConceptGraphNode;
  edges: ConceptGraphEdge[];
  allNodes: ConceptGraphNode[];
  onClose: () => void;
  /** Activate a community filter chip from the detail panel link. */
  onActivateCommunity: (communityId: string) => void;
  /** Current hop depth (null = focus off). */
  focusHops: number | null;
  /** Set hop depth or null to clear focus. */
  onSetFocusHops: (hops: number | null) => void;
  /** Current run id, when known, for cross-view links (Diff, Lesson). */
  currentRun: string | undefined;
}) {
  const { t } = useTranslation();
  const nodeMap = useMemo(() => new Map(allNodes.map((n) => [n.id, n])), [allNodes]);

  const { groups, total } = useMemo(
    () => groupConnectedByRelation(node.id, edges, nodeMap, t('Graph.relation_default')),
    [edges, node.id, nodeMap, t],
  );

  const community = useMemo(() => readCommunity(node), [node]);

  const communitySize = useMemo(() => {
    if (community == null) return 0;
    let count = 0;
    for (const n of allNodes) {
      if (readCommunity(n) === community) count += 1;
    }
    return count;
  }, [allNodes, community]);

  // Derived label for the panel link (e.g. "transport" instead of bare "Community 0").
  const communityInfo = useMemo<CommunityLabelInfo | null>(
    () => (community != null ? deriveCommunityLabel(community, allNodes) : null),
    [community, allNodes],
  );

  const handleHopClick = useCallback(
    (e: React.MouseEvent<HTMLButtonElement>) => {
      const raw = e.currentTarget.dataset.hops;
      if (!raw) return;
      const v = Number.parseInt(raw, 10);
      if (!Number.isFinite(v) || v < 1 || v > 3) return;
      onSetFocusHops(focusHops === v ? null : v);
    },
    [focusHops, onSetFocusHops],
  );

  const handleClearFocus = useCallback(() => onSetFocusHops(null), [onSetFocusHops]);

  const handleActivateCommunity = useCallback(() => {
    if (community != null) onActivateCommunity(community);
  }, [community, onActivateCommunity]);

  const metadataEntries = useMemo(() => {
    const meta = node.metadata;
    if (!meta || typeof meta !== 'object') return [];
    const skip = new Set(['community']);
    return Object.entries(meta as Record<string, unknown>)
      .filter(
        ([k, v]) =>
          !skip.has(k) && METADATA_DISPLAY_KEYS.has(k) && isRenderableMetadataValue(v),
      )
      .slice(0, 12)
      .map(([k, v]) => [k, String(v)] as const);
  }, [node.metadata]);

  /**
   * Quick-link hrefs for cross-view navigation.
   *
   * - "View in Diff" only renders when both `currentRun` and `node.file_path`
   *   exist; without the run id the diff route can't load and the file param
   *   would be useless.
   * - "Find in Lesson" only renders when `currentRun` is set.
   * - "Search this concept" + "Review related" always render.
   *
   * For URL hrefs we always `encodeURIComponent` so names with `/`, `?`, `#`,
   * `&`, or whitespace stay parseable. The search action dispatches a custom
   * event instead of navigating, so AppShell can pre-fill the global overlay.
   */
  const encodedName = encodeURIComponent(node.name);
  const diffHref =
    currentRun && node.file_path
      ? `#/run/${encodeURIComponent(currentRun)}/diff?file=${encodeURIComponent(node.file_path)}`
      : null;
  const lessonHref = currentRun
    ? `#/run/${encodeURIComponent(currentRun)}/lesson`
    : null;
  const reviewHref = `#/review?q=${encodedName}`;

  const handleSearchClick = useCallback(
    (event: React.MouseEvent<HTMLAnchorElement>) => {
      event.preventDefault();
      const detail: OpenSearchEventDetail = { query: node.name };
      window.dispatchEvent(new CustomEvent(OPEN_SEARCH_EVENT, { detail }));
    },
    [node.name],
  );

  return (
    <aside
      className="concept-graph__detail"
      aria-label={node.name}
      style={kindColorStyle(node.kind)}
    >
      <div className="concept-graph__detail-bar" aria-hidden="true" />
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

      {community != null && (
        <div className="concept-graph__detail-row">
          <span className="concept-graph__detail-label">{t('Graph.community')}</span>
          <button
            type="button"
            className="concept-graph__community-link"
            onClick={handleActivateCommunity}
            style={{
              borderColor: communityColor(community) ?? 'currentColor',
              color: communityColor(community) ?? 'inherit',
            }}
          >
            <span
              className="concept-graph__community-dot"
              aria-hidden="true"
              style={{ background: communityColor(community) ?? 'currentColor' }}
            />
            {communityInfo && communityInfo.sourceFile
              ? `${communityInfo.label} (${t('Graph.community_label', { id: community })})`
              : t('Graph.community_label', { id: community })}
            {communitySize > 0 && (
              <span className="concept-graph__community-link-count">
                {' · '}
                {t('Graph.community_nodes', { count: String(communitySize) })}
              </span>
            )}
          </button>
        </div>
      )}

      <div className="concept-graph__detail-row">
        <span className="concept-graph__detail-label">{t('Graph.connected')}</span>
        <span className="concept-graph__detail-value">
          {t('Concept.list_connections', { count: String(total) })}
        </span>
      </div>

      <div className="concept-graph__detail-row">
        <span className="concept-graph__detail-label">{t('Graph.hop_depth')}</span>
        <div
          className="concept-graph__hop-selector"
          role="group"
          aria-label={t('Graph.focus_mode')}
        >
          {([1, 2, 3] as const).map((h) => {
            const active = focusHops === h;
            const label = t(`Graph.hop_label_${h}` as 'Graph.hop_label_1');
            return (
              <button
                key={h}
                type="button"
                data-hops={String(h)}
                className={`concept-graph__hop-btn${
                  active ? ' concept-graph__hop-btn--active' : ''
                }`}
                onClick={handleHopClick}
                aria-pressed={active}
                title={label}
              >
                {label}
              </button>
            );
          })}
          <button
            type="button"
            className="concept-graph__hop-clear"
            onClick={handleClearFocus}
            disabled={focusHops == null}
            aria-label={t('Graph.focus_clear')}
            title={t('Graph.focus_clear')}
          >
            ✕
          </button>
        </div>
      </div>

      {metadataEntries.length > 0 && (
        <div className="concept-graph__detail-section">
          <span className="concept-graph__detail-label">{t('Graph.metadata')}</span>
          <dl className="concept-graph__detail-meta">
            {metadataEntries.map(([k, v]) => (
              <div key={k} className="concept-graph__detail-meta-row">
                <dt className="concept-graph__detail-meta-key">{k}</dt>
                <dd className="concept-graph__detail-meta-val">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {groups.length > 0 && (
        <div className="concept-graph__detail-section">
          <span className="concept-graph__detail-label">
            {t('Graph.connected')} ({total})
          </span>
          <div className="concept-graph__detail-rel-groups">
            {groups.map((g) => (
              <div key={g.relation} className="concept-graph__detail-rel-group">
                <div className="concept-graph__detail-rel-header">
                  <span className="concept-graph__detail-rel-name">{g.relation}</span>
                  <span className="concept-graph__detail-rel-count">{g.nodes.length}</span>
                </div>
                <ul className="concept-graph__detail-connections">
                  {g.nodes.map((c) => (
                    <li
                      key={c.id}
                      className="concept-graph__detail-conn-item"
                      style={kindColorStyle(c.kind)}
                    >
                      <span
                        className="concept-graph__detail-conn-dot"
                        aria-hidden="true"
                      />
                      <span className="concept-graph__detail-conn-name">{c.name}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      <nav
        className="concept-graph__quick-links"
        aria-label={t('Graph.quick_links')}
      >
        <span className="concept-graph__detail-label">{t('Graph.quick_links')}</span>
        {diffHref && (
          <a className="concept-graph__quick-link" href={diffHref}>
            {t('Graph.view_in_diff')}
          </a>
        )}
        <a
          className="concept-graph__quick-link"
          href={`#/search?q=${encodedName}`}
          onClick={handleSearchClick}
        >
          {t('Graph.search_concept')}
        </a>
        <a className="concept-graph__quick-link" href={reviewHref}>
          {t('Graph.review_related')}
        </a>
        {lessonHref && (
          <a className="concept-graph__quick-link" href={lessonHref}>
            {t('Graph.find_in_lesson')}
          </a>
        )}
      </nav>
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
      <span className="concept-graph__legend-item concept-graph__legend-item--ring">
        <span
          className="concept-graph__legend-swatch concept-graph__legend-swatch--ring"
          aria-hidden="true"
        />
        {t('Graph.legend_ring')}
      </span>
    </div>
  );
}

function AccessibleGraphNodes({
  nodes,
  onSelectNode,
}: {
  nodes: ConceptGraphNode[];
  onSelectNode: (id: string) => void;
}) {
  const { t } = useTranslation();
  const handleClick = useCallback(
    (event: React.MouseEvent<HTMLButtonElement>) => {
      const id = event.currentTarget.dataset.nodeId;
      if (id) onSelectNode(id);
    },
    [onSelectNode],
  );

  return (
    <ul className="concept-graph__a11y-list" aria-label={t('Graph.accessible_nodes')}>
      {nodes.map((node) => (
        <li key={node.id}>
          <button
            type="button"
            className="concept-graph__a11y-node"
            data-node-id={node.id}
            onClick={handleClick}
          >
            <span className="concept-graph__a11y-node-name">{node.name}</span>
            {node.file_path && (
              <span className="concept-graph__a11y-node-file">
                {shortenFilePath(node.file_path)}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

/* ---------- Filter chips ---------- */

type FreshnessFilter = 'fresh' | 'stale';

function FilterChips({
  kinds,
  freshnessKinds,
  activeKinds,
  activeFreshness,
  hasAllKinds,
  onToggleKind,
  onToggleFreshness,
  onClearAll,
}: {
  kinds: string[];
  freshnessKinds: FreshnessProjection[];
  activeKinds: Set<string>;
  activeFreshness: Set<FreshnessFilter>;
  hasAllKinds: boolean;
  onToggleKind: (kind: string) => void;
  onToggleFreshness: (kind: FreshnessFilter) => void;
  onClearAll: () => void;
}) {
  const { t } = useTranslation();
  const handleKindClick = useCallback(
    (e: React.MouseEvent<HTMLButtonElement>) => {
      const kind = e.currentTarget.dataset.kind;
      if (!kind) return;
      onToggleKind(kind);
    },
    [onToggleKind],
  );
  const handleFreshnessClick = useCallback(
    (e: React.MouseEvent<HTMLButtonElement>) => {
      const fr = e.currentTarget.dataset.freshness as FreshnessFilter | undefined;
      if (!fr) return;
      onToggleFreshness(fr);
    },
    [onToggleFreshness],
  );
  const showAnything = kinds.length > 1 || freshnessKinds.length > 0;
  if (!showAnything) return null;

  return (
    <div className="concept-graph__filters" role="group" aria-label={t('Graph.filter')}>
      <button
        type="button"
        className={`concept-graph__filter-chip concept-graph__filter-chip--all${
          hasAllKinds ? ' concept-graph__filter-chip--active' : ''
        }`}
        onClick={onClearAll}
        aria-pressed={hasAllKinds}
      >
        {t('Concept.filter_all')}
      </button>
      {kinds.map((k) => {
        const isActive = activeKinds.has(k);
        return (
          <button
            key={k}
            type="button"
            data-kind={k}
            className={`concept-graph__filter-chip${
              isActive ? ' concept-graph__filter-chip--active' : ''
            }`}
            onClick={handleKindClick}
            aria-pressed={isActive}
            style={kindColorStyle(k)}
          >
            <span
              className="concept-graph__filter-swatch"
              aria-hidden="true"
            />
            {k}
          </button>
        );
      })}
      {freshnessKinds.length > 0 && (
        <span className="concept-graph__filters-sep" aria-hidden="true" />
      )}
      {freshnessKinds.map((f) => {
        const isActive = activeFreshness.has(f as FreshnessFilter);
        return (
          <button
            key={`fresh-${f}`}
            type="button"
            data-freshness={f}
            className={`concept-graph__filter-chip concept-graph__filter-chip--freshness concept-graph__filter-chip--freshness-${f}${
              isActive ? ' concept-graph__filter-chip--active' : ''
            }`}
            onClick={handleFreshnessClick}
            aria-pressed={isActive}
          >
            <span
              className={`concept-graph__filter-swatch concept-graph__filter-swatch--${f}`}
              aria-hidden="true"
            />
            {t(FRESHNESS_LABEL_KEY[f])}
          </button>
        );
      })}
    </div>
  );
}

/* ---------- Community filter chips ---------- */

function CommunityFilterChips({
  communityIds,
  activeCommunities,
  onToggle,
  onClear,
  allNodes,
}: {
  communityIds: string[];
  activeCommunities: Set<string>;
  onToggle: (id: string) => void;
  onClear: () => void;
  /** Full node list (unfiltered) used to derive meaningful labels per community. */
  allNodes: ConceptGraphNode[];
}) {
  const { t } = useTranslation();
  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLButtonElement>) => {
      const id = e.currentTarget.dataset.community;
      if (!id) return;
      onToggle(id);
    },
    [onToggle],
  );
  const summaryByCommunity = useMemo(
    () => buildCommunitySummaries(communityIds, allNodes),
    [communityIds, allNodes],
  );
  const visibleCommunityIds = communityIds.slice(0, MAX_COMMUNITY_FILTER_CHIPS);
  const hiddenCommunityCount = Math.max(0, communityIds.length - visibleCommunityIds.length);

  if (communityIds.length === 0) return null;
  return (
    <div
      className="concept-graph__community-filters"
      role="group"
      aria-label={t('Graph.community_filter')}
    >
      <span className="concept-graph__community-filters-label">
        {t('Graph.community_filter')}
      </span>
      <span
        className="concept-graph__community-help"
        role="img"
        aria-label={t('Graph.community_help')}
        title={t('Graph.community_help')}
      >
        i
      </span>
      {activeCommunities.size > 0 && (
        <button
          type="button"
          className="concept-graph__filter-chip concept-graph__filter-chip--all"
          onClick={onClear}
        >
          {t('Concept.filter_all')}
        </button>
      )}
      {visibleCommunityIds.map((id) => {
        const isActive = activeCommunities.has(id);
        const color = communityColor(id) ?? 'var(--accent)';
        const info = summaryByCommunity.get(id);
        // Chip text: prefer the derived label; fall back to "Community {id}" when
        // we couldn't derive anything better (e.g. all nodes lack file_path).
        const chipText = info && info.sourceFile
          ? info.label
          : t('Graph.community_label', { id });
        // Tooltip: keep the raw "Community {id}" prefix so debugging stays easy,
        // then append "· N nodes · mainly from <file>" when info is available.
        const count = info?.count ?? 0;
        const sep = t('Graph.sep');
        const parts: string[] = [t('Graph.community_label', { id })];
        if (count > 0) parts.push(t('Graph.community_nodes', { count: String(count) }));
        if (info && info.sourceFile) {
          parts.push(t('Graph.community_from', { file: info.sourceFile }));
        }
        const tooltip = parts.join(sep);
        return (
          <button
            key={id}
            type="button"
            data-community={id}
            className={`concept-graph__filter-chip concept-graph__filter-chip--community${
              isActive ? ' concept-graph__filter-chip--active' : ''
            }`}
            onClick={handleClick}
            aria-pressed={isActive}
            aria-label={tooltip}
            title={tooltip}
            style={
              isActive
                ? { borderColor: color, color, background: 'transparent' }
                : { borderColor: color }
            }
          >
            <span
              className="concept-graph__filter-swatch"
              aria-hidden="true"
              style={{ background: color }}
            />
            {chipText}
          </button>
        );
      })}
      {hiddenCommunityCount > 0 && (
        <span className="concept-graph__community-overflow" aria-hidden="true">
          +{hiddenCommunityCount}
        </span>
      )}
    </div>
  );
}

/* ---------- List fallback (large graphs) ---------- */

function ListFallback({
  nodes,
  edges,
  onSelectNode,
  communityById,
}: {
  nodes: ConceptGraphNode[];
  edges: ConceptGraphEdge[];
  onSelectNode: (id: string) => void;
  /** Map node id → community id (string), null when node has no community.
   * Used to render a left-border accent in the community color on each card. */
  communityById: Map<string, string | null>;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [showAll, setShowAll] = useState(false);
  const [collapsedKinds, setCollapsedKinds] = useState<Set<string>>(new Set());

  const degrees = useMemo(() => computeDegrees(nodes, edges), [nodes, edges]);

  const handleNodeClick = useCallback(
    (e: React.MouseEvent<HTMLButtonElement>) => {
      const id = e.currentTarget.dataset.nodeId;
      if (!id) return;
      onSelectNode(id);
    },
    [onSelectNode],
  );

  const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setSearch(e.target.value);
  }, []);

  const handleToggleKind = useCallback((e: React.MouseEvent<HTMLButtonElement>) => {
    const k = e.currentTarget.dataset.kind;
    if (!k) return;
    setCollapsedKinds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }, []);

  const filteredNodes = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return nodes;
    return nodes.filter((n) => {
      if (n.name.toLowerCase().includes(q)) return true;
      if (n.file_path && n.file_path.toLowerCase().includes(q)) return true;
      return false;
    });
  }, [nodes, search]);

  const totalAfterSearch = filteredNodes.length;
  const limited = !showAll && totalAfterSearch > LIST_INITIAL_LIMIT;
  const visibleNodes = limited
    ? filteredNodes.slice(0, LIST_INITIAL_LIMIT)
    : filteredNodes;

  /**
   * Group nodes by kind and sort each group alphabetically.
   * Untyped nodes (kind === null) live under 'unknown' and render last.
   */
  const grouped = useMemo(() => {
    const buckets = new Map<string, ConceptGraphNode[]>();
    for (const n of visibleNodes) {
      const key = n.kind ?? 'unknown';
      const arr = buckets.get(key);
      if (arr) arr.push(n);
      else buckets.set(key, [n]);
    }
    const entries: { kind: string; displayKind: string | null; items: ConceptGraphNode[] }[] = [];
    for (const [k, arr] of buckets) {
      const sorted = [...arr].sort((a, b) =>
        a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }),
      );
      entries.push({
        kind: k,
        displayKind: k === 'unknown' ? null : k,
        items: sorted,
      });
    }
    entries.sort((a, b) => {
      if (a.kind === 'unknown') return 1;
      if (b.kind === 'unknown') return -1;
      return a.kind.localeCompare(b.kind);
    });
    return entries;
  }, [visibleNodes]);

  return (
    <div className="concept-graph__list-wrap">
      <div className="concept-graph__list-search">
        <input
          type="search"
          className="concept-graph__list-search-input"
          placeholder={t('Concept.list_search_placeholder')}
          value={search}
          onChange={handleSearchChange}
          aria-label={t('Concept.list_search_placeholder')}
        />
      </div>

      {totalAfterSearch === 0 ? (
        <div className="concept-graph__list-empty" role="status">
          {t('Concept.list_no_results')}
        </div>
      ) : (
        <>
          {grouped.map((group) => {
            const isCollapsed = collapsedKinds.has(group.kind);
            const headerLabel = group.displayKind ?? t('Graph.kind_unknown');
            return (
              <section
                key={group.kind}
                className="concept-graph__list-group"
                style={kindColorStyle(group.displayKind)}
              >
                <button
                  type="button"
                  className={`concept-graph__list-group-header${
                    isCollapsed ? ' concept-graph__list-group-header--collapsed' : ''
                  }`}
                  data-kind={group.kind}
                  onClick={handleToggleKind}
                  aria-expanded={!isCollapsed}
                >
                  <span
                    className="concept-graph__list-group-dot"
                    aria-hidden="true"
                  />
                  <span className="concept-graph__list-group-name">{headerLabel}</span>
                  <span className="concept-graph__list-group-count">
                    {t('Concept.list_group_nodes', { count: String(group.items.length) })}
                  </span>
                  <span
                    className="concept-graph__list-group-chev"
                    aria-hidden="true"
                  >
                    {isCollapsed ? '▸' : '▾'}
                  </span>
                </button>
                {!isCollapsed && (
                  <div className="concept-graph__listg">
                    {group.items.map((n) => {
                      const degree = degrees.get(n.id) ?? 0;
                      const fresh = n.freshness === 'fresh';
                      const stale = n.freshness === 'stale';
                      // Compose kind color tokens with the community-color
                      // accent on the left border. When the node has no
                      // community, the existing kind-stroke fallback is kept.
                      const community = communityById.get(n.id) ?? null;
                      const commColor = communityColor(community);
                      const lnodeStyle: CSSProperties = {
                        ...kindColorStyle(n.kind),
                        ...(commColor ? { borderLeftColor: commColor } : null),
                      };
                      return (
                        <button
                          key={n.id}
                          type="button"
                          data-node-id={n.id}
                          className="concept-graph__lnode"
                          onClick={handleNodeClick}
                          style={lnodeStyle}
                        >
                          <div className="concept-graph__lnode-head">
                            <span className="concept-graph__lnode-name">{n.name}</span>
                            {n.freshness && (fresh || stale) && (
                              <span
                                className={`concept-graph__lnode-fresh concept-graph__lnode-fresh--${n.freshness}`}
                                aria-label={t(FRESHNESS_LABEL_KEY[n.freshness])}
                                title={t(FRESHNESS_LABEL_KEY[n.freshness])}
                              />
                            )}
                          </div>
                          {n.kind && (
                            <span className="concept-graph__lnode-kind">{n.kind}</span>
                          )}
                          {n.file_path && (
                            <span className="concept-graph__lnode-file">
                              {shortenFilePath(n.file_path)}
                            </span>
                          )}
                          {degree > 0 && (
                            <span className="concept-graph__lnode-deg">
                              {t('Concept.list_connections', { count: String(degree) })}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}
              </section>
            );
          })}

          {limited && (
            <div className="concept-graph__list-more">
              <span className="concept-graph__list-more-text">
                {t('Concept.list_showing_first', {
                  shown: String(LIST_INITIAL_LIMIT),
                  total: String(totalAfterSearch),
                })}
              </span>
              <button
                type="button"
                className="concept-graph__list-more-btn"
                onClick={() => setShowAll(true)}
              >
                {t('Concept.list_show_more')}
              </button>
            </div>
          )}
        </>
      )}
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

function ConceptGraph({
  nodes,
  edges,
  status,
  truncated,
  focusNodeId,
  onShowAll,
  currentRun,
}: ConceptGraphProps) {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeKinds, setActiveKinds] = useState<Set<string>>(new Set());
  const [activeFreshness, setActiveFreshness] = useState<Set<FreshnessFilter>>(new Set());
  const [activeCommunities, setActiveCommunities] = useState<Set<string>>(new Set());
  const [focusHops, setFocusHops] = useState<number | null>(null);
  const [viewMode, setViewMode] = useState<'graph' | 'list'>(
    nodes.length > LARGE_GRAPH_THRESHOLD ? 'list' : 'graph',
  );
  const [allowExtremeGraphRender, setAllowExtremeGraphRender] = useState(false);
  const graphWrapRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<ForceGraphRef>(undefined);

  const handleFit = useCallback(() => {
    fgRef.current?.zoomToFit(400, 40);
  }, []);

  const handleExport = useCallback(() => {
    const payload = JSON.stringify(
      {
        status,
        nodes,
        edges,
        truncated,
      },
      null,
      2,
    );
    const blob = new Blob([payload], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'concept-graph.json';
    a.style.display = 'none';
    document.body.appendChild(a);
    try {
      a.click();
    } finally {
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    }
  }, [edges, nodes, status, truncated]);

  const allKinds = useMemo(() => collectKinds(nodes), [nodes]);
  const allFreshness = useMemo(() => collectFreshness(nodes), [nodes]);
  const resolvedFocusNodeId = useMemo(() => {
    if (!focusNodeId) return null;
    return nodes.find((node) => conceptGraphNodeMatchesFocus(node, focusNodeId))?.id ?? null;
  }, [focusNodeId, nodes]);

  useEffect(() => {
    setActiveKinds(new Set());
    setActiveFreshness(new Set());
    setActiveCommunities(new Set());
    setFocusHops(null);
    setSelectedId(null);
  }, [nodes]);

  useEffect(() => {
    if (!resolvedFocusNodeId) return;
    setActiveKinds(new Set());
    setActiveFreshness(new Set());
    setActiveCommunities(new Set());
    setSelectedId(resolvedFocusNodeId);
  }, [resolvedFocusNodeId]);

  // Auto-clear focus hops whenever the selected node is cleared.
  useEffect(() => {
    if (selectedId == null && focusHops != null) {
      setFocusHops(null);
    }
  }, [selectedId, focusHops]);

  useEffect(() => {
    setViewMode(nodes.length > LARGE_GRAPH_THRESHOLD ? 'list' : 'graph');
    setAllowExtremeGraphRender(false);
  }, [nodes.length]);

  const filteredNodes = useMemo(() => {
    let out = nodes;
    if (activeKinds.size > 0) {
      out = out.filter((n) => n.kind != null && activeKinds.has(n.kind));
    }
    if (activeFreshness.size > 0) {
      out = out.filter(
        (n) =>
          n.freshness != null &&
          (n.freshness === 'fresh' || n.freshness === 'stale') &&
          activeFreshness.has(n.freshness as FreshnessFilter),
      );
    }
    if (activeCommunities.size > 0) {
      out = out.filter((n) => {
        const c = readCommunity(n);
        return c != null && activeCommunities.has(c);
      });
    }
    return out;
  }, [nodes, activeKinds, activeFreshness, activeCommunities]);

  const filteredNodeIds = useMemo(
    () => new Set(filteredNodes.map((n) => n.id)),
    [filteredNodes],
  );

  const filteredKinds = useMemo(() => collectKinds(filteredNodes), [filteredNodes]);

  const filteredEdges = useMemo(() => {
    return edges.filter(
      (e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target),
    );
  }, [edges, filteredNodeIds]);

  // Community id → color is stable; we keep two derived structures:
  //   - communityById: per-node lookup for ring color + dim policy
  //   - allCommunityIds: sorted unique list to populate the chip group
  const communityById = useMemo(() => {
    const m = new Map<string, string | null>();
    for (const n of nodes) m.set(n.id, readCommunity(n));
    return m;
  }, [nodes]);

  const allCommunityIds = useMemo(() => {
    const s = new Set<string>();
    for (const n of nodes) {
      const c = readCommunity(n);
      if (c != null) s.add(c);
    }
    return Array.from(s).sort((a, b) =>
      a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }),
    );
  }, [nodes]);

  // Adjacency built once over ALL edges so BFS reaches the full neighborhood
  // even when filters hide some edges.
  const adjacency = useMemo(() => buildAdjacency(edges), [edges]);

  // BFS frontier. Only computed when focus mode is active and a node is
  // selected; otherwise null disables focus rendering entirely.
  const focusedIds = useMemo(() => {
    if (focusHops == null || selectedId == null) return null;
    return getNeighborsAtHops(selectedId, adjacency, focusHops);
  }, [focusHops, selectedId, adjacency]);

  useEffect(() => {
    if (viewMode === 'graph') {
      const timer = window.setTimeout(() => fgRef.current?.zoomToFit(400, 40), 300);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [filteredEdges, filteredNodes, viewMode]);

  const selectedNode = useMemo(
    () => filteredNodes.find((n) => n.id === selectedId) ?? null,
    [filteredNodes, selectedId],
  );
  const isExtremelyLargeGraph = filteredNodes.length >= EXTREMELY_LARGE_GRAPH_THRESHOLD;
  const shouldBlockExtremeGraph =
    viewMode === 'graph' && isExtremelyLargeGraph && !allowExtremeGraphRender;

  useEffect(() => {
    if (!resolvedFocusNodeId || viewMode !== 'graph' || shouldBlockExtremeGraph) return undefined;
    if (!filteredNodeIds.has(resolvedFocusNodeId)) return undefined;
    const timer = window.setTimeout(() => {
      fgRef.current?.zoomToFit(
        500,
        120,
        (node) => String(node.id ?? '') === resolvedFocusNodeId,
      );
    }, 450);
    return () => window.clearTimeout(timer);
  }, [resolvedFocusNodeId, filteredNodeIds, shouldBlockExtremeGraph, viewMode]);

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

  const handleToggleFreshness = useCallback((fr: FreshnessFilter) => {
    setActiveFreshness((prev) => {
      const next = new Set(prev);
      if (next.has(fr)) next.delete(fr);
      else next.add(fr);
      return next;
    });
  }, []);

  const handleClearAll = useCallback(() => {
    setActiveKinds(new Set());
    setActiveFreshness(new Set());
    setActiveCommunities(new Set());
  }, []);

  const handleToggleCommunity = useCallback((id: string) => {
    setActiveCommunities((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleClearCommunities = useCallback(() => {
    setActiveCommunities(new Set());
  }, []);

  const handleActivateCommunity = useCallback((id: string) => {
    setActiveCommunities((prev) => {
      if (prev.has(id) && prev.size === 1) return prev;
      return new Set([id]);
    });
  }, []);

  const hasAllKinds =
    activeKinds.size === 0 && activeFreshness.size === 0 && activeCommunities.size === 0;

  useEffect(() => {
    if (selectedId == null) return;
    const handleWindowKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest('[role="dialog"][aria-modal="true"]')) return;
      if (event.key === 'Escape') {
        // Fully clear selection state so users can always recover from
        // a dimmed/focus-mode graph.
        setSelectedId(null);
        setFocusHops(null);
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
        <div className="concept-graph__toolbar-filters">
          <FilterChips
            kinds={allKinds}
            freshnessKinds={allFreshness}
            activeKinds={activeKinds}
            activeFreshness={activeFreshness}
            hasAllKinds={hasAllKinds}
            onToggleKind={handleToggleKind}
            onToggleFreshness={handleToggleFreshness}
            onClearAll={handleClearAll}
          />
          <CommunityFilterChips
            communityIds={allCommunityIds}
            activeCommunities={activeCommunities}
            onToggle={handleToggleCommunity}
            onClear={handleClearCommunities}
            allNodes={nodes}
          />
        </div>
        <div className="concept-graph__view-toggle">
          <button
            type="button"
            className={`concept-graph__view-btn${viewMode === 'graph' ? ' concept-graph__view-btn--active' : ''}`}
            onClick={() => {
              setAllowExtremeGraphRender(false);
              if (!resolvedFocusNodeId) {
                setSelectedId(null);
                setFocusHops(null);
              }
              setViewMode('graph');
              // Auto-fit shortly after the canvas mounts/lays out.
              window.setTimeout(() => handleFit(), 100);
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
                  <AccessibleGraphNodes
                    nodes={filteredNodes}
                    onSelectNode={setSelectedId}
                  />
                  <ForceGraph
                    nodes={filteredNodes}
                    edges={filteredEdges}
                    onSelectNode={setSelectedId}
                    selectedId={selectedId}
                    focusedIds={focusedIds}
                    communityById={communityById}
                    fgRef={fgRef}
                  />
                  <Legend kinds={filteredKinds} />
                </div>
              )}
            </>
          ) : (
            <ListFallback
              nodes={filteredNodes}
              edges={filteredEdges}
              onSelectNode={setSelectedId}
              communityById={communityById}
            />
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
            currentRun={currentRun}
            onActivateCommunity={handleActivateCommunity}
            focusHops={focusHops}
            onSetFocusHops={setFocusHops}
          />
        )}
      </div>
    </div>
  );
}

export default memo(ConceptGraph);
