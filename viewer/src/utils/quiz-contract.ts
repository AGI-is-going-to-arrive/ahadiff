import type { SourceAnchor } from '../api/types';
import { sourceAnchorSchema } from '../api/schemas';

export interface QuizEvidenceAnchor {
  file: string;
  line: number;
}

export type QuizChoiceLabel = 'A' | 'B' | 'C' | 'D';

const EXPECTED_CHOICE_LABELS: readonly QuizChoiceLabel[] = ['A', 'B', 'C', 'D'];

export interface QuizChoice {
  label: QuizChoiceLabel;
  text: string;
  is_correct: boolean;
}

export type AnswerMode = 'open' | 'multiple_choice';
export type QuizKind = 'guided' | 'recall' | 'transfer';
export type ExerciseKind = 'prediction' | 'completion' | 'error_reason';
export type SelfAssessment = 'independent' | 'assisted' | 'not_yet';
export type ExerciseErrorType = 'none' | 'recall' | 'application' | 'reasoning' | 'boundary';

export interface QuizPrompt {
  question_id: string;
  review_card_id?: string | null;
  question: string;
  quiz_kind: QuizKind;
  exercise_kind?: ExerciseKind | null;
  scenario_kind?: 'new_variant' | null;
  answer_mode?: AnswerMode;
  choices?: Pick<QuizChoice, 'label' | 'text'>[] | null;
}

