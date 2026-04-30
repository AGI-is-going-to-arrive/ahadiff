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
  /** API may emit unknown source_kind for forward compat. */
  source_kind: z.string(),
  content_lang: z.string(),
  capability_level: z.union([z.literal(1), z.literal(2), z.literal(3)]),
  /** API may emit unknown verdict for forward compat. */
  verdict: z.string(),
  overall: z.number().finite(),
  /** API may emit unknown status for forward compat. */
  status: z.string(),
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
  content_lang: z.string().nullable().optional(),
});

/* ─────────────── 4. RatchetHistory ─────────────── */

export const ratchetHistoryEntrySchema = z.object({
  run_id: z.string().min(1),
  source_ref: z.string(),
  eval_bundle_version: z.string(),
  overall: z.number().finite(),
  verdict: z.string(),
  status: z.string(),
  timestamp: z.string(),
  weakest_dim: z.string(),
});

export const ratchetHistoryResponseSchema = z.object({
  history: z.array(ratchetHistoryEntrySchema),
  next_cursor: z.string().optional(),
});

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

export const dueReviewCardSchema = z.object({
  card_id: z.string().min(1),
  concept: z.string(),
  run_id: z.string().min(1),
  due_date: z.string(),
  scaffolding_level: z.string(),
  display_path: z.string(),
  source_ref: z.string().nullable().optional(),
  symbol: z.string().nullable().optional(),
});

export const reviewQueueResponseSchema = z.object({
  cards: z.array(dueReviewCardSchema),
});

export const reviewRateResponseSchema = z.object({
  inserted: z.boolean(),
  review: reviewUpdateSchema.optional(),
});

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

export const configResponseSchema = z.object({
  lang: z.string().nullable(),
  privacy_mode: z.string().nullable(),
  generate_model: z.string().nullable(),
  judge_model: z.string().nullable(),
  serve_port: z.number().int().nullable(),
  key_status: z.record(z.string(), z.enum(['configured', 'missing'])).default({}),
});

export const configUpdateResponseSchema = z.object({
  updated: z.boolean(),
  scope: z.enum(['session']),
});

export const doctorCheckSchema = z.object({
  name: z.string().min(1),
  status: z.enum(['pass', 'warn', 'fail']),
  message: z.string(),
  category: z.string().optional(),
  details: z.record(z.string(), z.unknown()).optional(),
});

export const doctorResponseSchema = z.object({
  summary_status: z.enum(['pass', 'warn', 'fail']).optional(),
  checks: z.array(doctorCheckSchema),
});

export const installTargetSchema = z.object({
  name: z.string().min(1),
  display_name: z.string().min(1),
  detected: z.boolean(),
  platform_supported: z.boolean(),
  status: z.enum(['installed', 'available', 'unsupported', 'error']),
  description: z.string(),
  error_message: z.string().nullable().optional(),
});

export const installTargetsResponseSchema = z.object({
  targets: z.array(installTargetSchema),
  total: z.number().int().nonnegative(),
});

export const providerSummarySchema = z.object({
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
  probed: z.boolean(),
  probed_max_context: z.number().int().positive().nullable(),
  probed_tpm: z.number().int().positive().nullable().optional(),
  probed_rpm: z.number().int().positive().nullable().optional(),
  supports_temperature: z.boolean().nullable().optional(),
  probe_timestamp: z.string().nullable().optional(),
});

export const providersResponseSchema = z.object({
  providers: z.array(providerSummarySchema),
});

export const usageModelSummarySchema = z.object({
  provider_class: z.string(),
  model_id: z.string(),
  call_count: z.number().int().nonnegative(),
  total_input_tokens: z.number().int().nonnegative(),
  total_output_tokens: z.number().int().nonnegative(),
  total_cost_usd: z.number().finite(),
});

export const usageResponseSchema = z.object({
  models: z.array(usageModelSummarySchema),
  total_calls: z.number().int().nonnegative(),
  total_input_tokens: z.number().int().nonnegative(),
  total_output_tokens: z.number().int().nonnegative(),
  total_cost_usd: z.number().finite(),
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

export const graphStatusResponseSchema = z
  .object({
    enabled: z.boolean(),
    source_exists: z.boolean(),
    has_graph: z.boolean(),
    freshness: freshnessProjectionSchema.nullable(),
    node_count: z.number().int().nonnegative(),
    edge_count: z.number().int().nonnegative(),
    source_path: z.string().nullable(),
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

/* ─────────────── 15. Stats (/api/stats) ─────────────── */

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

/* ─────────────── 16. Boundary helper ─────────────── */

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
