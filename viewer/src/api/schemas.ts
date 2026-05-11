/**
 * Phase 4F: Runtime validation for all serve-API response payloads.
 *
 * Why runtime validation when TypeScript already types these contracts:
 *  - Serve API surface and viewer ship independently. A `serve` running an
 *    older / newer schema can silently feed mis-typed payloads into the
 *    viewer; without `safeParse` we only notice when a downstream component
 *    crashes on `undefined`. With it, we surface the failure at the boundary.
 *  - Zod can be tree-shaken into per-route lazy chunks (every consumer is
 *    already lazy via `App.tsx` route splitting), so it does NOT enter the
 *    initial shell bundle. See `vite.config.ts` manualChunks vendor-misc bucket.
 *
 * Conventions:
 *  - All exported `*Schema` are the source of truth; `z.infer` types are
 *    re-exported under the same names as `types.ts` so callers can switch
 *    progressively.
 *  - `parseResponse(schema, raw)` either returns the validated value or
 *    throws `ValidationError` — caught by `validate()` helpers in api/*.ts.
 */

import { z } from 'zod';

/* ─────────────── Primitives ─────────────── */

export const localeSchema = z.enum(['en', 'zh-CN']);

export const graphifyModeSchema = z.enum(['full', 'learning_only', 'empty']);

export const verdictSchema = z.enum(['PASS', 'CAUTION', 'FAIL']);

export const runStatusSchema = z.enum([
  'baseline',
  'keep',
  'discard',
  'crash',
  'targeted_verify',
  'keep_final',
  'phase25_rewrite',
  'non_ratcheted',
]);

export const sourceKindSchema = z.enum([
  'git_ref',
  'git_staged',
  'git_staged_unstaged',
  'git_unstaged',
  'git_since',
  'patch_file',
  'patch_stdin',
  'file_compare',
]);

export const degradedFlagSchema = z.enum([
  'diff_clipped',
  'binary_only',
  'file_count_exceeded',
  'token_exceeded',
]);

export const reviewAnswerSchema = z.enum(['easy', 'good', 'hard', 'wrong']);

/* ─────────────── 1. AuthTokenResponse ─────────────── */

export const authTokenResponseSchema = z
  .object({
    token: z.string().min(1),
    expires_at: z.string().nullable().optional(),
  })
  .strict();

/* ─────────────── 2. RunSummary / RunDetail ─────────────── */

export const runSummarySchema = z.object({
  run_id: z.string().min(1),
  source_ref: z.string(),
  source_kind: z.string().min(1),
  content_lang: z.string().min(1),
  capability_level: z.union([z.literal(1), z.literal(2), z.literal(3)]),
  verdict: z.string().min(1),
  overall: z.number().finite(),
  status: z.string().min(1),
  weakest_dim: z.string(),
  created_at: z.string(),
  /**
   * V6 API may emit `degraded_flags` as a sparse map (only true keys present)
   * or omit it entirely on healthy runs. Zod 4's `record(enum, value)` rejects
   * sparse maps by default, so we use a fully-optional object and coerce
   * missing/undefined to `{}` to match `Partial<Record<DegradedFlag, boolean>>`.
   */
  degraded_flags: z
    .object({
      diff_clipped: z.boolean().optional(),
      binary_only: z.boolean().optional(),
      file_count_exceeded: z.boolean().optional(),
      token_exceeded: z.boolean().optional(),
    })
    .optional()
    .transform(
      (v): Partial<Record<z.infer<typeof degradedFlagSchema>, boolean>> => v ?? {},
    ),
});

export const runDetailSchema = runSummarySchema.extend({
  base_ref: z.string().nullable(),
  prompt_version: z.string(),
  eval_bundle_version: z.string(),
  note_json: z.string().nullable(),
  artifacts: z.array(z.string()).default([]),
  graphify_mode: graphifyModeSchema.nullable(),
  graphify_status: z.string().nullable(),
  graphify_notes: z.array(z.string()).nullable().optional(),
});

/* ─────────────── 3. RunArtifactEnvelope ─────────────── */

