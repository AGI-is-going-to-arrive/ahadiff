import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getReviewQueue, submitReviewRate } from '../api/review';
import { useReviewStore } from './review-store';

vi.mock('../api/review', () => ({
  getReviewQueue: vi.fn(),
  submitReviewRate: vi.fn(),
}));

const mockedGetReviewQueue = vi.mocked(getReviewQueue);
const mockedSubmitReviewRate = vi.mocked(submitReviewRate);

describe('review store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useReviewStore.getState().reset();
    useReviewStore.setState({
      cards: [
        {
          card_id: 'card-1',
          concept: 'learn-from-diff',
          run_id: 'test-run',
          due_date: '2026-04-27T00:00:00Z',
          scaffolding_level: '3',
          display_path: 'demo.py',
          source_ref: 'HEAD',
          symbol: null,
        },
      ],
      currentIndex: 0,
      loading: false,
      rating: false,
      error: null,
    });
  });

  it('submits easy as a first-class ReviewAnswer', async () => {
    mockedSubmitReviewRate.mockResolvedValue({ inserted: true });

    await useReviewStore.getState().rate('easy');

    expect(mockedSubmitReviewRate).toHaveBeenCalledWith(
      expect.objectContaining({
        card_id: 'card-1',
        answer: 'easy',
        idempotency_key: expect.any(String),
      }),
      undefined,
    );
    expect(useReviewStore.getState().currentIndex).toBe(1);
    expect(useReviewStore.getState().error).toBeNull();
  });

  it('does not advance when the backend rejects a rating', async () => {
    mockedSubmitReviewRate.mockRejectedValue(new Error('backend rejected card'));

    await useReviewStore.getState().rate('good');

    expect(useReviewStore.getState().currentIndex).toBe(0);
    expect(useReviewStore.getState().rating).toBe(false);
    const storeError = useReviewStore.getState().error;
    expect(storeError).toBeInstanceOf(Error);
    expect((storeError as Error).message).toBe('backend rejected card');
  });

  it('loads the review queue through the API contract', async () => {
    mockedGetReviewQueue.mockResolvedValue({
      cards: [
        {
          card_id: 'card-2',
          concept: 'evidence',
          run_id: 'test-run',
          due_date: '2026-04-28T00:00:00Z',
          scaffolding_level: '2',
          display_path: 'demo.py',
          source_ref: null,
          symbol: 'demo.hello',
        },
      ],
    });

    await useReviewStore.getState().loadQueue();

    expect(useReviewStore.getState().cards.map((card) => card.card_id)).toEqual(['card-2']);
    expect(useReviewStore.getState().loading).toBe(false);
    expect(useReviewStore.getState().error).toBeNull();
  });
});
