import { describe, expect, it } from 'vitest';
import {
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
      },
    ]);
    expect(hasQuizReviewCard(parsed[0]!)).toBe(false);
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
});
