import { describe, expect, it } from 'vitest';

import { dueReviewCardSchema, reviewQueueResponseSchema } from '../schemas';
import type { DueReviewCard } from '../types';

const dueCard = {
  card_id: 'card-1',
  concept: 'retry loop',
  run_id: 'run-1',
  due_date: '2026-05-19T00:00:00Z',
  scaffolding_level: '3',
  display_path: 'src/app.py',
  stability: 4.5,
  difficulty: 6.25,
  reps: 2,
  lapses: 1,
  last_rating: 3,
} satisfies DueReviewCard;

describe('review queue API schemas', () => {
  it('accepts current due review card stats and defaults legacy stat fields', () => {
    expect(dueReviewCardSchema.parse(dueCard)).toEqual(dueCard);

    const {
      stability: _stability,
      difficulty: _difficulty,
      reps: _reps,
      lapses: _lapses,
      last_rating: _lastRating,
      ...legacyCard
    } = dueCard;

    expect(dueReviewCardSchema.parse(legacyCard)).toMatchObject({
      stability: null,
      difficulty: null,
      reps: 0,
      lapses: 0,
      last_rating: null,
    });
  });

  it('rejects unknown fields and non-finite stat payloads', () => {
    expect(
      dueReviewCardSchema.safeParse({
        ...dueCard,
        leaked_secret: 'sk-test',
      }).success,
    ).toBe(false);
    expect(
      reviewQueueResponseSchema.safeParse({
        cards: [dueCard],
        extra: true,
      }).success,
    ).toBe(false);
    expect(
      reviewQueueResponseSchema.safeParse({
        cards: [{ ...dueCard, stability: Number.POSITIVE_INFINITY }],
      }).success,
    ).toBe(false);
  });
});
