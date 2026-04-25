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

export type ReviewAnswer = 'good' | 'hard' | 'wrong';

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

export type ArtifactKind = 'lesson' | 'claims' | 'quiz' | 'diff' | 'concepts';

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
}

export interface LocaleGetResponse {
  locale: Locale;
}

export interface LocalePutPayload {
  lang: Locale;
}

export interface SignalResponse {
  inserted: boolean;
  review?: Record<string, unknown>;
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
}

export interface QuizAnswerPayload {
  idempotency_key: string;
  quiz_id: string;
  choice: string;
  correct: boolean;
}

export interface HelpfulnessPayload {
  idempotency_key: string;
  target_kind?: 'file';
  target_id: string;
  payload?: Record<string, unknown>;
}
