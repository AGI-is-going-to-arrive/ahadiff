import { apiFetch } from './client';
import { parseResponse, signalResponseSchema } from './schemas';
import type {
  HelpfulnessPayload,
  MarkWrongPayload,
  QuizAnswerPayload,
  SignalResponse,
  SrsReviewPayload,
} from './types';

export async function markWrong(payload: MarkWrongPayload): Promise<SignalResponse> {
  const raw = await apiFetch<unknown>('/api/signals/mark-wrong', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return parseResponse('POST /api/signals/mark-wrong', signalResponseSchema, raw);
}

export async function srsReview(payload: SrsReviewPayload): Promise<SignalResponse> {
  const raw = await apiFetch<unknown>('/api/signals/srs-review', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return parseResponse('POST /api/signals/srs-review', signalResponseSchema, raw);
}

export async function quizAnswer(payload: QuizAnswerPayload): Promise<SignalResponse> {
  const raw = await apiFetch<unknown>('/api/signals/quiz-answer', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return parseResponse('POST /api/signals/quiz-answer', signalResponseSchema, raw);
}

export async function helpfulness(payload: HelpfulnessPayload): Promise<SignalResponse> {
  const raw = await apiFetch<unknown>('/api/signals/helpfulness', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return parseResponse('POST /api/signals/helpfulness', signalResponseSchema, raw);
}
