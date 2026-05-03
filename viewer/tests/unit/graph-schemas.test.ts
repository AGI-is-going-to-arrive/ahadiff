import { describe, expect, it } from 'vitest';
import {
  authTokenResponseSchema,
  conceptGraphEdgeSchema,
  conceptGraphNodeSchema,
  conceptGraphResponseSchema,
  freshnessProjectionSchema,
  graphStatusResponseSchema,
  ratchetHistoryEntrySchema,
  ratchetHistoryResponseSchema,
  statsResponseSchema,
  taskInfoResponseSchema,
  taskResultSummarySchema,
} from '../../src/api/schemas';

describe('auth token schema', () => {
  it('accepts token and optional nullable expires_at', () => {
    expect(authTokenResponseSchema.parse({ token: 'abc' })).toEqual({ token: 'abc' });
    expect(authTokenResponseSchema.parse({ token: 'abc', expires_at: null })).toEqual({
      token: 'abc',
      expires_at: null,
    });
  });

  it('rejects empty token and unknown keys', () => {
    expect(() => authTokenResponseSchema.parse({ token: '' })).toThrow();
    expect(() => authTokenResponseSchema.parse({ token: 'abc', extra: true })).toThrow();
  });
});

describe('graph schemas', () => {
  const validStatus = {
    enabled: true,
    source_exists: true,
    has_graph: true,
    freshness: 'fresh' as const,
    node_count: 3,
    edge_count: 2,
    source_path: '.ahadiff/graphify/graph.json',
    provenance: null,
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

  it('conceptGraphNodeSchema rejects empty name and unknown keys', () => {
    expect(() => conceptGraphNodeSchema.parse({ id: 'n1', name: '' })).toThrow();
    expect(() =>
      conceptGraphNodeSchema.parse({ id: 'n1', name: 'test', extra: true }),
    ).toThrow();
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

  it('conceptGraphEdgeSchema rejects finite outlier weights', () => {
    for (const weight of [-1, 0, 1e308]) {
      expect(() =>
        conceptGraphEdgeSchema.parse({
          id: 'e1',
          source: 'n1',
          target: 'n2',
          weight,
        }),
      ).toThrow();
    }
  });

  it('conceptGraphEdgeSchema rejects empty public ids and unknown keys', () => {
    for (const patch of [{ id: '' }, { source: '' }, { target: '' }]) {
      expect(() =>
        conceptGraphEdgeSchema.parse({
          id: 'e1',
          source: 'n1',
          target: 'n2',
          ...patch,
        }),
      ).toThrow();
    }
    expect(() =>
      conceptGraphEdgeSchema.parse({
        id: 'e1',
        source: 'n1',
        target: 'n2',
        extra: true,
      }),
    ).toThrow();
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

  it('graphStatusResponseSchema rejects missing/null required fields and unknown keys', () => {
    expect(() =>
      graphStatusResponseSchema.parse({ ...validStatus, node_count: null }),
    ).toThrow();
    expect(() =>
      graphStatusResponseSchema.parse({ ...validStatus, enabled: undefined }),
    ).toThrow();
    expect(() =>
      graphStatusResponseSchema.parse({ ...validStatus, provenance: undefined }),
    ).toThrow();
    expect(() =>
      graphStatusResponseSchema.parse({ ...validStatus, extra: true }),
    ).toThrow();
  });

  it('task schemas reject out-of-range scores and missing stable fields', () => {
    expect(() =>
      taskResultSummarySchema.parse({
        run_id: 'run-1',
        status: 'completed',
        overall: 101,
        verdict: 'PASS',
        warnings: [],
      }),
    ).toThrow();

    expect(() =>
      taskInfoResponseSchema.parse({
        task_id: 'task-1',
        task_type: 'learn',
        status: 'running',
        progress: { current: 0, total: 10, message: '' },
        created_at: '2026-05-01T00:00:00Z',
      }),
    ).toThrow();
  });

  it('conceptGraphResponseSchema rejects unknown top-level keys', () => {
    expect(() =>
      conceptGraphResponseSchema.parse({
        status: validStatus,
        nodes: [],
        edges: [],
        extra: true,
      }),
    ).toThrow();
  });

  it('rejects NaN/Infinity in edge weight', () => {
    for (const weight of [NaN, Infinity, -Infinity]) {
      expect(() =>
        conceptGraphEdgeSchema.parse({
          id: 'e1',
          source: 'n1',
          target: 'n2',
          weight,
        }),
      ).toThrow();
    }
  });
});

describe('ratchet history schemas', () => {
  const validEntry = {
    run_id: 'run-1',
    source_ref: 'HEAD',
    eval_bundle_version: 'bundle-v1',
    overall: 88,
    verdict: 'PASS',
    status: 'keep',
    timestamp: '2026-05-02T00:00:00Z',
    weakest_dim: 'evidence',
    note_json: null,
  };

  it('rejects unknown entry and response keys', () => {
    expect(() => ratchetHistoryEntrySchema.parse({ ...validEntry, extra: true })).toThrow();
    expect(() =>
      ratchetHistoryResponseSchema.parse({
        history: [validEntry],
        extra: true,
      }),
    ).toThrow();
  });
});

describe('stats schema', () => {
  const validStats = {
    total_runs: 1,
    total_lessons: 1,
    total_quizzes: 1,
    total_concepts: 2,
    total_claims: 3,
    total_reviews: 4,
    avg_overall_score: 83.5,
    weakest_dimensions: ['evidence'],
    last_run_at: '2026-04-10T12:00:00Z',
  };

  it('accepts null avg_overall_score', () => {
    const result = statsResponseSchema.parse({
      ...validStats,
      avg_overall_score: null,
    });

    expect(result.avg_overall_score).toBeNull();
  });

  it('rejects unknown top-level keys', () => {
    expect(() =>
      statsResponseSchema.parse({ ...validStats, extra: true }),
    ).toThrow();
  });

  it('rejects NaN and Infinity numeric values', () => {
    for (const avg_overall_score of [NaN, Infinity, -Infinity]) {
      expect(() =>
        statsResponseSchema.parse({ ...validStats, avg_overall_score }),
      ).toThrow();
    }
    expect(() => statsResponseSchema.parse({ ...validStats, total_runs: NaN })).toThrow();
    expect(() =>
      statsResponseSchema.parse({ ...validStats, total_runs: Infinity }),
    ).toThrow();
  });
});
