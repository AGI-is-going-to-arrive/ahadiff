import { apiFetch } from './client';
import type {
  HelpfulnessPayload,
  MarkWrongPayload,
  QuizAnswerPayload,
  SignalResponse,
  SrsReviewPayload,
} from './types';

export function markWrong(payload: MarkWrongPayload): Promise<SignalResponse> {
  return apiFetch<SignalResponse>('/api/signals/mark-wrong', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function srsReview(payload: SrsReviewPayload): Promise<SignalResponse> {
  return apiFetch<SignalResponse>('/api/signals/srs-review', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function quizAnswer(payload: QuizAnswerPayload): Promise<SignalResponse> {
  return apiFetch<SignalResponse>('/api/signals/quiz-answer', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function helpfulness(payload: HelpfulnessPayload): Promise<SignalResponse> {
  return apiFetch<SignalResponse>('/api/signals/helpfulness', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
