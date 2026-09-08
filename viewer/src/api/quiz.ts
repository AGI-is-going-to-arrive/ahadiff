import { z } from 'zod';
import { apiFetch, type ApiFetchOptions } from './client';
import { parseResponse } from './schemas';
import { parseQuizJsonl, parseQuizPrompts, type QuizChoiceLabel, type QuizItem, type QuizPrompt } from '../utils/quiz-contract';

const questionsSchema = z.object({ run_id: z.string().min(1), questions: z.array(z.unknown()) }).strict();
const revealSchema = z.object({
  run_id: z.string().min(1),
  question: z.unknown(),
  correct: z.boolean().nullable(),
  feedback_kind: z.enum(['choice_check', 'reference_comparison', 'semantic_self_assessment']),
}).strict();

export interface QuizRevealResponse {
  run_id: string;
  question: QuizItem;
  correct: boolean | null;
  feedback_kind: 'choice_check' | 'reference_comparison' | 'semantic_self_assessment';
}

export async function getQuizQuestions(
  runId: string, opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<{ run_id: string; questions: QuizPrompt[] }> {
  const raw = await apiFetch<unknown>(`/api/run/${encodeURIComponent(runId)}/quiz/questions`, opts);
  const result = parseResponse('GET /api/run/{runId}/quiz/questions', questionsSchema, raw);
  const questions = parseQuizPrompts(result.questions);
  if (result.run_id !== runId || questions.length !== result.questions.length) throw new Error('Invalid quiz prompts');
  return { run_id: result.run_id, questions };
}

export async function revealQuizQuestion(
  runId: string, questionId: string,
  payload: { attempted: true; selected_choice_label?: QuizChoiceLabel },
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<QuizRevealResponse> {
  const raw = await apiFetch<unknown>(
    `/api/run/${encodeURIComponent(runId)}/quiz/${encodeURIComponent(questionId)}/reveal`,
    { ...opts, method: 'POST', body: JSON.stringify(payload) },
  );
  const result = parseResponse('POST /api/run/{runId}/quiz/{questionId}/reveal', revealSchema, raw);
  const question = parseQuizJsonl(JSON.stringify(result.question))[0];
  if (result.run_id !== runId || question?.question_id !== questionId) throw new Error('Invalid revealed quiz');
  return { ...result, question };
}