export const runArtifactEnvelopeSchema = z.object({
  run_id: z.string().min(1),
  artifact_type: z.string().min(1),
  content: z.string(),
  content_lang: z.string().min(1).nullable().optional(),
});

/* ─────────────── 3b. ScoreReport payload inside RunArtifactEnvelope.content ─────────────── */

export const scoreDimensionSchema = z
  .object({
    score: z.number().finite().nonnegative(),
    max_score: z.number().finite().positive(),
    reason: z.string(),
  })
  .strict()
  .refine((dimension) => dimension.score <= dimension.max_score, {
    message: 'score must be <= max_score',
    path: ['score'],
  });

export const scoreHardGateSchema = z
  .object({
    passed: z.boolean(),
    detail: z.string(),
    score: z.number().finite().nonnegative().optional(),
    threshold: z.number().finite().nonnegative().optional(),
  })
  .strict();

export const scorePayloadSchema = z
  .object({
    run_id: z.string().min(1),
    source_ref: z.string(),
    source_kind: z.string().min(1),
    capability_level: z.union([z.literal(1), z.literal(2), z.literal(3)]),
    degraded_flags: z
      .object({
        diff_clipped: z.boolean().optional(),
        binary_only: z.boolean().optional(),
        file_count_exceeded: z.boolean().optional(),
        token_exceeded: z.boolean().optional(),
      })
      .strict(),
    overall: z.number().finite().min(0).max(100),
    verdict: z.string().min(1),
    weakest_dim: z.string().min(1),
    eval_bundle_version: z.string().min(1),
    rubric_version: z.string().min(1),
    dimensions: z
      .record(z.string().min(1), scoreDimensionSchema)
      .refine((dimensions) => Object.keys(dimensions).length > 0, {
        message: 'dimensions must not be empty',
      }),
    hard_gates: z.record(z.string().min(1), scoreHardGateSchema),
    notes: z.array(z.string()),
  })
  .strict();

/* ─────────────── 4. RatchetHistory ─────────────── */

export const ratchetHistoryEntrySchema = z.object({
  run_id: z.string().min(1),
  source_ref: z.string(),
  eval_bundle_version: z.string(),
  overall: z.number().finite(),
  verdict: z.string().min(1),
  status: z.string().min(1),
  timestamp: z.string(),
  weakest_dim: z.string(),
  note_json: z.string().nullable().default(null),
}).strict();

export const ratchetHistoryResponseSchema = z.object({
  history: z.array(ratchetHistoryEntrySchema),
  next_cursor: z.string().optional(),
}).strict();

/* ─────────────── 5. Paginated runs / concepts ─────────────── */

export const paginatedRunsResponseSchema = z.object({
  runs: z.array(runSummarySchema),
  next_cursor: z.string().optional(),
});

export const paginatedConceptsResponseSchema = z.object({
  artifact_type: z.literal('concepts'),
  content: z.string(),
  next_cursor: z.string().optional(),
});

export const conceptLedgerEntrySchema = z
  .object({
    term_key: z.string().min(1),
    concept: z.string().min(1),
    display_name: z.string().default(''),
    related_claims: z.array(z.string()).default([]),
    file_refs: z.array(z.string()).default([]),
    source_refs: z.array(z.string()).default([]),
    updated_by_runs: z.array(z.string()).default([]),
  })
  .strict();

export const conceptLedgerResponseSchema = z
  .object({
    entries: z.array(conceptLedgerEntrySchema),
    next_cursor: z.string().nullable().optional(),
    total_count: z.number().int().nonnegative().default(0),
  })
  .strict();

/* ─────────────── 6. Locale ─────────────── */

export const localeGetResponseSchema = z.object({
  locale: localeSchema,
});

/* ─────────────── 7. ReviewQueue / ReviewRate / ReviewUpdate ─────────────── */

export const reviewUpdateSchema = z.object({
  card_id: z.string().min(1),
  rating: z.number().finite(),
  due_date: z.string(),
  fsrs_state: z.string(),
  stability: z.number().finite(),
  difficulty: z.number().finite(),
  card_state: z.string(),
  scaffolding_level: z.string(),
});

const reviewChoiceLabels = ['A', 'B', 'C', 'D'] as const;

