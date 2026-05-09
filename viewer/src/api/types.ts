export type Locale = 'en' | 'zh-CN';

export type GraphifyMode = 'full' | 'learning_only' | 'empty';

export type Verdict = 'PASS' | 'CAUTION' | 'FAIL';

export type RunStatus =
  | 'baseline'
  | 'keep'
  | 'discard'
  | 'crash'
  | 'targeted_verify'
  | 'keep_final'
  | 'phase25_rewrite'
  | 'non_ratcheted';

export type SourceKind =
  | 'git_ref'
  | 'git_staged'
  | 'git_staged_unstaged'
  | 'git_unstaged'
  | 'git_since'
  | 'patch_file'
  | 'patch_stdin'
  | 'file_compare';

export type DegradedFlag =
  | 'diff_clipped'
  | 'binary_only'
  | 'file_count_exceeded'
  | 'token_exceeded';

export type DegradedFlagsMap = Partial<Record<DegradedFlag, boolean>>;

export type ReviewAnswer = 'easy' | 'good' | 'hard' | 'wrong';

export interface AuthTokenResponse {
  token: string;
  expires_at?: string | null;
}

export interface RunSummary {
  run_id: string;
  source_ref: string;
  source_kind: string;
  content_lang: string;
  capability_level: 1 | 2 | 3;
  verdict: string;
  overall: number;
  status: string;
  weakest_dim: string;
  created_at: string;
  degraded_flags: DegradedFlagsMap;
}

export interface RunDetail extends RunSummary {
  base_ref: string | null;
  prompt_version: string;
  eval_bundle_version: string;
  note_json: string | null;
  artifacts: string[];
  graphify_mode: GraphifyMode | null;
  graphify_status: string | null;
  graphify_notes?: string[] | null;
}

export type ArtifactKind =
  | 'lesson'
  | 'claims'
  | 'quiz'
  | 'misconceptions'
  | 'diff'
  | 'concepts'
  | 'score';

export interface RunArtifactEnvelope {
  run_id: string;
  artifact_type: string;
  content: string;
  content_lang?: string | null;
}

export interface ScoreDimension {
  score: number;
  max_score: number;
  reason: string;
}

export interface ScoreHardGate {
  passed: boolean;
  detail: string;
  score?: number;
  threshold?: number;
}

export interface ScorePayload {
  run_id: string;
  source_ref: string;
  source_kind: string;
  capability_level: 1 | 2 | 3;
  degraded_flags: DegradedFlagsMap;
  overall: number;
  verdict: string;
  weakest_dim: string;
  eval_bundle_version: string;
  rubric_version: string;
  dimensions: Record<string, ScoreDimension>;
  hard_gates: Record<string, ScoreHardGate>;
  notes: string[];
}

export interface RatchetHistoryEntry {
  run_id: string;
  source_ref: string;
  eval_bundle_version: string;
  overall: number;
  verdict: string;
  status: string;
  timestamp: string;
  weakest_dim: string;
  note_json: string | null;
}

export interface RatchetHistoryResponse {
  history: RatchetHistoryEntry[];
  next_cursor?: string;
}

export interface LocaleGetResponse {
  locale: Locale;
}

export interface LocalePutPayload {
  lang: Locale;
}

export interface SignalResponse {
  inserted: boolean;
  review?: ReviewUpdate;
}

export interface MarkWrongPayload {
  idempotency_key: string;
  claim_id: string;
  reason?: string | null;
}

export interface SrsReviewPayload {
  idempotency_key: string;
  card_id: string;
  answer: ReviewAnswer;
  peeked_this_session?: boolean;
  selected_choice_label?: string | null;
}

export interface QuizAnswerPayload {
  idempotency_key: string;
  quiz_id: string;
  choice: string;
  correct: boolean;
  selected_choice_label?: string | null;
}

export interface HelpfulnessPayload {
  idempotency_key: string;
  target_kind?: 'file' | 'section';
  target_id: string;
  payload?: Record<string, unknown>;
}

// --- Review Queue / Rate ---

export interface ReviewUpdate {
  card_id: string;
  rating: number;
  due_date: string;
  fsrs_state: string;
  stability: number;
  difficulty: number;
  card_state: string;
  scaffolding_level: string;
}

