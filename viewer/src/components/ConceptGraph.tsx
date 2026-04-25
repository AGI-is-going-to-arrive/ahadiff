import { useCallback, useId, useMemo, useState } from 'react';
import type { GraphifyMode } from '../api/types';
import { useTranslation } from '../i18n/useTranslation';
import './ConceptGraph.css';

/* ---------- Public types ---------- */

export interface Concept {
  concept: string;
  term_key: string;
  display_name: string;
  /** surface explanation — may be absent in current schema */
  surface?: string;
  /** related claim IDs that link concepts together */
  related_claims?: string[];
  /** file references */
  file_refs?: string[];
  /** aliases for this concept */
  aliases?: string[];
}

export interface ConceptGraphProps {
  concepts: Concept[];
  mode: GraphifyMode;
}

/* ---------- Layout helpers ---------- */

interface NodeLayout {
  concept: Concept;
  cx: number;
  cy: number;
}

interface Edge {
  from: number;
  to: number;
}

/**
 * Place nodes equally spaced on a circle.
 * Edges are derived from shared `related_claims` between concepts.
 */
function computeCircularLayout(
  concepts: Concept[],
  width: number,
  height: number,
): { nodes: NodeLayout[]; edges: Edge[] } {
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(cx, cy) - 40;
  const count = concepts.length;

  const nodes: NodeLayout[] = concepts.map((concept, i) => {
    const angle = (2 * Math.PI * i) / count - Math.PI / 2;
    return {
      concept,
      cx: cx + radius * Math.cos(angle),
      cy: cy + radius * Math.sin(angle),
    };
  });

  /* Build claim-to-node index for edge derivation */
  const claimIndex = new Map<string, number[]>();
  concepts.forEach((c, i) => {
    for (const claim of c.related_claims ?? []) {
      const existing = claimIndex.get(claim);
      if (existing) {
        existing.push(i);
      } else {
        claimIndex.set(claim, [i]);
      }
    }
  });

  const edgeSet = new Set<string>();
  const edges: Edge[] = [];
  for (const indices of claimIndex.values()) {
    for (let a = 0; a < indices.length; a++) {
      for (let b = a + 1; b < indices.length; b++) {
        const key = `${indices[a]}-${indices[b]}`;
        if (!edgeSet.has(key)) {
          edgeSet.add(key);
          edges.push({ from: indices[a], to: indices[b] });
        }
      }
    }
  }

  return { nodes, edges };
}

/* ---------- SVG Full graph ---------- */

const SVG_WIDTH = 640;
const SVG_HEIGHT = 480;
const NODE_RADIUS = 18;

function FullGraph({ concepts }: { concepts: Concept[] }) {
  const { t } = useTranslation();
  const tooltipId = useId();
  const [activeIdx, setActiveIdx] = useState<number | null>(null);
  const { nodes, edges } = useMemo(
    () => computeCircularLayout(concepts, SVG_WIDTH, SVG_HEIGHT),
    [concepts],
  );

  const handleNodeActivate = useCallback((index: number) => {
    setActiveIdx((prev) => (prev === index ? null : index));
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent, index: number) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleNodeActivate(index);
      }
    },
    [handleNodeActivate],
  );

  const handleSvgKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') setActiveIdx(null);
  }, []);

  const activeNode = activeIdx !== null ? nodes[activeIdx] : null;

  return (
    <div className="concept-graph__svg-wrap">
      <span className="concept-graph__mode-badge">{t('Concept.mode_full')}</span>
      <svg
        className="concept-graph__svg"
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        role="graphics-document"
        aria-label={t('Concept.title')}
        onKeyDown={handleSvgKeyDown}
      >
        {/* Edges */}
        {edges.map((edge) => (
          <line
            key={`${edge.from}-${edge.to}`}
            className="concept-graph__edge"
            x1={nodes[edge.from].cx}
            y1={nodes[edge.from].cy}
            x2={nodes[edge.to].cx}
            y2={nodes[edge.to].cy}
          />
        ))}

        {/* Nodes */}
        {nodes.map((node, i) => {
          const titleId = `${tooltipId}-node-${i}`;
          return (
            <g
              key={node.concept.term_key}
              className="concept-graph__node"
              tabIndex={0}
              role="button"
              aria-pressed={activeIdx === i}
              aria-describedby={activeIdx === i ? tooltipId : undefined}
              aria-labelledby={titleId}
              onClick={() => handleNodeActivate(i)}
              onKeyDown={(e) => handleKeyDown(e, i)}
            >
              <title id={titleId}>{node.concept.display_name}</title>
              <circle
                className="concept-graph__circle"
                cx={node.cx}
                cy={node.cy}
                r={NODE_RADIUS}
              />
              <text className="concept-graph__label" x={node.cx} y={node.cy}>
                {truncateLabel(node.concept.display_name, 8)}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Tooltip */}
      <div
        id={tooltipId}
        className={`concept-graph__tooltip${activeNode ? ' concept-graph__tooltip--visible' : ''}`}
        style={
          activeNode
            ? { left: `${(activeNode.cx / SVG_WIDTH) * 100}%`, top: `${(activeNode.cy / SVG_HEIGHT) * 100}%` }
            : undefined
        }
        role="tooltip"
      >
        {activeNode && (
          <>
            <div className="concept-graph__tooltip-name">
              {activeNode.concept.display_name}
            </div>
            {activeNode.concept.surface && (
              <div className="concept-graph__tooltip-surface">{activeNode.concept.surface}</div>
            )}
            {activeNode.concept.file_refs && activeNode.concept.file_refs.length > 0 && (
              <div className="concept-graph__tooltip-refs">
                {activeNode.concept.file_refs.join(', ')}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* ---------- Learning-only list ---------- */

function LearningList({ concepts }: { concepts: Concept[] }) {
  const { t } = useTranslation();

  return (
    <div>
      <span className="concept-graph__mode-badge">{t('Concept.mode_learning_only')}</span>
      <ul className="concept-graph__list" role="list">
        {concepts.map((c) => (
          <li key={c.term_key} className="concept-graph__list-item">
            <span className="concept-graph__list-name">{c.display_name}</span>
            {c.surface && (
              <span className="concept-graph__list-detail">{c.surface}</span>
            )}
            {c.aliases && c.aliases.length > 0 && (
              <span className="concept-graph__list-detail">
                {c.aliases.join(', ')}
              </span>
            )}
            {c.file_refs && c.file_refs.length > 0 && (
              <div className="concept-graph__list-refs">
                {c.file_refs.map((ref) => (
                  <span key={ref} className="concept-graph__ref-tag">
                    {ref}
                  </span>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ---------- Empty state ---------- */

function EmptyState() {
  const { t } = useTranslation();

  return (
    <div className="concept-graph__empty" role="status">
      <span className="concept-graph__empty-icon" aria-hidden="true">
        ◇
      </span>
      <span className="concept-graph__empty-text">{t('Concept.empty')}</span>
    </div>
  );
}

/* ---------- Helpers ---------- */

function truncateLabel(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 1) + '…';
}

/* ---------- Main component ---------- */

export default function ConceptGraph({ concepts, mode }: ConceptGraphProps) {
  if (mode === 'empty' || concepts.length === 0) {
    return (
      <div className="concept-graph">
        <EmptyState />
      </div>
    );
  }

  if (mode === 'learning_only') {
    return (
      <div className="concept-graph">
        <LearningList concepts={concepts} />
      </div>
    );
  }

  /* mode === 'full' */
  return (
    <div className="concept-graph">
      <FullGraph concepts={concepts} />
    </div>
  );
}