export const reviewAnswerModeSchema = z.enum(['open', 'multiple_choice']);
export const reviewChoiceLabelSchema = z.enum(reviewChoiceLabels);

export const reviewChoiceSchema = z.object({
  label: reviewChoiceLabelSchema,
  text: z.string().min(1),
  is_correct: z.boolean(),
});

const reviewChoicesSchema = z
  .array(reviewChoiceSchema)
  .length(reviewChoiceLabels.length)
  .refine(
    (choices) => choices.every((choice, index) => choice.label === reviewChoiceLabels[index]),
    { message: 'review choices must be ordered A, B, C, D' },
  )
  .refine((choices) => choices.filter((choice) => choice.is_correct).length === 1, {
    message: 'review choices must contain exactly one correct choice',
  })
  .refine(
    (choices) => {
      const textKeys = choices.map((choice) => choice.text.trim().replace(/\s+/g, ' ').toLocaleLowerCase());
      return new Set(textKeys).size === textKeys.length;
    },
    { message: 'review choice text must be unique' },
  );

export const dueReviewCardSchema = z.object({
  card_id: z.string().min(1),
  concept: z.string(),
  run_id: z.string().min(1),
  due_date: z.string(),
  scaffolding_level: z.string(),
  display_path: z.string(),
  source_ref: z.string().nullable().optional(),
  symbol: z.string().nullable().optional(),
  question: z.string().nullable().optional(),
  answer: z.string().nullable().optional(),
  answer_mode: reviewAnswerModeSchema.optional(),
  choices: reviewChoicesSchema.nullable().optional(),
});

export const reviewQueueResponseSchema = z.object({
  cards: z.array(dueReviewCardSchema),
});

export const reviewRateResponseSchema = z.object({
  inserted: z.boolean(),
  review: reviewUpdateSchema.optional(),
});

export const reviewQueueStateResponseSchema = z
  .object({
    card_id: z.string().min(1),
    state: z.enum(['archived', 'suspended']),
    updated: z.boolean(),
  })
  .strict();

export const weakConceptItemSchema = z
  .object({
    card_id: z.string().min(1),
    concept: z.string(),
    stability: z.number().finite(),
    difficulty: z.number().finite(),
    scaffolding_level: z.string(),
    display_path: z.string(),
  })
  .strict();

export const weakConceptsResponseSchema = z
  .object({
    concepts: z.array(weakConceptItemSchema),
    new_concepts: z.array(weakConceptItemSchema).default([]),
  })
  .strict();

export const reviewMasteryItemSchema = z
  .object({
    concept: z.string(),
    review_count: z.number().int().nonnegative(),
    avg_rating: z.number().finite().nullable(),
    last_review: z.string().nullable(),
  })
  .strict();

export const reviewMasteryResponseSchema = z
  .object({
    mastery: z.array(reviewMasteryItemSchema),
  })
  .strict();

/* ─────────────── 8. SignalResponse (mark-wrong / srs-review / quiz / helpfulness) ─────────────── */

export const signalResponseSchema = z.object({
  inserted: z.boolean(),
  review: reviewUpdateSchema.optional(),
});

/* ─────────────── 9. MisconceptionCard ─────────────── */

export const misconceptionCardSchema = z.object({
  card_id: z.string().min(1),
  concept: z.string(),
  misconception: z.string(),
  correction: z.string(),
  evidence_ref: z.string(),
  severity: z.enum(['low', 'medium', 'high']),
  safety_tags: z.array(z.string()).default([]),
  run_id: z.string().min(1),
});

/* ─────────────── 10. Config / Doctor / Install ─────────────── */

export const captureConfigSchema = z.object({
  max_files: z.number().int().positive(),
  hard_limit: z.number().int().positive(),
  max_patch_bytes: z.number().int().positive(),
  file_ranking: z.string(),
  symbol_extractor: z.string().default('auto'),
});

export const llmConfigSchema = z.object({
  input_token_budget: z.number().int().positive(),
  output_token_budget: z.number().int().positive(),
  request_timeout_seconds: z.number().int().positive(),
  max_concurrent: z.number().int().positive(),
  retry_attempts: z.number().int().nonnegative(),
  output_lang: z.string().default('auto'),
});