export type ReviewAnswerMode = 'open' | 'multiple_choice';

export interface ReviewChoice {
  label: string;
  text: string;
  is_correct: boolean;
}

export interface DueReviewCard {
  card_id: string;
  concept: string;
  run_id: string;
  due_date: string;
  scaffolding_level: string;
  display_path: string;
  source_ref?: string | null;
  symbol?: string | null;
  question?: string | null;
  answer?: string | null;
  answer_mode?: ReviewAnswerMode;
  choices?: ReviewChoice[] | null;
}

export interface ReviewQueueResponse {
  cards: DueReviewCard[];
}

export interface ReviewRatePayload {
  card_id: string;
  answer: ReviewAnswer;
  idempotency_key: string;
  peeked_this_session?: boolean;
  selected_choice_label?: string | null;
}

export type ReviewQueueState = 'archived' | 'suspended';

export interface ReviewQueueStatePayload {
  card_id: string;
  state: ReviewQueueState;
}

export interface ReviewQueueStateResponse {
  card_id: string;
  state: ReviewQueueState;
  updated: boolean;
}

export interface WeakConceptItem {
  card_id: string;
  concept: string;
  stability: number;
  difficulty: number;
  scaffolding_level: string;
  display_path: string;
}

export interface WeakConceptsResponse {
  concepts: WeakConceptItem[];
  new_concepts: WeakConceptItem[];
}

export interface ReviewMasteryItem {
  concept: string;
  review_count: number;
  avg_rating: number | null;
  last_review: string | null;
}

export interface ReviewMasteryResponse {
  mastery: ReviewMasteryItem[];
}

export interface MisconceptionCardItem {
  card_id: string;
  concept: string;
  misconception: string;
  correction: string;
  evidence_ref: string;
  severity: 'low' | 'medium' | 'high';
  safety_tags: string[];
  run_id: string;
}

export interface ReviewRateResponse {
  inserted: boolean;
  review?: ReviewUpdate;
}

// --- Paginated responses ---

export interface PaginatedRunsResponse {
  runs: RunSummary[];
  next_cursor?: string;
}

export interface PaginatedConceptsResponse {
  artifact_type: 'concepts';
  content: string;
  next_cursor?: string;
}

// --- Graph (Phase 5D) ---

export type FreshnessProjection = 'fresh' | 'stale' | 'unavailable' | 'disabled';

export interface GraphProvenance {
  graph_sha256: string;
  import_time: string;
  parser_version: string;
}

export interface GraphStatusResponse {
  enabled: boolean;
  source_exists: boolean;
  has_graph: boolean;
  freshness: FreshnessProjection | null;
  node_count: number;
  edge_count: number;
  source_path: string | null;
  provenance: GraphProvenance | null;
}

export interface ConceptGraphNode {
  id: string;
  name: string;
  kind: string | null;
  file_path: string | null;
  freshness: FreshnessProjection | null;
  metadata: Record<string, unknown>;
}

export interface ConceptGraphEdge {
  id: string;
  source: string;
  target: string;
  relation: string | null;
  weight: number;
}

export interface ConceptGraphResponse {
  status: GraphStatusResponse;
  nodes: ConceptGraphNode[];
  edges: ConceptGraphEdge[];
  truncated: boolean;
}

export interface StatsResponse {
  total_runs: number;
  total_lessons: number;
  total_quizzes: number;
  total_concepts: number;
  total_claims: number;
  total_reviews: number;
  avg_overall_score: number | null;
  weakest_dimensions: string[];
  last_run_at: string | null;
}

export interface ReviewHeatmapEntry {
  date: string;
  review_count: number;
  avg_rating: number | null;
}

export interface ReviewHeatmapResponse {
  entries: ReviewHeatmapEntry[];
}

export interface ServeStatusResponse {
  version: string;
  uptime_seconds: number;
  review_db_exists: boolean;
  runs_count: number;
}

export interface HelpfulnessAggregate {
  target_kind: string;
  target_id: string;
  signal_count: number;
  positive_count: number;
  negative_count: number;
  helpfulness_score: number;
}

export interface TransferConcept {
  concept: string;
  total_reviews: number;
  avg_rating: number;
  improving: boolean;
}

