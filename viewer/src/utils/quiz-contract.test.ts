import { describe, expect, it } from 'vitest';
import {
  hasChoices,
  hasQuizReviewCard,
  isQuizAnswerCorrect,
  parseQuizJsonl,
} from './quiz-contract';

describe('quiz contract helpers', () => {
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