export const learnConfigSchema = z.object({
  learnability_threshold: z.number().min(0).max(1).default(0.3),
  desired_retention: z.number().min(0.7).max(0.99).optional(),
});

export const configResponseSchema = z.object({
  lang: z.string().nullable(),
  privacy_mode: z.string().nullable(),
  generate_provider: z.string().nullable().default(null),
  generate_model: z.string().nullable(),
  judge_provider: z.string().nullable().default(null),
  judge_model: z.string().nullable(),
  serve_port: z.number().int().nullable(),
  key_status: z.record(z.string(), z.enum(['configured', 'missing'])).default({}),
  capture: captureConfigSchema,
  llm: llmConfigSchema,
  learn: learnConfigSchema,
});

export const configUpdateResponseSchema = z.object({
  updated: z.boolean(),
  scope: z.enum(['session']),
});

export const doctorCheckSchema = z
  .object({
    name: z.string().min(1),
    status: z.enum(['pass', 'warn', 'fail']),
    message: z.string(),
    category: z.string(),
    details: z.record(z.string(), z.unknown()).optional().default({}),
  })
  .strict();

export const doctorResponseSchema = z
  .object({
    summary_status: z.enum(['pass', 'warn', 'fail']),
    checks: z.array(doctorCheckSchema),
  })
  .strict();

export const dbCheckResultSchema = z
  .object({
    healthy: z.boolean(),
    schema_version: z.number().int().nonnegative(),
    quick_check: z.string(),
    event_count: z.number().int().nonnegative(),
    card_count: z.number().int().nonnegative(),
  })
  .strict();

export const installManifestActionSchema = z.object({
  action: z.string().min(1),
  file_strategy: z.enum(['generated', 'user-managed']),
  path: z.string().min(1),
});

export const installManifestSummarySchema = z.object({
  preview: z.array(installManifestActionSchema),
  write: z.array(installManifestActionSchema),
  uninstall: z.array(installManifestActionSchema),
});

export const installTargetSchema = z.object({
  name: z.string().min(1),
  display_name: z.string().min(1),
  detected: z.boolean(),
  platform_supported: z.boolean(),
  status: z.enum(['installed', 'available', 'unsupported', 'error']),
  description: z.string(),
  install_command: z.string().min(1).optional(),
  uninstall_command: z.string().min(1).optional(),
  manifest: installManifestSummarySchema.nullable().optional(),
  manifest_hash: z.string().length(64).nullable().optional(),
  manifest_error: z.string().nullable().optional(),
  error_message: z.string().nullable().optional(),
});

export const installTargetsResponseSchema = z.object({
  targets: z.array(installTargetSchema),
  total: z.number().int().nonnegative(),
});

export const installTargetPreviewResponseSchema = z.object({
  target: installTargetSchema,
  manifest_hash: z.string().length(64),
});

export const installTargetMutationResponseSchema = z.object({
  target: installTargetSchema,
  operation: z.enum(['install', 'uninstall']),
  updated: z.boolean(),
  updated_paths: z.array(z.string()),
  manifest_hash: z.string().length(64),
});

export const providerSummarySchema = z
  .object({
    alias: z.string().min(1),
    role: z.string().nullable().optional(),
    provider_class: z.string().min(1),
    provider_kind: z.string().min(1),
    model_name: z.string().min(1),
    base_url: z.string(),
    api_key_env: z.string().nullable().optional(),
    key_status: z.enum(['configured', 'missing', 'unknown']),
    api_family: z.string().nullable().optional(),
    api_family_version: z.string().nullable().optional(),
    max_output_tokens: z.number().int().positive().nullable().optional(),
    thinking_level: z.enum(['none', 'low', 'medium', 'high']).nullable().optional(),
    probed: z.boolean(),
    probed_max_context: z.number().int().positive().nullable(),
    probed_tpm: z.number().int().positive().nullable().optional(),
    probed_rpm: z.number().int().positive().nullable().optional(),
    probe_timestamp: z.string().nullable().optional(),
  available_models: z.array(z.string()).default([]),
  })
  .strict();

export const providersResponseSchema = z
  .object({
    providers: z.array(providerSummarySchema),
  })
  .strict();

