import { describe, expect, it } from 'vitest';
import {
  authTokenResponseSchema,
  challengeFeedbackSchema,
  conceptGraphEdgeSchema,
  conceptGraphNodeSchema,
  conceptGraphResponseSchema,
  freshnessProjectionSchema,
  graphStatusResponseSchema,
  judgeFailureSchema,
  learningEffectivenessResponseSchema,
  conceptLedgerEntrySchema,
  ratchetHistoryEntrySchema,
  ratchetHistoryResponseSchema,
  reviewMasteryResponseSchema,
  runSummarySchema,
  scorePayloadSchema,
  serveStatusResponseSchema,
  specAlignmentArtifactSchema,
  specAlignmentResponseSchema,
  statsResponseSchema,
  taskInfoResponseSchema,
  taskResultSummarySchema,
  usageResponseSchema,
  watchStatusResponseSchema,
  weakConceptsResponseSchema,
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

describe('judge failure schema', () => {
  const validFailure = {
    schema: 'ahadiff.judge_failure.v1',
    provider_class: 'openai_responses',
    model_name: 'gpt-5.5-mini',
    error_type: 'InputError',
    message: '评审失败 😀'.repeat(200),
    created_at: '2026-05-23T00:00:00Z',
  };

  it('uses the backend schema literal and counts Unicode by code point', () => {
    expect(judgeFailureSchema.parse(validFailure).schema).toBe('ahadiff.judge_failure.v1');
    expect(judgeFailureSchema.parse({ ...validFailure, message: '😀'.repeat(2000) }).message)
      .toHaveLength(4000);
    expect(() =>
      judgeFailureSchema.parse({ ...validFailure, schema: 'ahadiff.judge_failure.v2' }),
    ).toThrow();
    expect(() =>
      judgeFailureSchema.parse({ ...validFailure, message: '😀'.repeat(2001) }),
    ).toThrow();
  });
});

describe('challenge schemas', () => {
  const validFeedback = {
    challenge_id: 'c1',
    source_run_id: 'run_123',
    missing_files: [],
    extra_files: [],
    hunk_coverage: [
      {
        path: 'src/foo.py',
        canonical_hunks: 1,
        matched_hunks: 1,
        missing_hunks: 0,
      },
    ],
    gap_claim_ids: [],
    all_canonical_claim_ids: ['claim-1'],
    adapt: {
      challenge_id: 'c1',
      inserted_claim_ids: [],
      duplicate_claim_ids: [],
      signal_count: 0,
    },
    state: {
      challenge_id: 'c1',
      source_run_id: 'run_123',
      stage: 'idle',
      created_at_utc: '2026-05-12T00:00:00Z',
      updated_at_utc: '2026-05-12T00:00:00Z',
    },
  };

  it('requires gap_claim_ids so stale backend feedback cannot look perfect', () => {
    expect(challengeFeedbackSchema.parse(validFeedback).gap_claim_ids).toEqual([]);
    const { gap_claim_ids: _gapClaimIds, ...missingGapIds } = validFeedback;
    expect(() => challengeFeedbackSchema.parse(missingGapIds)).toThrow();
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

  it('conceptLedgerEntrySchema accepts nullable Graphify node ids', () => {
    expect(
      conceptLedgerEntrySchema.parse({
        term_key: 'concept-1',
        concept: 'concept-1',
        graphify_node_id: 'node-1',
      }).graphify_node_id,
    ).toBe('node-1');
    expect(
      conceptLedgerEntrySchema.parse({
        term_key: 'concept-1',
        concept: 'concept-1',
        graphify_node_id: null,
      }).graphify_node_id,
    ).toBeNull();
    expect(() =>
      conceptLedgerEntrySchema.parse({
        term_key: 'concept-1',
        concept: 'concept-1',
        graphify_node_id: '',
      }),
    ).toThrow();
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

  it('taskInfoResponseSchema tolerates forward-compatible top-level keys', () => {
    const result = taskInfoResponseSchema.parse({
      task_id: 'task-1',
      task_type: 'learn',
      status: 'running',
      progress: { current: 1, total: 10, message: 'Running' },
      result_summary: null,
      error: null,
      error_code: null,
      created_at: '2026-05-01T00:00:00Z',
      started_at: '2026-05-01T00:00:01Z',
      completed_at: null,
      elapsed_seconds: 1,
      recovery_hint: null,
      future_field: 'ok',
    });

    expect(result.future_field).toBe('ok');
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

describe('score payload schema', () => {
  const validScorePayload = {
    run_id: 'run_0123456789abcdef0123456789abcdef',
    source_ref: 'HEAD',
    source_kind: 'git_ref',
    capability_level: 3,
    degraded_flags: {},
    overall: 94.5,
    verdict: 'PASS',
    weakest_dim: 'learnability',
    eval_bundle_version: 'bundle-v1',
    rubric_version: 'v0.1',
    dimensions: {
      accuracy: {
        score: 18,
        max_score: 20,
        reason: 'claim status mix',
      },
    },
    hard_gates: {
      accuracy: {
        passed: true,
        detail: 'accuracy score passed',
        score: 18,
        threshold: 14,
      },
    },
    notes: [],
  };

  it('accepts ScoreReport.to_payload shaped score artifacts', () => {
    const parsed = scorePayloadSchema.parse(validScorePayload);

    expect(parsed.dimensions.accuracy?.score).toBe(18);
    expect(parsed.hard_gates.accuracy?.passed).toBe(true);
  });

  it('rejects unsafe score numbers and missing stable fields', () => {
    expect(() =>
      scorePayloadSchema.parse({
        ...validScorePayload,
        dimensions: {
          accuracy: { score: Number.NaN, max_score: 20, reason: 'bad' },
        },
      }),
    ).toThrow();

    expect(() =>
      scorePayloadSchema.parse({
        ...validScorePayload,
        dimensions: {
          accuracy: { score: 21, max_score: 20, reason: 'bad' },
        },
      }),
    ).toThrow();

    expect(() => scorePayloadSchema.parse({ ...validScorePayload, notes: undefined })).toThrow();
  });

  it('rejects unknown top-level keys', () => {
    expect(() => scorePayloadSchema.parse({ ...validScorePayload, extra: true })).toThrow();
  });
});

describe('run summary schemas', () => {
  const validRun = {
    run_id: 'run-1',
    source_ref: 'HEAD',
    source_kind: 'git_ref',
    content_lang: 'en',
    capability_level: 3,
    verdict: 'PASS',
    overall: 88,
    status: 'keep',
    weakest_dim: 'evidence',
    created_at: '2026-05-02T00:00:00Z',
    degraded_flags: {},
  };

  it('keeps display enums forward-compatible at the viewer boundary', () => {
    expect(runSummarySchema.parse({ ...validRun, source_kind: 'future_source' }).source_kind)
      .toBe('future_source');
    expect(runSummarySchema.parse({ ...validRun, content_lang: 'fr' }).content_lang)
      .toBe('fr');
    expect(runSummarySchema.parse({ ...validRun, verdict: 'WARN' }).verdict)
      .toBe('WARN');
    expect(runSummarySchema.parse({ ...validRun, status: 'completed' }).status)
      .toBe('completed');
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

describe('settings and auxiliary API schemas', () => {
  it('rejects negative usage costs', () => {
    const validUsage = {
      models: [
        {
          provider_class: 'openai',
          model_id: 'gpt-5.4-mini',
          call_count: 1,
          total_input_tokens: 10,
          total_output_tokens: 5,
          total_cost_usd: 0.01,
        },
      ],
      total_calls: 1,
      total_input_tokens: 10,
      total_output_tokens: 5,
      total_cost_usd: 0.01,
      cache_hits: 0,
      cache_misses: 1,
    };

    expect(() => usageResponseSchema.parse({ ...validUsage, total_cost_usd: -0.01 })).toThrow();
    expect(() =>
      usageResponseSchema.parse({
        ...validUsage,
        models: [{ ...validUsage.models[0], total_cost_usd: -0.01 }],
      }),
    ).toThrow();
  });

  it('validates serve status, spec alignment, watch, mastery, and weak concepts', () => {
    expect(
      serveStatusResponseSchema.parse({
        version: '0.1.0a0',
        uptime_seconds: 1.5,
        review_db_exists: true,
        runs_count: 1,
      }),
    ).toMatchObject({ runs_count: 1 });

    expect(
      specAlignmentResponseSchema.parse({
        alignment_score: null,
        total_evaluated: 0,
        recent_trend: null,
        total_requirements: 0,
        implemented: 0,
        partial: 0,
        missing: 0,
        unknown: 0,
        degraded_count: 0,
        semantic_reviewed: 0,
        semantic_degraded_count: 0,
        semantic_disagreement_count: 0,
      }),
    ).toMatchObject({ total_evaluated: 0 });

    expect(
      specAlignmentArtifactSchema.parse({
        artifact: 'spec_alignment',
        schema: 'ahadiff.spec_alignment',
        schema_version: 1,
        applicability: 'applicable',
        status: 'scored',
        requirements: [
          {
            id: 'REQ-001',
            text: 'Must expose `--against-spec`.',
            classification: 'implemented',
            severity: 'high',
            evidence_refs: [
              {
                type: 'patch',
                file: 'src/ahadiff/cli.py',
                lines: [1, 2],
                anchors: ['--against-spec'],
                side: 'new',
              },
            ],
            confidence: 0.82,
            reason: 'Captured diff added all required code anchors.',
          },
        ],
        summary: { implemented: 1, partial: 0, missing: 0, unknown: 0 },
        score: 10,
        max_score: 10,
        confidence: 0.82,
        semantic_review: {
          enabled: true,
          provider: 'openai_responses',
          model: 'gpt-5.5',
          prompt_digest: 'abc123',
          input_digest: 'def456',
          requirements: [
            {
              id: 'REQ-001',
              classification: 'implemented',
              confidence: 0.8,
              rationale: 'Evidence supports the requirement.',
              evidence_refs: [
                {
                  type: 'patch',
                  file: 'src/ahadiff/cli.py',
                  lines: [1, 2],
                  anchors: ['--against-spec'],
                  side: 'new',
                },
              ],
              disagreement_with_deterministic: false,
            },
          ],
          aggregate: {
            implemented: 1,
            partial: 0,
            missing: 0,
            unknown: 0,
            violated: 0,
            confidence: 0.8,
            risk_flags: [],
          },
          degraded: false,
          degradation_reason: null,
          limitations: ['Semantic review is not a proof.'],
        },
        semantic_adjustment: {
          policy: 'conservative_evidence_bound',
          score: 10,
          delta: 0,
          reason: 'semantic review recorded; deterministic score retained',
        },
        matcher: {
          mode: 'deterministic_structured',
          claim_count: 0,
          uses_code_anchors: true,
          uses_patch_added_lines: true,
          detects_forbidden_additions: true,
        },
        known_limitations: [],
      }).requirements[0].evidence_refs[0].anchors,
    ).toEqual(['--against-spec']);

    expect(
      watchStatusResponseSchema.parse({
        enabled: false,
        running: false,
        last_trigger_time: null,
        pending_changes: 0,
        restartable: true,
        stop_timed_out: false,
        consecutive_failures: 0,
        total_triggers: 0,
        total_failures: 0,
        last_error: null,
        failure_threshold_hit: false,
      }),
    ).toMatchObject({ enabled: false });

    expect(
      weakConceptsResponseSchema.parse({
        concepts: [
          {
            card_id: 'card-1',
            concept: 'learn-from-diff',
            stability: 1.2,
            difficulty: 7.3,
            scaffolding_level: '2',
            display_path: 'demo.py',
          },
        ],
      }),
    ).toMatchObject({ concepts: expect.any(Array) });

    expect(
      reviewMasteryResponseSchema.parse({
        mastery: [
          {
            concept: 'learn-from-diff',
            review_count: 3,
            avg_rating: 2.7,
            last_review: '2026-04-27T00:00:00Z',
          },
        ],
      }),
    ).toMatchObject({ mastery: expect.any(Array) });
  });

  it('validates learning effectiveness DTO', () => {
    expect(
      learningEffectivenessResponseSchema.parse({
        total_concepts_reviewed: 1,
        concepts_improving: 1,
        concepts_stable: 0,
        concepts_declining: 0,
        transfer_rate: 1,
        helpfulness: [
          {
            target_kind: 'section',
            target_id: 'run-1:intro',
            signal_count: 2,
            positive_count: 2,
            negative_count: 0,
            helpfulness_score: 1,
          },
        ],
        transfer_metrics: [
          {
            concept: 'learn-from-diff',
            total_reviews: 3,
            avg_rating: 2.7,
            improving: true,
          },
        ],
      }),
    ).toMatchObject({ transfer_rate: 1 });
  });
});
