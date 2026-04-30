import { describe, expect, it } from 'vitest';
import {
  conceptGraphEdgeSchema,
  conceptGraphNodeSchema,
  conceptGraphResponseSchema,
  freshnessProjectionSchema,
  graphStatusResponseSchema,
} from '../../src/api/schemas';

describe('graph schemas', () => {
  const validStatus = {
    enabled: true,
    source_exists: true,
    has_graph: true,
    freshness: 'fresh' as const,
    node_count: 3,
    edge_count: 2,
    source_path: '.ahadiff/graphify/graph.json',
  };

  it('freshnessProjectionSchema accepts all 4 values', () => {
    for (const v of ['fresh', 'stale', 'unavailable', 'disabled']) {
      expect(freshnessProjectionSchema.parse(v)).toBe(v);
    }
  });

  it('freshnessProjectionSchema rejects unknown values', () => {
    expect(() => freshnessProjectionSchema.parse('unknown')).toThrow();
  });

  it('graphStatusResponseSchema validates correct payload', () => {
    const result = graphStatusResponseSchema.parse(validStatus);
    expect(result.enabled).toBe(true);
    expect(result.freshness).toBe('fresh');
    expect(result.node_count).toBe(3);
  });

  it('graphStatusResponseSchema accepts null freshness', () => {
    const result = graphStatusResponseSchema.parse({ ...validStatus, freshness: null });
    expect(result.freshness).toBeNull();
  });

  it('conceptGraphNodeSchema applies defaults', () => {
    const result = conceptGraphNodeSchema.parse({ id: 'n1', name: 'test' });
    expect(result.kind).toBeNull();
    expect(result.file_path).toBeNull();
    expect(result.freshness).toBeNull();
    expect(result.metadata).toEqual({});
  });

  it('conceptGraphNodeSchema rejects empty id', () => {
    expect(() => conceptGraphNodeSchema.parse({ id: '', name: 'test' })).toThrow();
  });

  it('conceptGraphEdgeSchema applies default weight', () => {
    const result = conceptGraphEdgeSchema.parse({
      id: 'e1',
      source: 'n1',
      target: 'n2',
    });
    expect(result.weight).toBe(1.0);
    expect(result.relation).toBeNull();
  });

  it('conceptGraphResponseSchema validates full payload', () => {
    const payload = {
      status: validStatus,
      nodes: [
        { id: 'n1', name: 'fn', kind: 'function', file_path: 'a.py', freshness: 'fresh', metadata: {} },
        { id: 'n2', name: 'cls', kind: null, file_path: null, freshness: null, metadata: {} },
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2', relation: 'calls', weight: 0.8 },
      ],
      truncated: false,
    };
    const result = conceptGraphResponseSchema.parse(payload);
    expect(result.nodes).toHaveLength(2);
    expect(result.edges).toHaveLength(1);
    expect(result.truncated).toBe(false);
  });

  it('conceptGraphResponseSchema defaults truncated to false', () => {
    const result = conceptGraphResponseSchema.parse({
      status: validStatus,
      nodes: [],
      edges: [],
    });
    expect(result.truncated).toBe(false);
  });

  it('rejects NaN/Infinity in edge weight', () => {
    expect(() =>
      conceptGraphEdgeSchema.parse({
        id: 'e1',
        source: 'n1',
        target: 'n2',
        weight: NaN,
      }),
    ).toThrow();
  });
});