/* ─────────────── 11b. Provider mutations (POST/PUT/DELETE/probe) ─────────────── */

/**
 * Request body for `POST /api/providers`.
 *
 * Mirrors the backend `ProviderCreateRequest` DTO. `alias`, `provider_class`,
 * `provider_kind`, `model_name`, and `base_url` are required identity fields;
 * the rest are optional override hints. Secrets are NEVER posted in plaintext —
 * `api_key_env` carries the env var NAME holding the credential.
 */
export const providerCreateRequestSchema = z
  .object({
    alias: z.string().min(1),
    provider_class: z.string().min(1),
    model_name: z.string().min(1),
    base_url: z.string().min(1),
    api_key_env: z.string().min(1),
    max_output_tokens: z.number().int().positive().nullable().optional(),
    thinking_level: z.enum(['none', 'low', 'medium', 'high']).nullable().optional(),
  })
  .strict();

export const providerUpdateRequestSchema = z
  .object({
    provider_class: z.string().min(1).optional(),
    model_name: z.string().min(1).optional(),
    base_url: z.string().min(1).optional(),
    api_key_env: z.string().min(1).optional(),
    max_output_tokens: z.number().int().positive().nullable().optional(),
    thinking_level: z.enum(['none', 'low', 'medium', 'high']).nullable().optional(),
  })
  .strict();

export const providerMutationResponseSchema = z
  .object({
    updated: z.boolean(),
    provider: providerSummarySchema,
  })
  .strict();

export const providerDeleteResponseSchema = z
  .object({
    deleted: z.boolean(),
    alias: z.string().min(1),
  })
  .strict();

export const providerProbeSubmitResponseSchema = z
  .object({
    task_id: z.string().min(1),
    alias: z.string().min(1),
    status: z.literal('submitted'),
    poll_url: z.string(),
  })
  .strict();

export const usageModelSummarySchema = z.object({
  provider_class: z.string(),
  model_id: z.string(),
  call_count: z.number().int().nonnegative(),
  total_input_tokens: z.number().int().nonnegative(),
  total_output_tokens: z.number().int().nonnegative(),
  total_cost_usd: z.number().finite().nonnegative(),
});

export const usageResponseSchema = z.object({
  models: z.array(usageModelSummarySchema),
  total_calls: z.number().int().nonnegative(),
  total_input_tokens: z.number().int().nonnegative(),
  total_output_tokens: z.number().int().nonnegative(),
  total_cost_usd: z.number().finite().nonnegative(),
  cache_hits: z.number().int().nonnegative(),
  cache_misses: z.number().int().nonnegative(),
});

export const auditResponseSchema = z.object({
  entries: z.array(z.record(z.string(), z.unknown())),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
  page: z.number().int().positive(),
  has_more: z.boolean(),
  next_cursor: z.string().nullable().optional(),
  fields: z.array(z.string()).nullable().optional(),
});

/* ─────────────── 12. Search (Phase 3D /api/search) ─────────────── */

/* Backend (`src/ahadiff/contracts/serve_runtime.py:10`) returns raw FTS rows
 * keyed by `source_table` ∈ {"concepts", "result_events", "cards", "graph_nodes"}
 * and a string `primary_key`. The viewer keeps a `kind`/`id`/`title` shape
 * because every consumer (SearchOverlay, hrefFor) was already written against
 * it. Map the wire shape to the viewer shape inside the schema so consumers
 * never see the raw column names. */
export const searchResultKindSchema = z.enum([
  'concept',
  'claim',
  'run',
  'card',
]);

const SOURCE_TABLE_TO_KIND: Record<string, z.infer<typeof searchResultKindSchema>> = {
  concepts: 'concept',
  result_events: 'run',
  cards: 'card',
  graph_nodes: 'concept',
};

