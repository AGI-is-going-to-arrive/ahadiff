import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { buildClusterPlan } from './ConceptGraph';
import ConceptGraph from './ConceptGraph';
import type { ConceptGraphEdge, ConceptGraphNode } from '../api/types';

function makeNodes(
  count: number,
  kindFor: (index: number) => string | null,
  nameFor: (index: number) => string = (index) => `Concept ${index}`,
): ConceptGraphNode[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `n-${index}`,
    name: nameFor(index),
    kind: kindFor(index),
    file_path: null,
    freshness: null,
    metadata: {},
  }));
}

function makeChainEdges(count: number): ConceptGraphEdge[] {
  return Array.from({ length: count - 1 }, (_, index) => ({
    id: `e-${index}`,
    source: `n-${index}`,
    target: `n-${index + 1}`,
    relation: null,
    weight: 1,
  }));
}

describe('ConceptGraph clustering', () => {
  it('groups large mixed-kind graphs by kind and aggregates inter-cluster edges', () => {
    const nodes = makeNodes(24, (index) => (index % 2 === 0 ? 'code' : 'rationale'));
    const plan = buildClusterPlan(nodes, makeChainEdges(nodes.length));

    expect(plan.groupedBy).toBe('kind');
    expect(plan.clusters).toHaveLength(2);
    expect(plan.clusters.map((cluster) => cluster.members.length).sort((a, b) => a - b)).toEqual([
      12,
      12,
    ]);
    expect(plan.edges).toHaveLength(1);
    expect(plan.edges[0]?.count).toBe(23);
  });

  it('falls back to prefix grouping for a single-kind large graph', () => {
    const nodes = makeNodes(24, () => 'code', (index) =>
      index < 12 ? `Alpha ${index}` : `Beta ${index}`,
    );
    const plan = buildClusterPlan(nodes, makeChainEdges(nodes.length));

    expect(plan.groupedBy).toBe('prefix');
    expect(plan.clusters.map((cluster) => cluster.label).sort()).toEqual(['ALP', 'BET']);
    expect(plan.nodeToCluster.get('n-0')).toBe('cluster:prefix:alp');
    expect(plan.nodeToCluster.get('n-23')).toBe('cluster:prefix:bet');
  });
});

describe('ConceptGraph rendering guards', () => {
  it('disables graph mode for very large graphs', () => {
    const nodes = makeNodes(201, () => 'code');
    const html = renderToStaticMarkup(
      <ConceptGraph
        status={{
          enabled: true,
          source_exists: true,
          has_graph: true,
          freshness: 'fresh',
          node_count: nodes.length,
          edge_count: nodes.length - 1,
          source_path: null,
          provenance: null,
        }}
        nodes={nodes}
        edges={makeChainEdges(nodes.length)}
        truncated={false}
      />,
    );

    expect(html).toContain('Full graph');
    expect(html).toContain('List view');
    expect(html).toContain('disabled=""');
  });

  it('escapes concept labels when large graphs render as a list', () => {
    const maliciousLabel = '<img src=x onerror=alert(1)>';
    const nodes = makeNodes(201, () => 'code', (index) =>
      index === 0 ? maliciousLabel : `Concept ${index}`,
    );
    const html = renderToStaticMarkup(
      <ConceptGraph
        status={{
          enabled: true,
          source_exists: true,
          has_graph: true,
          freshness: 'fresh',
          node_count: nodes.length,
          edge_count: 0,
          source_path: null,
          provenance: null,
        }}
        nodes={nodes}
        edges={[]}
        truncated={false}
      />,
    );

    expect(html).toContain('&lt;img src=x onerror=alert(1)&gt;');
    expect(html).not.toContain('<img src=x onerror=alert(1)>');
  });
});