export interface QuizItem {
  question_id: string;
  review_card_id?: string;
  question: string;
  expected_answer: string;
  quiz_kind: QuizKind;
  exercise_kind?: ExerciseKind | null;
  scenario_kind?: 'new_variant' | null;
  source_claims: string[];
  concepts: string[];
  evidence: QuizEvidenceAnchor[];
  source_anchors?: SourceAnchor[];
  explanation?: string;
  answer_mode?: AnswerMode;
  choices?: QuizChoice[] | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function normalizeText(value: string): string {
  return value.trim().replace(/\s+/g, ' ');
}

function parseStringList(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const normalized = value
    .filter((item): item is string => typeof item === 'string')
    .map(normalizeText)
    .filter((item) => item.length > 0);
  return normalized.length === value.length ? normalized : null;
}

function parseEvidence(value: unknown): QuizEvidenceAnchor[] | null {
  if (!Array.isArray(value)) return null;
  const anchors: QuizEvidenceAnchor[] = [];
  for (const item of value) {
    if (!isRecord(item)) return null;
    const file = typeof item.file === 'string' ? normalizeText(item.file) : '';
    const line = item.line;
    if (!file || typeof line !== 'number' || !Number.isInteger(line) || line < 1) {
      return null;
    }
    anchors.push({ file, line });
  }
  return anchors;
}

function parseChoices(value: unknown, expectedAnswer: string): QuizChoice[] | null {
  if (value === null || value === undefined) return null;
  if (!Array.isArray(value)) return null;
  if (value.length !== EXPECTED_CHOICE_LABELS.length) return null;
  const choices: QuizChoice[] = [];
  const seenTexts = new Set<string>();
  let correctCount = 0;
  let correctText: string | null = null;
  for (let index = 0; index < value.length; index += 1) {
    const item = value[index];
    if (!isRecord(item)) return null;
    const expectedLabel = EXPECTED_CHOICE_LABELS[index]!;
    const rawLabel = typeof item.label === 'string' ? item.label.trim() : '';
    if (rawLabel !== expectedLabel) return null;
    const text = typeof item.text === 'string' ? normalizeText(item.text) : '';
    if (!text) return null;
    const textKey = text.toLocaleLowerCase();
    if (seenTexts.has(textKey)) return null;
    seenTexts.add(textKey);
    const isCorrect = item.is_correct === true;
    if (isCorrect) {
      correctCount += 1;
      correctText = text;
    }
    choices.push({ label: expectedLabel, text, is_correct: isCorrect });
  }
  if (correctCount !== 1) return null;
  if (correctText === null || normalizeText(correctText) !== normalizeText(expectedAnswer)) return null;
  return choices;
}

function parseQuizRecord(value: unknown): QuizItem | null {
  if (!isRecord(value)) return null;

  const questionId = typeof value.question_id === 'string' ? normalizeText(value.question_id) : '';
  let reviewCardId: string | undefined;
  if (value.review_card_id !== undefined && value.review_card_id !== null) {
    if (typeof value.review_card_id !== 'string') return null;
    const normalizedReviewCardId = normalizeText(value.review_card_id);
    if (normalizedReviewCardId) reviewCardId = normalizedReviewCardId;
  }
  const question = typeof value.question === 'string' ? value.question.trim() : '';
  const expectedAnswer =
    typeof value.expected_answer === 'string' ? value.expected_answer.trim() : '';
  const rawQuizKind = typeof value.quiz_kind === 'string' ? value.quiz_kind : null;
  const quizKind: QuizKind =
    rawQuizKind === 'guided' || rawQuizKind === 'transfer' ? rawQuizKind : 'recall';
  const sourceClaims = parseStringList(value.source_claims);
  const concepts = value.concepts === undefined ? [] : parseStringList(value.concepts);
  const evidence = parseEvidence(value.evidence ?? []);
  const anchorResult = sourceAnchorSchema.array().safeParse(value.source_anchors ?? []);
  if (!anchorResult.success) return null;
  const sourceAnchors = anchorResult.data;
  const exerciseKind = value.exercise_kind === 'prediction' || value.exercise_kind === 'completion' ||
    value.exercise_kind === 'error_reason' ? value.exercise_kind : undefined;
  if (value.exercise_kind != null && !exerciseKind) return null;
  if (value.scenario_kind != null && (value.scenario_kind !== 'new_variant' || !exerciseKind)) return null;
  const explanation =
    typeof value.explanation === 'string' ? value.explanation.trim() : undefined;
  // choices field is optional. A non-null/undefined value that fails to parse
  // (malformed shape, wrong length, missing fields) collapses to null so the
  // textarea fallback renders rather than rejecting the whole row.
  const choices = parseChoices(value.choices, expectedAnswer);
  const rawAnswerMode = typeof value.answer_mode === 'string' ? value.answer_mode : null;
  const answerMode: AnswerMode =
    rawAnswerMode === 'multiple_choice'
      ? 'multiple_choice'
      : rawAnswerMode === 'open'
        ? 'open'
        : choices && choices.length > 0
          ? 'multiple_choice'
          : 'open';

  if (
    !questionId ||
    !question ||
    !expectedAnswer ||
    !sourceClaims ||
    sourceClaims.length === 0 ||
    !concepts ||
    !evidence || (evidence.length === 0 && sourceAnchors.length === 0) ||
    (exerciseKind !== undefined && (quizKind !== 'transfer' || answerMode !== 'open' || choices))
  ) return null;

  return {
    question_id: questionId,
    question,
    expected_answer: expectedAnswer,
    quiz_kind: quizKind,
    source_claims: sourceClaims,
    concepts: concepts ?? [],
    evidence,
    answer_mode: answerMode,
    ...(exerciseKind ? { exercise_kind: exerciseKind } : {}),
    ...(value.scenario_kind === 'new_variant' && exerciseKind ? { scenario_kind: 'new_variant' as const } : {}),
    ...(sourceAnchors.length > 0 ? { source_anchors: sourceAnchors } : {}),
    ...(reviewCardId ? { review_card_id: reviewCardId } : {}),
    ...(explanation ? { explanation } : {}),
    ...(choices ? { choices } : {}),
  };
}

export function parseQuizJsonl(content: string): QuizItem[] {
  const items: QuizItem[] = [];
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const parsed = parseQuizRecord(JSON.parse(trimmed) as unknown);
      if (parsed) items.push(parsed);
    } catch {
      // Ignore malformed JSONL rows; valid rows should still render.
    }
  }
  return items;
}

