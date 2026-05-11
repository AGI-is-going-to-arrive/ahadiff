import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('react-force-graph-2d', async () => {
  const React = await import('react');
  type ForceGraphMockProps = {
    graphData?: {
      nodes?: Array<Record<string, unknown>>;
      links?: Array<Record<string, unknown>>;
    };
    nodeLabel?: (node: Record<string, unknown>) => string;
    linkLabel?: (link: Record<string, unknown>) => string;
  };
  const ForceGraph2D = React.forwardRef<unknown, ForceGraphMockProps>(
    function ForceGraph2DMock(props, ref) {
      React.useImperativeHandle(ref, () => ({ zoomToFit: () => undefined }));
      const nodes = props.graphData?.nodes ?? [];
      const links = props.graphData?.links ?? [];
      const nodeLabels = nodes.map((node) => props.nodeLabel?.(node) ?? '').join('|');
      const linkLabels = links.map((link) => props.linkLabel?.(link) ?? '').join('|');
      return (
        <canvas
          data-testid="force-graph-2d"
          data-node-count={String(nodes.length)}
          data-link-count={String(links.length)}
          data-node-labels={nodeLabels}
          data-link-labels={linkLabels}
        />
      );
    },
  );
  return {
    default: ForceGraph2D,
    __esModule: true,
  };
});

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

describe('ConceptGraph rendering guards', () => {
  it('keeps medium graphs in full graph mode without cluster controls', () => {
    const nodes = makeNodes(24, (index) => (index % 2 === 0 ? 'code' : 'rationale'));
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
    expect(html).toContain('Fit to view');
    expect(html).toContain('data-testid="force-graph-2d"');
    expect(html).toContain('data-node-count="24"');
    expect(html).toContain('Accessible graph node list');
    expect(html).not.toContain('Group by kind');
    expect(html).not.toContain('Ungroup');
  });

  it('escapes concept labels before passing them to canvas tooltips', () => {
    const maliciousLabel = '<img src=x onerror=alert(1)>';
    const nodes = makeNodes(24, () => 'code', (index) =>
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

    expect(html).toContain('data-testid="force-graph-2d"');
    expect(html).toContain('&amp;lt;img src=x onerror=alert(1)&amp;gt;');
    expect(html).not.toContain('<img src=x onerror=alert(1)>');
  });

  it('defaults very large graphs to the list while still allowing the full graph control', () => {
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
    expect(html).not.toContain('disabled=""');
    expect(html).toContain('Concept 0');
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

  it('does not mount the force graph for extreme graphs before explicit consent', () => {
    const nodes = makeNodes(1001, () => 'code');
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
    expect(html).toContain('Concept 0');
    expect(html).not.toContain('<canvas');
  });
});