export interface LearningEffectivenessResponse {
  total_concepts_reviewed: number;
  concepts_improving: number;
  concepts_stable: number;
  concepts_declining: number;
  transfer_rate: number;
  helpfulness: HelpfulnessAggregate[];
  transfer_metrics: TransferConcept[];
}

export interface SpecAlignmentResponse {
  alignment_score: number | null;
  total_evaluated: number;
  recent_trend: 'improving' | 'stable' | 'declining' | null;
}

export interface WatchStatusResponse {
  enabled: boolean;
  running: boolean;
  last_trigger_time: number | null;
  pending_changes: number;
  restartable: boolean;
  stop_timed_out: boolean;
  consecutive_failures: number;
  total_triggers: number;
  total_failures: number;
  last_error: string | null;
  failure_threshold_hit: boolean;
}

export interface LearnSubmitPayload {
  revision?: string;
  last?: boolean;
  author?: string;
  staged?: boolean;
  unstaged?: boolean;
  include_untracked?: boolean;
  changed_paths?: string[];
  since?: string;
  patch?: string;
  compare?: [string, string];
  compare_dir?: [string, string];
  patch_url?: string;
  dry_run?: boolean;
  use_graphify?: boolean | null;
  force_learn?: boolean;
  lang?: 'auto' | Locale;
  privacy_mode?: 'strict_local' | 'redacted_remote' | 'explicit_remote';
}

export type LearnRiskLevel = 'ok' | 'warn' | 'danger';

export interface LearnEstimateResponse {
  patch_bytes: number;
  file_count: number;
  total_lines: number;
  estimated_tokens: number;
  provider_context_window: number;
  provider_max_output: number | null;
  risk_level: LearnRiskLevel;
  warnings: string[];
}

export interface TaskProgressResponse {
  current: number;
  total: number;
  message: string;
  step_started_at: string;
}

export interface TaskResultSummary {
  run_id: string | null;
  status: string | null;
  overall: number | null;
  verdict: string | null;
  warnings: string[];
}

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export type TaskErrorCode =
  | 'network_error'
  | 'timeout'
  | 'config_error'
  | 'permission_error'
  | 'claim_error'
  | 'lesson_error'
  | 'quiz_error'
  | 'learnability_error'
  | 'cancelled'
  | 'internal_error';

export type RecoveryHint = 'retry' | 'check_config' | 'check_permissions' | 'dismiss' | 'none';

export interface TaskInfoResponse {
  task_id: string;
  task_type: string;
  status: TaskStatus;
  progress: TaskProgressResponse;
  result_summary: TaskResultSummary | null;
  error: string | null;
  error_code: TaskErrorCode | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  elapsed_seconds: number | null;
  recovery_hint: RecoveryHint | null;
  timeout_seconds?: number | null;
  deadline_at?: string | null;
}

export type TaskProgressEvent =
  | { event: 'progress'; data: TaskInfoResponse }
  | { event: 'error'; data: { error: string } };

export interface TaskListResponse {
  tasks: TaskInfoResponse[];
}

export interface TaskSubmitResponse {
  task_id: string;
}

export interface TaskCancelResponse {
  cancelled: boolean;
}

/**
 * Provider mutation contracts — see `viewer/src/api/providers.ts`.
 *
 * Mirrors backend DTOs. `ProviderSummary` returned by mutation endpoints lives
 * in `config.ts` to avoid duplicating the GET-side type; both modules infer
 * from the same Zod schema (`providerSummarySchema`).
 */
export interface ProviderCreateInput {
  alias: string;
  provider_class: string;
  model_name: string;
  base_url: string;
  api_key_env: string;
  max_output_tokens?: number | null;
  thinking_level?: string | null;
}

export interface ProviderUpdateInput {
  provider_class?: string;
  model_name?: string;
  base_url?: string;
  api_key_env?: string;
  max_output_tokens?: number | null;
  thinking_level?: string | null;
}

export interface ProviderMutationResponse {
  updated: boolean;
  provider: import('./config').ProviderSummary;
}

export interface ProviderDeleteResponse {
  deleted: boolean;
  alias: string;
}

export interface ProviderProbeSubmitResponse {
  task_id: string;
  alias: string;
  status: 'submitted';
  poll_url: string;
}
