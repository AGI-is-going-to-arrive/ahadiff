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
  source_kind: SourceKind | string;
  content_lang: Locale | string;
  capability_level: 1 | 2 | 3;
  verdict: Verdict | string;
  overall: number;
  status: RunStatus | string;
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
  | 'concepts';

export interface RunArtifactEnvelope {
  run_id: string;
  artifact_type: string;
  content: string;
  content_lang?: Locale | string | null;
}

export interface RatchetHistoryEntry {
  run_id: string;
  source_ref: string;
  eval_bundle_version: string;
  overall: number;
  verdict: Verdict | string;
  status: RunStatus | string;
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
}

export interface QuizAnswerPayload {
  idempotency_key: string;
  quiz_id: string;
  choice: string;
  correct: boolean;
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

export interface DueReviewCard {
  card_id: string;
  concept: string;
  run_id: string;
  due_date: string;
  scaffolding_level: string;
  display_path: string;
  source_ref?: string | null;
  symbol?: string | null;
}

export interface ReviewQueueResponse {
  cards: DueReviewCard[];
}

export interface ReviewRatePayload {
  card_id: string;
  answer: ReviewAnswer;
  idempotency_key: string;
  peeked_this_session?: boolean;
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

export interface GraphStatusResponse {
  enabled: boolean;
  source_exists: boolean;
  has_graph: boolean;
  freshness: FreshnessProjection | null;
  node_count: number;
  edge_count: number;
  source_path: string | null;
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

export interface LearnSubmitPayload {
  revision?: string;
  last?: boolean;
  author?: string;
  staged?: boolean;
  unstaged?: boolean;
  include_untracked?: boolean;
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

export interface TaskProgressResponse {
  current: number;
  total: number;
  message: string;
}

export interface TaskResultSummary {
  run_id: string | null;
  status: string | null;
  overall: number | null;
  verdict: string | null;
  warnings: string[];
}

export interface TaskInfoResponse {
  task_id: string;
  task_type: string;
  status: string;
  progress: TaskProgressResponse;
  result_summary?: TaskResultSummary | null;
  error?: string | null;
  error_code?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  elapsed_seconds?: number | null;
}

export interface TaskListResponse {
  tasks: TaskInfoResponse[];
}

export interface TaskSubmitResponse {
  task_id: string;
}

export interface TaskCancelResponse {
  cancelled: boolean;
}