/** Reject any unexpected answer-bearing fields, including in nested choices. */
export function parseQuizPrompts(value: unknown): QuizPrompt[] {
  if (!Array.isArray(value) || value.length > 30) throw new Error('Invalid quiz questions');
  const fields = new Set([
    'question_id', 'review_card_id', 'question', 'quiz_kind', 'exercise_kind', 'scenario_kind', 'answer_mode', 'choices',
  ]);
  const seenIds = new Set<string>();
  return value.map((item: unknown) => {
    if (!isRecord(item) || Object.keys(item).some((key) => !fields.has(key))) {
      throw new Error('Invalid public quiz question');
    }
    const { question_id: id, review_card_id: reviewId, question, quiz_kind: kind,
      exercise_kind: exercise, scenario_kind: scenario, answer_mode: mode, choices: rawChoices } = item;
    if (typeof id !== 'string' || !id.trim() || seenIds.has(id) ||
      typeof question !== 'string' || !question.trim() ||
      (reviewId != null && (typeof reviewId !== 'string' || !reviewId.trim())) ||
      (kind !== 'guided' && kind !== 'recall' && kind !== 'transfer') ||
      (mode !== 'open' && mode !== 'multiple_choice') ||
      (exercise != null && exercise !== 'prediction' && exercise !== 'completion' && exercise !== 'error_reason') ||
      (scenario != null && (scenario !== 'new_variant' || exercise == null))) {
      throw new Error('Invalid public quiz question');
    }
    seenIds.add(id);
    let choices: QuizPrompt['choices'] = null;
    if (rawChoices != null) {
      if (!Array.isArray(rawChoices) || rawChoices.length !== 4) throw new Error('Invalid choices');
      choices = rawChoices.map((choice: unknown, index: number) => {
        if (!isRecord(choice) || Object.keys(choice).some((key) => key !== 'label' && key !== 'text') ||
          choice.label !== EXPECTED_CHOICE_LABELS[index] || typeof choice.text !== 'string' || !choice.text.trim()) {
          throw new Error('Invalid public choice');
        }
        return { label: EXPECTED_CHOICE_LABELS[index]!, text: choice.text };
      });
      if (new Set(choices.map((choice) => normalizeText(choice.text).toLocaleLowerCase())).size !== 4) {
        throw new Error('Invalid duplicate choices');
      }
    }
    if ((mode === 'multiple_choice') !== (choices !== null) ||
      (exercise != null && (kind !== 'transfer' || mode !== 'open'))) {
      throw new Error('Invalid quiz answer mode');
    }
    return {
      question_id: id, question, quiz_kind: kind, answer_mode: mode, choices,
      ...(typeof reviewId === 'string' ? { review_card_id: reviewId } : {}),
      ...(exercise != null ? { exercise_kind: exercise } : {}),
      ...(scenario === 'new_variant' ? { scenario_kind: scenario } : {}),
    };
  });
}

export function normalizeQuizAnswer(value: string): string {
  return normalizeText(value).toLocaleLowerCase();
}

export function isQuizAnswerCorrect(answer: string, expectedAnswer: string): boolean {
  return normalizeQuizAnswer(answer) === normalizeQuizAnswer(expectedAnswer);
}

export function hasQuizReviewCard<T extends QuizPrompt>(quiz: T): quiz is T & { review_card_id: string } {
  return typeof quiz.review_card_id === 'string' && quiz.review_card_id.length > 0;
}

export function hasChoices<T extends QuizPrompt>(
  quiz: T,
): quiz is T & { choices: NonNullable<T['choices']>; answer_mode: 'multiple_choice' } {
  return quiz.answer_mode === 'multiple_choice' && Array.isArray(quiz.choices) && quiz.choices.length > 0;
}
