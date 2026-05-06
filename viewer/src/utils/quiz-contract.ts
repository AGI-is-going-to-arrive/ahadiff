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

export interface QuizItem {
  question_id: string;
  review_card_id?: string;
  question: string;
  expected_answer: string;
  source_claims: string[];
  concepts: string[];
  evidence: QuizEvidenceAnchor[];
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
  return anchors.length > 0 ? anchors : null;
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
  if (correctText === null || normalizeText(correctText) !== expectedAnswer) return null;
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
  const question = typeof value.question === 'string' ? normalizeText(value.question) : '';
  const expectedAnswer =
    typeof value.expected_answer === 'string' ? normalizeText(value.expected_answer) : '';
  const sourceClaims = parseStringList(value.source_claims);
  const concepts = value.concepts === undefined ? [] : parseStringList(value.concepts);
  const evidence = parseEvidence(value.evidence);
  const explanation =
    typeof value.explanation === 'string' ? normalizeText(value.explanation) : undefined;
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
    !evidence
  ) return null;

  return {
    question_id: questionId,
    question,
    expected_answer: expectedAnswer,
    source_claims: sourceClaims,
    concepts: concepts ?? [],
    evidence,
    answer_mode: answerMode,
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

export function normalizeQuizAnswer(value: string): string {
  return normalizeText(value).toLocaleLowerCase();
}

export function isQuizAnswerCorrect(answer: string, expectedAnswer: string): boolean {
  return normalizeQuizAnswer(answer) === normalizeQuizAnswer(expectedAnswer);
}

export function hasQuizReviewCard(quiz: QuizItem): quiz is QuizItem & { review_card_id: string } {
  return typeof quiz.review_card_id === 'string' && quiz.review_card_id.length > 0;
}

export function hasChoices(
  quiz: QuizItem,
): quiz is QuizItem & { choices: QuizChoice[]; answer_mode: 'multiple_choice' } {
  return quiz.answer_mode === 'multiple_choice' && Array.isArray(quiz.choices) && quiz.choices.length > 0;
}
