import { create } from 'zustand';
import { getReviewQueue, submitReviewRate } from '../api/review';
import type { DueReviewCard, ReviewAnswer, ReviewRateResponse } from '../api/types';

interface ReviewState {
  cards: DueReviewCard[];
  currentIndex: number;
  loading: boolean;
  rating: boolean;
  /** Raw error object preserved for classification (status code, type, etc.). */
  error: unknown;

  loadQueue: (opts?: { signal?: AbortSignal }) => Promise<void>;
  rate: (answer: ReviewAnswer, opts?: { signal?: AbortSignal }) => Promise<ReviewRateResponse | null>;
  currentCard: () => DueReviewCard | null;
  remaining: () => number;
  reset: () => void;
}

export const useReviewStore = create<ReviewState>((set, get) => ({
  cards: [],
  currentIndex: 0,
  loading: false,
  rating: false,
  error: null,

  loadQueue: async (opts) => {
    set({ loading: true, error: null });
    try {
      const res = await getReviewQueue(opts ? { signal: opts.signal } : undefined);
      set({ cards: res.cards, currentIndex: 0, loading: false });
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        set({ loading: false });
        return;
      }
      set({ error: e, loading: false });
    }
  },

  rate: async (answer, opts) => {
    const { cards, currentIndex, rating } = get();
    if (rating) return null;
    const card = cards[currentIndex];
    if (!card) return null;
    set({ rating: true, error: null });
    try {
      const res = await submitReviewRate(
        {
          card_id: card.card_id,
          answer,
          idempotency_key: crypto.randomUUID(),
        },
        opts ? { signal: opts.signal } : undefined,
      );
      set({ currentIndex: currentIndex + 1, rating: false });
      return res;
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        set({ rating: false });
        return null;
      }
      set({ error: e, rating: false });
      return null;
    }
  },

  currentCard: () => {
    const { cards, currentIndex } = get();
    return cards[currentIndex] ?? null;
  },

  remaining: () => {
    const { cards, currentIndex } = get();
    return Math.max(0, cards.length - currentIndex);
  },

  reset: () => set({ cards: [], currentIndex: 0, loading: false, rating: false, error: null }),
}));