export const searchResultSchema = z
  .object({
    source_table: z.string().min(1),
    primary_key: z.string().min(1),
    snippet: z.string(),
    rank: z.number().finite(),
    href: z.string().nullable().optional(),
  })
  .transform((row) => {
    const kind = SOURCE_TABLE_TO_KIND[row.source_table] ?? 'concept';
    /* Title falls back to snippet (truncated) when the backend has no name
     * column for the table — graph_nodes / cards rows often only carry
     * snippets. Consumers can still display `snippet` underneath. */
    const title = row.snippet.length > 80 ? row.snippet.slice(0, 80) + '…' : row.snippet;
    return {
      kind,
      id: row.primary_key,
      title,
      snippet: row.snippet,
      rank: row.rank,
      href: row.href ?? null,
    };
  });

export const searchResponseSchema = z.object({
  results: z.array(searchResultSchema),
  next_cursor: z.string().nullable().optional(),
});

/* ─────────────── 13. Heatmap (/api/review/heatmap) ─────────────── */

/* Backend DTO is `ReviewHeatmapResponse { entries: [{ date, review_count,
 * avg_rating }] }` (`src/ahadiff/contracts/serve_stats.py:28`). The viewer
 * presents 4 intensity buckets so we translate `review_count` to a normalized
 * `count` for downstream consumers. */
export const heatmapEntrySchema = z.object({
  date: z.string().min(1),
  review_count: z.number().int().nonnegative(),
  avg_rating: z.number().nullable(),
});

export const heatmapResponseSchema = z.object({
  entries: z.array(heatmapEntrySchema),
});

/* ─────────────── 14. Graph (Phase 5D /api/graph/*) ─────────────── */

const MIN_GRAPH_EDGE_WEIGHT = 0.1;
const MAX_GRAPH_EDGE_WEIGHT = 3.0;

export const freshnessProjectionSchema = z.enum([
  'fresh',
  'stale',
  'unavailable',
  'disabled',
]);

export const graphProvenanceSchema = z
  .object({
    graph_sha256: z.string().length(64).regex(/^[0-9a-f]{64}$/),
    import_time: z.string().min(1).max(64),
    parser_version: z.string().min(1).max(64),
  })
  .strict();

export const graphStatusResponseSchema = z
  .object({
    enabled: z.boolean(),
    source_exists: z.boolean(),
    has_graph: z.boolean(),
    freshness: freshnessProjectionSchema.nullable(),
    node_count: z.number().int().nonnegative(),
    edge_count: z.number().int().nonnegative(),
    source_path: z.string().nullable(),
    provenance: graphProvenanceSchema.nullable(),
  })
  .strict();

export const conceptGraphNodeSchema = z
  .object({
    id: z.string().min(1),
    name: z.string().min(1),
    kind: z.string().nullable().default(null),
    file_path: z.string().nullable().default(null),
    freshness: freshnessProjectionSchema.nullable().default(null),
    metadata: z.record(z.string(), z.unknown()).default({}),
  })
  .strict();

export const conceptGraphEdgeSchema = z
  .object({
    id: z.string().min(1),
    source: z.string().min(1),
    target: z.string().min(1),
    relation: z.string().nullable().default(null),
    weight: z
      .number()
      .finite()
      .min(MIN_GRAPH_EDGE_WEIGHT)
      .max(MAX_GRAPH_EDGE_WEIGHT)
      .default(1.0),
    confidence: z.enum(['EXTRACTED', 'INFERRED', 'AMBIGUOUS']).nullable().optional(),
  })
  .strict();

export const conceptGraphResponseSchema = z
  .object({
    status: graphStatusResponseSchema,
    nodes: z.array(conceptGraphNodeSchema),
    edges: z.array(conceptGraphEdgeSchema),
    truncated: z.boolean().default(false),
  })
  .strict();

export const graphRefreshResponseSchema = z
  .object({
    status: z.string().min(1),
    nodes: z.number().int().nonnegative(),
    edges: z.number().int().nonnegative(),
  })
  .strict();

/* ─────────────── 15. Learn tasks (/api/learn + /api/tasks*) ─────────────── */

export const taskProgressResponseSchema = z
  .object({
    current: z.number().int().nonnegative(),
    total: z.number().int().nonnegative(),
    message: z.string(),
    step_started_at: z.string().default(""),
  })
  .strict();

export const taskResultSummarySchema = z
  .object({
    run_id: z.string().nullable(),
    status: z.string().nullable(),
    overall: z.number().finite().min(0).max(100).nullable(),
    verdict: z.string().nullable(),
    warnings: z.array(z.string()).default([]),
  })
  .strict();

