import { describe, expect, it } from 'vitest';
import { activePracticeSummarySchema, practiceAttemptSummarySchema } from '../api/schemas';
import {
  hasChoices,
  hasQuizReviewCard,
  isQuizAnswerCorrect,
  parseQuizJsonl,
  parseQuizPrompts,
} from './quiz-contract';

describe('quiz contract helpers', () => {
  it('keeps absent practice measurements distinct from observed zero', () => {
    expect(practiceAttemptSummarySchema.parse({ attempts: 0, independent_rate: null }).independent_rate).toBeNull();
    expect(practiceAttemptSummarySchema.parse({ attempts: 1, independent_rate: 0 }).independent_rate).toBe(0);
    for (const value of [
      { attempts: 0, independent_rate: 0 }, { attempts: 1, independent_rate: null },
      { attempts: 1, independent_rate: Number.NaN }, { attempts: true, independent_rate: 1 },
      { attempts: 1, independent_rate: Number.POSITIVE_INFINITY }, { attempts: 1, independent_rate: 1.1 },
    ]) expect(practiceAttemptSummarySchema.safeParse(value).success).toBe(false);
    expect(activePracticeSummarySchema.safeParse({
      initial: {attempts:0,independent_rate:null}, delayed_recall:{attempts:0,independent_rate:null},
      unseen_variant:{attempts:0,independent_rate:null},
      error_types:{none:0,recall:0,application:0,reasoning:0,boundary:0}, feedback_kind:'executed_tests',
    }).success).toBe(false);
  });

  it('accepts multiline active prompts and rejects answer-bearing public fields', () => {
    const prompt = {
      question_id: 'quiz_exercise_1', question: 'Complete:\nif failed:\n    ____',
      quiz_kind: 'transfer', exercise_kind: 'completion', scenario_kind: 'new_variant',
      answer_mode: 'open', choices: null,
    };
    expect(parseQuizPrompts([prompt])[0]?.question).toBe(prompt.question);
    for (const field of ['expected_answer', 'explanation', 'evidence', 'source_anchors', 'concepts', 'source_claims']) {
      expect(() => parseQuizPrompts([{ ...prompt, [field]: 'private reference' }])).toThrow();
    }
    expect(() => parseQuizPrompts([{ ...prompt, exercise_kind: 'execute' }])).toThrow();
    expect(() => parseQuizPrompts([prompt, prompt])).toThrow();
  });

  it('rejects correctness flags inside public choices', () => {
    const prompt = {
      question_id: 'quiz_1', question: 'Choose a path', quiz_kind: 'recall', answer_mode: 'multiple_choice',
      choices: ['A', 'B', 'C', 'D'].map(label => ({ label, text: `Path ${label}` })),
    };
    expect(parseQuizPrompts([prompt])[0]?.choices).toHaveLength(4);
    expect(() => parseQuizPrompts([{ ...prompt, choices: prompt.choices.map((choice, index) => ({ ...choice, is_correct: index === 0 })) }])).toThrow();
  });

  it('does not reinterpret corrupt active metadata as legacy text grading', () => {
    const row = {question_id:'quiz_exercise_1',question:'Example',expected_answer:'Reference',
      quiz_kind:'transfer',answer_mode:'open',exercise_kind:'unknown',source_claims:['claim-1'],
      evidence:[{file:'sample.py',line:1}]};
    expect(parseQuizJsonl(JSON.stringify(row))).toEqual([]);
  });

  it('parses real quiz.jsonl rows and rejects legacy choice rows', () => {
    const realRow = JSON.stringify({
      question_id: 'quiz_1',
      review_card_id: 'card_explicit_1',
      question: 'What does the new comment indicate?',
      expected_answer: 'A learn-from-diff marker',
      source_claims: ['c1'],
      concepts: ['learn-from-diff'],
      evidence: [{ file: 'demo.py', line: 4 }],
      explanation: 'The marker tags the change for the lesson.',
    });
    const legacyRow = JSON.stringify({
      quiz_id: 'q1',
      question: 'What changed?',
      choices: ['A', 'B'],
      answer_index: 0,
    });

    expect(parseQuizJsonl(`${legacyRow}\n${realRow}\n`)).toEqual([
      {
        question_id: 'quiz_1',
        review_card_id: 'card_explicit_1',
        question: 'What does the new comment indicate?',
        expected_answer: 'A learn-from-diff marker',
        quiz_kind: 'recall',
        source_claims: ['c1'],
        concepts: ['learn-from-diff'],
        evidence: [{ file: 'demo.py', line: 4 }],
        explanation: 'The marker tags the change for the lesson.',
        answer_mode: 'open',
      },
    ]);
  });

  it('keeps open-answer rows without review_card_id renderable but untracked by SRS', () => {
    const missingReviewCardId = JSON.stringify({
      question_id: 'quiz_1',
      question: 'What does the new comment indicate?',
      expected_answer: 'A learn-from-diff marker',
      source_claims: ['c1'],
      concepts: ['learn-from-diff'],
      evidence: [{ file: 'demo.py', line: 4 }],
    });

    const parsed = parseQuizJsonl(missingReviewCardId);
    expect(parsed).toEqual([
      {
        question_id: 'quiz_1',
        question: 'What does the new comment indicate?',
        expected_answer: 'A learn-from-diff marker',
        quiz_kind: 'recall',
        source_claims: ['c1'],
        concepts: ['learn-from-diff'],
        evidence: [{ file: 'demo.py', line: 4 }],
        answer_mode: 'open',
      },
    ]);
    expect(hasQuizReviewCard(parsed[0]!)).toBe(false);
    expect(hasChoices(parsed[0]!)).toBe(false);
  });

  it('identifies rows with explicit review_card_id as SRS-tracked', () => {
    const row = JSON.stringify({
      question_id: 'quiz_1',
      review_card_id: 'card_explicit_1',
      question: 'What changed?',
      expected_answer: 'The retry path',
      source_claims: ['c1'],
      evidence: [{ file: 'demo.py', line: 4 }],
    });

    const parsed = parseQuizJsonl(row);
    expect(hasQuizReviewCard(parsed[0]!)).toBe(true);
  });

  it('parses transfer quiz kind and defaults invalid kinds to recall', () => {
    const transferRow = JSON.stringify({
      question_id: 'quiz_transfer',
      question: 'How would this retry rule apply to a webhook receiver?',
      expected_answer: 'Use idempotency before retrying side-effectful writes.',
      quiz_kind: 'transfer',
      source_claims: ['c1'],
      evidence: [{ file: 'demo.py', line: 4 }],
    });
    const invalidRow = JSON.stringify({
      question_id: 'quiz_invalid_kind',
      question: 'What changed?',
      expected_answer: 'A learn-from-diff marker',
      quiz_kind: 'memory',
      source_claims: ['c1'],
      evidence: [{ file: 'demo.py', line: 4 }],
    });

    const parsed = parseQuizJsonl(`${transferRow}\n${invalidRow}`);

    expect(parsed[0]!.quiz_kind).toBe('transfer');
    expect(parsed[1]!.quiz_kind).toBe('recall');
  });

  it('matches CLI quiz answer normalization', () => {
    expect(isQuizAnswerCorrect('  A   Learn-From-Diff Marker ', 'a learn-from-diff marker')).toBe(
      true,
    );
  });

  it('parses ABCD multiple_choice rows with valid choices array', () => {
    const row = JSON.stringify({
      question_id: 'quiz_mc_1',
      review_card_id: 'card_mc_1',
      question: 'What does the comment indicate?',
      expected_answer: 'A learn-from-diff marker',
      source_claims: ['c1'],
      concepts: ['learn-from-diff'],
      evidence: [{ file: 'demo.py', line: 4 }],
      explanation: 'The marker tags the change.',
      answer_mode: 'multiple_choice',
      choices: [
        { label: 'A', text: 'A learn-from-diff marker', is_correct: true },
        { label: 'B', text: 'A runtime debug flag', is_correct: false },
        { label: 'C', text: 'A deprecation notice', is_correct: false },
        { label: 'D', text: 'A type annotation', is_correct: false },
      ],
    });

    const parsed = parseQuizJsonl(row);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]!.answer_mode).toBe('multiple_choice');
    expect(hasChoices(parsed[0]!)).toBe(true);
    expect(parsed[0]!.choices).toEqual([
      { label: 'A', text: 'A learn-from-diff marker', is_correct: true },
      { label: 'B', text: 'A runtime debug flag', is_correct: false },
      { label: 'C', text: 'A deprecation notice', is_correct: false },
      { label: 'D', text: 'A type annotation', is_correct: false },
    ]);
  });

  it('infers multiple_choice when choices present but answer_mode missing', () => {
    const row = JSON.stringify({
      question_id: 'quiz_mc_2',
      question: 'Pick one',
      expected_answer: 'first',
      source_claims: ['c1'],
      evidence: [{ file: 'demo.py', line: 4 }],
      choices: [
        { label: 'A', text: 'first', is_correct: true },
        { label: 'B', text: 'second', is_correct: false },
        { label: 'C', text: 'third', is_correct: false },
        { label: 'D', text: 'fourth', is_correct: false },
      ],
    });

    const parsed = parseQuizJsonl(row);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]!.answer_mode).toBe('multiple_choice');
    expect(hasChoices(parsed[0]!)).toBe(true);
  });

  it('falls back to open mode when choices field is null', () => {
    const row = JSON.stringify({
      question_id: 'quiz_3',
      question: 'Open question',
      expected_answer: 'free text',
      source_claims: ['c1'],
      evidence: [{ file: 'demo.py', line: 4 }],
      choices: null,
    });

    const parsed = parseQuizJsonl(row);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]!.answer_mode).toBe('open');
    expect(parsed[0]!.choices).toBeUndefined();
    expect(hasChoices(parsed[0]!)).toBe(false);
  });

  it('does not treat explicit open rows with choices as multiple choice', () => {
    const row = JSON.stringify({
      question_id: 'quiz_open_with_choices',
      question: 'Open question',
      expected_answer: 'free text',
      source_claims: ['c1'],
      evidence: [{ file: 'demo.py', line: 4 }],
      answer_mode: 'open',
      choices: [
        { label: 'A', text: 'free text', is_correct: true },
        { label: 'B', text: 'second', is_correct: false },
        { label: 'C', text: 'third', is_correct: false },
        { label: 'D', text: 'fourth', is_correct: false },
      ],
    });

    const parsed = parseQuizJsonl(row);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]!.answer_mode).toBe('open');
    expect(parsed[0]!.choices).toBeDefined();
    expect(hasChoices(parsed[0]!)).toBe(false);
  });

  it('rejects malformed choices but keeps the row in textarea fallback', () => {
    const wrongLength = JSON.stringify({
      question_id: 'quiz_bad_1',
      question: 'q',
      expected_answer: 'a',
      source_claims: ['c1'],
      evidence: [{ file: 'demo.py', line: 4 }],
      choices: [
        { label: 'A', text: 'one', is_correct: true },
        { label: 'B', text: 'two', is_correct: false },
      ],
    });
    const wrongLabel = JSON.stringify({
      question_id: 'quiz_bad_2',
      question: 'q',
      expected_answer: 'a',
      source_claims: ['c1'],
      evidence: [{ file: 'demo.py', line: 4 }],
      choices: [
        { label: 'A', text: 'one', is_correct: true },
        { label: 'X', text: 'two', is_correct: false },
        { label: 'C', text: 'three', is_correct: false },
        { label: 'D', text: 'four', is_correct: false },
      ],
    });
    const noCorrect = JSON.stringify({
      question_id: 'quiz_bad_3',
      question: 'q',
      expected_answer: 'a',
      source_claims: ['c1'],
      evidence: [{ file: 'demo.py', line: 4 }],
      choices: [
        { label: 'A', text: 'one', is_correct: false },
        { label: 'B', text: 'two', is_correct: false },
        { label: 'C', text: 'three', is_correct: false },
        { label: 'D', text: 'four', is_correct: false },
      ],
    });
    const duplicateText = JSON.stringify({
      question_id: 'quiz_bad_4',
      question: 'q',
      expected_answer: 'one',
      source_claims: ['c1'],
      evidence: [{ file: 'demo.py', line: 4 }],
      choices: [
        { label: 'A', text: 'one', is_correct: true },
        { label: 'B', text: 'ONE', is_correct: false },
        { label: 'C', text: 'three', is_correct: false },
        { label: 'D', text: 'four', is_correct: false },
      ],
    });
    const answerMismatch = JSON.stringify({
      question_id: 'quiz_bad_5',
      question: 'q',
      expected_answer: 'expected',
      source_claims: ['c1'],
      evidence: [{ file: 'demo.py', line: 4 }],
      choices: [
        { label: 'A', text: 'not expected', is_correct: true },
        { label: 'B', text: 'two', is_correct: false },
        { label: 'C', text: 'three', is_correct: false },
        { label: 'D', text: 'four', is_correct: false },
      ],
    });

    const parsed = parseQuizJsonl(
      `${wrongLength}\n${wrongLabel}\n${noCorrect}\n${duplicateText}\n${answerMismatch}`,
    );
    expect(parsed).toHaveLength(5);
    for (const item of parsed) {
      expect(item.answer_mode).toBe('open');
      expect(hasChoices(item)).toBe(false);
    }
  });
});
