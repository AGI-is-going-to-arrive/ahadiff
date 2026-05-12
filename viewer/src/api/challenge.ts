import { ApiError, apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  challengeEnvelopeSchema,
  challengeFeedbackEnvelopeSchema,
  challengeFeedbackSchema,
  challengeStateEnvelopeSchema,
  parseResponse,
} from './schemas';

export type ChallengeStage =
  | 'idle'
  | 'build'
  | 'tour'
  | 'challenge'
  | 'review'
  | 'adapt';

export const CHALLENGE_STAGES = [
  'build',
  'tour',
  'challenge',
  'review',
  'adapt',
] as const satisfies readonly Exclude<ChallengeStage, 'idle'>[];

export interface ChallengeState {
  challenge_id: string;
  source_run_id: string;
  stage: ChallengeStage;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface ChallengeManifest {
  challenge_id: string;
  source_run_id: string;
  canonical_patch: string;
  [key: string]: unknown;
}

export interface ChallengeEnvelope {
  state: ChallengeState;
  manifest?: ChallengeManifest | null;
}

export interface ChallengeStateEnvelope {
  state: ChallengeState;
}

/**
 * Per-file hunk coverage entry as returned by the backend.
 * Mirrors `ahadiff.challenge.engine.review_attempt()`.
 */
export interface ChallengeHunkCoverage {
  path: string;
  canonical_hunks: number;
  matched_hunks: number;
  missing_hunks: number;
}

/**
 * Summary of the adapt step (mark_wrong signals written for gap claim ids).
 * Mirrors `ahadiff.challenge.adapt.adapt_from_gaps()`.
 */
export interface ChallengeAdaptSummary {
  challenge_id: string;
  inserted_claim_ids: string[];
  duplicate_claim_ids: string[];
  signal_count: number;
}

/**
 * Feedback envelope returned by POST /api/challenge/{id}/review and persisted
 * to feedback.json. After review the backend automatically transitions
 * CHALLENGE → REVIEW → ADAPT → IDLE; the `state` field is the final state.
 */
export interface ChallengeFeedback {
  challenge_id: string;
  source_run_id: string;
  missing_files: string[];
  extra_files: string[];
  hunk_coverage: ChallengeHunkCoverage[];
  gap_claim_ids: string[];
  all_canonical_claim_ids: string[];
  adapt: ChallengeAdaptSummary;
  state: ChallengeState;
}

/**
 * Wrapper returned by GET /api/challenge/{id}/feedback. `feedback` is null
 * when no review has been submitted yet for this challenge.
 */
export interface ChallengeFeedbackEnvelope {
  feedback: ChallengeFeedback | null;
}

/**
 * Symbolic error code used by the backend when the challenge feature flag is
 * disabled (HTTP 501). The UI uses this to short-circuit into a "feature off"
 * panel instead of surfacing a raw error. Keep in sync with backend
 * `ErrorCode.FEATURE_UNAVAILABLE`.
 */
export const CHALLENGE_FEATURE_UNAVAILABLE_CODE = 'FEATURE_UNAVAILABLE';

export function isChallengeFeatureDisabled(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false;
  return err.status === 501 && err.errorCode === CHALLENGE_FEATURE_UNAVAILABLE_CODE;
}

function encode(id: string): string {
  return encodeURIComponent(id);
}

interface JsonBodyInit extends Omit<ApiFetchOptions, 'method' | 'body'> {
  body?: unknown;
}

function buildInit(method: string, init?: JsonBodyInit): ApiFetchOptions {
  const { body, ...rest } = init ?? {};
  const headers = new Headers(rest.headers);
  if (body !== undefined && !headers.has('content-type')) {
    headers.set('content-type', 'application/json');
  }
  return {
    ...rest,
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

export async function buildChallenge(
  runId: string,
  challengeId?: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ChallengeEnvelope> {
  const body: Record<string, string> = { run_id: runId };
  if (challengeId) body.challenge_id = challengeId;
  const raw = await apiFetch<unknown>(
    '/api/challenge/build',
    buildInit('POST', { ...opts, body }),
  );
  return parseResponse('POST /api/challenge/build', challengeEnvelopeSchema, raw);
}

export async function getChallenge(
  challengeId: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ChallengeEnvelope> {
  const raw = await apiFetch<unknown>(`/api/challenge/${encode(challengeId)}`, opts);
  return parseResponse('GET /api/challenge/{challengeId}', challengeEnvelopeSchema, raw);
}

export async function advanceChallenge(
  challengeId: string,
  targetStage?: ChallengeStage,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ChallengeStateEnvelope> {
  const body: Record<string, string> = {};
  if (targetStage) body.target_stage = targetStage;
  const raw = await apiFetch<unknown>(
    `/api/challenge/${encode(challengeId)}/advance`,
    buildInit('POST', { ...opts, body }),
  );
  return parseResponse(
    'POST /api/challenge/{challengeId}/advance',
    challengeStateEnvelopeSchema,
    raw,
  );
}

export async function abortChallenge(
  challengeId: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ChallengeStateEnvelope> {
  const raw = await apiFetch<unknown>(
    `/api/challenge/${encode(challengeId)}/abort`,
    buildInit('POST', { ...opts, body: {} }),
  );
  return parseResponse(
    'POST /api/challenge/{challengeId}/abort',
    challengeStateEnvelopeSchema,
    raw,
  );
}

export async function submitReview(
  challengeId: string,
  learnerDiff: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ChallengeFeedback> {
  const raw = await apiFetch<unknown>(
    `/api/challenge/${encode(challengeId)}/review`,
    buildInit('POST', { ...opts, body: { learner_diff: learnerDiff } }),
  );
  return parseResponse(
    'POST /api/challenge/{challengeId}/review',
    challengeFeedbackSchema,
    raw,
  );
}

export async function getChallengeFeedback(
  challengeId: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ChallengeFeedbackEnvelope> {
  const raw = await apiFetch<unknown>(
    `/api/challenge/${encode(challengeId)}/feedback`,
    opts,
  );
  return parseResponse(
    'GET /api/challenge/{challengeId}/feedback',
    challengeFeedbackEnvelopeSchema,
    raw,
  );
}