export const taskStatusSchema = z.enum([
  'pending',
  'running',
  'completed',
  'failed',
  'cancelled',
]);

export const taskErrorCodeSchema = z.enum([
  'network_error',
  'timeout',
  'config_error',
  'permission_error',
  'claim_error',
  'lesson_error',
  'quiz_error',
  'learnability_error',
  'cancelled',
  'internal_error',
]);

export const recoveryHintSchema = z.enum([
  'retry',
  'check_config',
  'check_permissions',
  'dismiss',
  'none',
]);

export const taskInfoResponseSchema = z
  .object({
    task_id: z.string().min(1),
    task_type: z.string(),
    status: taskStatusSchema,
    progress: taskProgressResponseSchema,
    result_summary: taskResultSummarySchema.nullable(),
    error: z.string().nullable(),
    error_code: taskErrorCodeSchema.nullable(),
    created_at: z.string(),
    started_at: z.string().nullable(),
    completed_at: z.string().nullable(),
    elapsed_seconds: z.number().finite().nonnegative().nullable(),
    recovery_hint: recoveryHintSchema.nullable(),
    timeout_seconds: z.number().finite().positive().nullable().optional(),
    deadline_at: z.string().nullable().optional(),
  })
  .passthrough();

export const taskProgressEventSchema = z.discriminatedUnion('event', [
  z
    .object({
      event: z.literal('progress'),
      data: taskInfoResponseSchema,
    })
    .strict(),
  z
    .object({
      event: z.literal('error'),
      data: z.object({ error: z.string() }).passthrough(),
    })
    .strict(),
]);

export const taskListResponseSchema = z
  .object({
    tasks: z.array(taskInfoResponseSchema),
  })
  .strict();

export const taskSubmitResponseSchema = z
  .object({
    task_id: z.string().min(1),
  })
  .strict();

export const taskCancelResponseSchema = z
  .object({
    cancelled: z.boolean(),
  })
  .strict();

/* ─────────────── 16. Stats (/api/stats) ─────────────── */

export const statsResponseSchema = z
  .object({
    total_runs: z.number().int().nonnegative(),
    total_lessons: z.number().int().nonnegative(),
    total_quizzes: z.number().int().nonnegative(),
    total_concepts: z.number().int().nonnegative(),
    total_claims: z.number().int().nonnegative(),
    total_reviews: z.number().int().nonnegative(),
    avg_overall_score: z.number().finite().nullable(),
    weakest_dimensions: z.array(z.string()),
    last_run_at: z.string().nullable(),
  })
  .strict();

export const serveStatusResponseSchema = z
  .object({
    version: z.string(),
    uptime_seconds: z.number().finite().nonnegative(),
    review_db_exists: z.boolean(),
    runs_count: z.number().int().nonnegative(),
  })
  .strict();

export const helpfulnessAggregateSchema = z
  .object({
    target_kind: z.string(),
    target_id: z.string(),
    signal_count: z.number().int().nonnegative(),
    positive_count: z.number().int().nonnegative(),
    negative_count: z.number().int().nonnegative(),
    helpfulness_score: z.number().finite(),
  })
  .strict();

export const transferConceptSchema = z
  .object({
    concept: z.string(),
    total_reviews: z.number().int().nonnegative(),
    avg_rating: z.number().finite(),
    improving: z.boolean(),
  })
  .strict();

export const learningEffectivenessResponseSchema = z
  .object({
    total_concepts_reviewed: z.number().int().nonnegative(),
    concepts_improving: z.number().int().nonnegative(),
    concepts_stable: z.number().int().nonnegative(),
    concepts_declining: z.number().int().nonnegative(),
    transfer_rate: z.number().finite(),
    helpfulness: z.array(helpfulnessAggregateSchema),
    transfer_metrics: z.array(transferConceptSchema),
  })
  .strict();

export const specAlignmentResponseSchema = z
  .object({
    alignment_score: z.number().finite().nullable(),
    total_evaluated: z.number().int().nonnegative(),
    recent_trend: z.enum(['improving', 'stable', 'declining']).nullable(),
  })
  .strict();

