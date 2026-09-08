import { create } from 'zustand';
import { getReviewQueue, submitReviewRate } from '../api/review';
import type { DueReviewCard, ReviewAnswer, ReviewRateResponse } from '../api/types';
import { createIdempotencyKey } from '../utils/idempotency';

interface RateOptions {
  signal?: AbortSignal;
  /** Bind deferred assessment work to the card on which it began. */
  cardId?: string;
  idempotencyKey?: string;
  selectedChoiceLabel?: string | null;
  peekedThisSession?: boolean;
}

interface ReviewState {
  cards: DueReviewCard[];
  currentIndex: number;
  loading: boolean;
  rating: boolean;
  error: unknown;
  loadQueue: (opts?: { signal?: AbortSignal }) => Promise<void>;
  rate: (answer: ReviewAnswer, opts?: RateOptions) => Promise<ReviewRateResponse | null>;
  currentCard: () => DueReviewCard | null;
  remaining: () => number;
  selectCard: (cardId: string) => boolean;
  reset: () => void;
}

interface RatingAttempt {
  key: string;
  answer: ReviewAnswer;
  selectedChoiceLabel: string | null;
  peeked: boolean;
  confirmed: boolean;
}

export const useReviewStore = create<ReviewState>((set, get) => {
  const attempts = new Map<string, RatingAttempt>();
  let selectionGeneration = 0;
  let loadGeneration = 0;
  let activeRequest = 0;
  return {
    cards: [], currentIndex: 0, loading: false, rating: false, error: null,

    loadQueue: async (opts) => {
      const generation = ++loadGeneration;
      set({ loading: true, error: null });
      try {
        const res = await getReviewQueue(opts ? { signal: opts.signal } : undefined);
        if (generation !== loadGeneration || opts?.signal?.aborted) return;
        selectionGeneration += 1;
        for (const [id, attempt] of attempts) {
          if (attempt.confirmed) attempts.delete(id);
        }
        set({ cards: res.cards, currentIndex: 0, loading: false });
      } catch (error) {
        if (generation !== loadGeneration) return;
        if (error instanceof DOMException && error.name === 'AbortError') {
          set({ loading: false });
          return;
        }
        set({ error, loading: false });
      }
    },

    rate: async (answer, opts) => {
      const { cards, currentIndex, rating } = get();
      if (rating) return null;
      const card = cards[currentIndex];
      if (!card || (opts?.cardId !== undefined && opts.cardId !== card.card_id)) return null;
      const generation = selectionGeneration;
      const requestId = ++activeRequest;
      const selectedChoiceLabel = opts?.selectedChoiceLabel ?? null;
      const peeked = opts?.peekedThisSession ?? false;
      const existing = attempts.get(card.card_id);
      if (existing && (existing.answer !== answer || existing.selectedChoiceLabel !== selectedChoiceLabel || existing.peeked !== peeked)) {
        set({ error: new Error('Retry the same rating to confirm the previous request.') });
        return null;
      }
      const attempt = existing ?? {
        key: opts?.idempotencyKey ?? createIdempotencyKey(), answer, selectedChoiceLabel, peeked, confirmed: false,
      };
      attempts.set(card.card_id, attempt);
      set({ rating: true, error: null });
      try {
        const res = await submitReviewRate({
          card_id: card.card_id, answer, idempotency_key: attempt.key,
          ...(opts?.peekedThisSession !== undefined ? { peeked_this_session: opts.peekedThisSession } : {}),
          ...(opts?.selectedChoiceLabel !== undefined ? { selected_choice_label: opts.selectedChoiceLabel } : {}),
        }, opts?.signal ? { signal: opts.signal } : undefined);
        attempt.confirmed = true;
        if (requestId !== activeRequest) return null;
        const current = get().currentCard();
        if (generation !== selectionGeneration || current?.card_id !== card.card_id) {
          set({ rating: false });
          return null;
        }
        selectionGeneration += 1;
        set({ currentIndex: currentIndex + 1, rating: false });
        return res;
      } catch (error) {
        if (requestId !== activeRequest) return null;
        if (generation !== selectionGeneration || (error instanceof DOMException && error.name === 'AbortError')) {
          set({ rating: false });
          return null;
        }
        // Keep the key: the server may have committed before the response was lost.
        set({ error, rating: false });
        return null;
      }
    },

    currentCard: () => get().cards[get().currentIndex] ?? null,
    remaining: () => Math.max(0, get().cards.length - get().currentIndex),
    selectCard: (cardId) => {
      const index = get().cards.findIndex((card) => card.card_id === cardId);
      if (index < 0) return false;
      if (index !== get().currentIndex) selectionGeneration += 1;
      set({ currentIndex: index });
      return true;
    },
    reset: () => {
      attempts.clear();
      selectionGeneration += 1;
      loadGeneration += 1;
      activeRequest += 1;
      set({ cards: [], currentIndex: 0, loading: false, rating: false, error: null });
    },
  };
});