export const watchStatusResponseSchema = z
  .object({
    enabled: z.boolean(),
    running: z.boolean(),
    last_trigger_time: z.number().finite().nullable(),
    pending_changes: z.number().int().nonnegative(),
    restartable: z.boolean(),
    stop_timed_out: z.boolean(),
    consecutive_failures: z.number().int().nonnegative(),
    total_triggers: z.number().int().nonnegative(),
    total_failures: z.number().int().nonnegative(),
    last_error: z.string().nullable(),
    failure_threshold_hit: z.boolean(),
  })
  .strict();

/* ─────────────── 16. Improve preflight ─────────────── */

export const improveRunSnapshotSchema = z
  .object({
    run_id: z.string().min(1),
    source_ref: z.string(),
    overall: z.number().finite(),
    weakest_dim: z.string().nullable().optional(),
    finalized: z.boolean(),
  })
  .strict();

export const improveSessionSummarySchema = z
  .object({
    session_id: z.string().min(1),
    rounds_completed: z.number().int().nonnegative(),
    last_status: z.string().nullable().optional(),
    phase25_attempted: z.boolean(),
    has_pending_worktree: z.boolean(),
    interrupted_round: z.number().int().nullable().optional(),
    interrupted_stage: z.string().nullable().optional(),
    updated_at: z.string(),
  })
  .strict();

export const improveRepoStateSchema = z
  .object({
    branch: z.string().nullable().optional(),
    head_sha: z.string().nullable().optional(),
    prompts_dirty: z.boolean(),
  })
  .strict();

export const improvePreflightResponseSchema = z.object({
  available: z.boolean(),
  reason: z.string().nullable().optional(),
  anchor_run: improveRunSnapshotSchema.nullable().optional(),
  baseline_run: improveRunSnapshotSchema.nullable().optional(),
  target_dimension: z.string().nullable().optional(),
  target_prompt_file: z.string().nullable().optional(),
  mutable_prompts: z.array(z.string()).default([]),
  phase25_eligible: z.boolean().default(false),
  phase25_trigger_reason: z.string().nullable().optional(),
  existing_sessions: z.array(improveSessionSummarySchema).default([]),
  repo_state: improveRepoStateSchema,
  provider_configured: z.boolean(),
}).strict();

/* ─────────────── 17. Boundary helper ─────────────── */

interface RedactedIssue {
  /** Dot-joined `path` array, "<root>" if empty. */
  path: string;
  /** Zod issue code (e.g. "invalid_type", "too_small"). */
  code: string;
}

/**
 * Surfaces validation failures as a typed error so api/*.ts can map to MessageKey.
 *
 * The raw response is intentionally NOT retained: misshapen payloads from a
 * stale serve build can carry untrusted text — concept names, lesson bodies,
 * file paths — which would leak into `console.error(err)` or any error
 * collector that serializes thrown objects. Only the endpoint, issue paths,
 * and Zod codes are kept.
 */
export class ValidationError extends Error {
  override readonly name = 'ValidationError';
  public readonly issues: RedactedIssue[];

  constructor(
    public readonly endpoint: string,
    issues: z.core.$ZodIssue[],
  ) {
    const redacted: RedactedIssue[] = issues.map((i) => ({
      path: i.path.length === 0 ? '<root>' : i.path.join('.'),
      code: i.code,
    }));
    super(
      `Validation failed for ${endpoint}: ${redacted
        .map((r) => `${r.path}(${r.code})`)
        .join(', ')}`,
    );
    this.issues = redacted;
  }
}

/**
 * Validate a fetched response. Throws `ValidationError` on shape mismatch so
 * callers (in api/*.ts wrappers) can convert to a MessageKey-typed error.
 *
 * Generic over the schema's output type; callers do not need a separate
 * type assertion — the inferred type matches `types.ts` definitions.
 */
export function parseResponse<S extends z.ZodTypeAny>(
  endpoint: string,
  schema: S,
  raw: unknown,
): z.infer<S> {
  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    throw new ValidationError(endpoint, parsed.error.issues);
  }
  return parsed.data;
}
