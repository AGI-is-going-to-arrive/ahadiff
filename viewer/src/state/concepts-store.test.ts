import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getConceptLedger } from '../api/concepts';
import { useConceptsStore } from './concepts-store';
import type { ConceptLedgerEntry, ConceptLedgerResponse } from '../api/types';

vi.mock('../api/concepts', () => ({
  getConceptLedger: vi.fn(),
}));

const mockedFetch = vi.mocked(getConceptLedger);

function makeEntry(overrides: Partial<ConceptLedgerEntry> = {}): ConceptLedgerEntry {
  return {
    term_key: 'term-1',
    concept: 'Concept 1',
    display_name: 'Concept 1',
    related_claims: [],
    file_refs: [],
    source_refs: [],
    updated_by_runs: [],
    ...overrides,
  };
}

function makeResponse(overrides: Partial<ConceptLedgerResponse> = {}): ConceptLedgerResponse {
  return {
    entries: [makeEntry()],
    next_cursor: null,
    total_count: 1,
    ...overrides,
  };
}

function resetStore() {
  useConceptsStore.setState({
    entries: [],
    nextCursor: undefined,
    hasMore: false,
    totalCount: 0,
    loading: false,
    loadingMore: false,
    error: false,
    runFilter: undefined,
    lastFetchedAt: 0,
  });
}

describe('concepts store', () => {
  beforeEach(() => {
    vi.useRealTimers();
    mockedFetch.mockReset();
    resetStore();
  });

  afterEach(() => {
    vi.useRealTimers();
    mockedFetch.mockReset();
  });

  it('initial state is empty and idle', () => {
    const state = useConceptsStore.getState();
    expect(state.entries).toEqual([]);
    expect(state.nextCursor).toBeUndefined();
    expect(state.hasMore).toBe(false);
    expect(state.totalCount).toBe(0);
    expect(state.loading).toBe(false);
    expect(state.loadingMore).toBe(false);
    expect(state.error).toBe(false);
    expect(state.runFilter).toBeUndefined();
    expect(state.lastFetchedAt).toBe(0);
  });

  it('loadLedger fetches entries and populates the store', async () => {
    const response = makeResponse({
      entries: [makeEntry({ term_key: 'a' }), makeEntry({ term_key: 'b' })],
      next_cursor: 'cursor-1',
      total_count: 12,
    });
    mockedFetch.mockResolvedValue(response);

    await useConceptsStore.getState().loadLedger();

    const state = useConceptsStore.getState();
    expect(state.entries.map((e) => e.term_key)).toEqual(['a', 'b']);
    expect(state.nextCursor).toBe('cursor-1');
    expect(state.hasMore).toBe(true);
    expect(state.totalCount).toBe(12);
    expect(state.loading).toBe(false);
    expect(state.error).toBe(false);
    expect(state.lastFetchedAt).toBeGreaterThan(0);
    expect(mockedFetch).toHaveBeenCalledWith({ limit: 50, run: undefined });
  });

  it('loadLedger marks hasMore=false when next_cursor is null', async () => {
    mockedFetch.mockResolvedValue(makeResponse({ next_cursor: null, total_count: 1 }));

    await useConceptsStore.getState().loadLedger();

    const state = useConceptsStore.getState();
    expect(state.nextCursor).toBeUndefined();
    expect(state.hasMore).toBe(false);
  });

  it('loadLedger sets error=true on API failure', async () => {
    mockedFetch.mockRejectedValue(new Error('boom'));

    await useConceptsStore.getState().loadLedger();

    const state = useConceptsStore.getState();
    expect(state.error).toBe(true);
    expect(state.loading).toBe(false);
    expect(state.entries).toEqual([]);
  });

  it('loadLedger uses cache within TTL for the same runFilter', async () => {
    mockedFetch.mockResolvedValue(makeResponse());
    await useConceptsStore.getState().loadLedger();

    await useConceptsStore.getState().loadLedger();

    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });

  it('loadLedger refetches when runFilter differs even within TTL', async () => {
    mockedFetch
      .mockResolvedValueOnce(makeResponse({ entries: [makeEntry({ term_key: 'a' })] }))
      .mockResolvedValueOnce(makeResponse({ entries: [makeEntry({ term_key: 'b' })] }));

    await useConceptsStore.getState().loadLedger();
    await useConceptsStore.getState().loadLedger('run-1');

    expect(mockedFetch).toHaveBeenCalledTimes(2);
    expect(mockedFetch).toHaveBeenLastCalledWith({ limit: 50, run: 'run-1' });
    expect(useConceptsStore.getState().runFilter).toBe('run-1');
    expect(useConceptsStore.getState().entries.map((e) => e.term_key)).toEqual(['b']);
  });

  it('loadLedger refetches after TTL expires', async () => {
    mockedFetch
      .mockResolvedValueOnce(makeResponse({ total_count: 5 }))
      .mockResolvedValueOnce(makeResponse({ total_count: 50 }));

    await useConceptsStore.getState().loadLedger();
    expect(useConceptsStore.getState().totalCount).toBe(5);

    useConceptsStore.setState({ lastFetchedAt: Date.now() - 30_001 });
    await useConceptsStore.getState().loadLedger();

    expect(mockedFetch).toHaveBeenCalledTimes(2);
    expect(useConceptsStore.getState().totalCount).toBe(50);
  });

  it('loadLedger deduplicates while a fetch is in-flight for the same runFilter', async () => {
    let resolve: ((value: ConceptLedgerResponse) => void) | undefined;
    mockedFetch.mockImplementation(
      () =>
        new Promise<ConceptLedgerResponse>((r) => {
          resolve = r;
        }),
    );

    const p1 = useConceptsStore.getState().loadLedger();
    const p2 = useConceptsStore.getState().loadLedger();
    expect(useConceptsStore.getState().loading).toBe(true);

    resolve?.(makeResponse());
    await Promise.all([p1, p2]);

    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });

  it('loadMoreLedger appends entries and updates cursor', async () => {
    mockedFetch.mockResolvedValueOnce(
      makeResponse({
        entries: [makeEntry({ term_key: 'a' })],
        next_cursor: 'cursor-1',
        total_count: 3,
      }),
    );
    await useConceptsStore.getState().loadLedger();

    mockedFetch.mockResolvedValueOnce(
      makeResponse({
        entries: [makeEntry({ term_key: 'b' }), makeEntry({ term_key: 'c' })],
        next_cursor: null,
        total_count: 3,
      }),
    );
    await useConceptsStore.getState().loadMoreLedger();

    const state = useConceptsStore.getState();
    expect(state.entries.map((e) => e.term_key)).toEqual(['a', 'b', 'c']);
    expect(state.nextCursor).toBeUndefined();
    expect(state.hasMore).toBe(false);
    expect(state.loadingMore).toBe(false);
    expect(mockedFetch).toHaveBeenNthCalledWith(2, {
      cursor: 'cursor-1',
      limit: 50,
      run: undefined,
    });
  });

  it('loadMoreLedger forwards the active runFilter', async () => {
    mockedFetch.mockResolvedValueOnce(
      makeResponse({
        entries: [makeEntry({ term_key: 'a' })],
        next_cursor: 'cursor-1',
        total_count: 2,
      }),
    );
    await useConceptsStore.getState().loadLedger('run-x');

    mockedFetch.mockResolvedValueOnce(
      makeResponse({
        entries: [makeEntry({ term_key: 'b' })],
        next_cursor: null,
        total_count: 2,
      }),
    );
    await useConceptsStore.getState().loadMoreLedger();

    expect(mockedFetch).toHaveBeenNthCalledWith(2, {
      cursor: 'cursor-1',
      limit: 50,
      run: 'run-x',
    });
  });

  it('loadMoreLedger is a no-op when hasMore is false', async () => {
    mockedFetch.mockResolvedValue(makeResponse({ next_cursor: null }));
    await useConceptsStore.getState().loadLedger();
    mockedFetch.mockClear();

    await useConceptsStore.getState().loadMoreLedger();

    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it('loadMoreLedger clears loadingMore on failure but keeps existing entries', async () => {
    mockedFetch.mockResolvedValueOnce(
      makeResponse({
        entries: [makeEntry({ term_key: 'a' })],
        next_cursor: 'cursor-1',
        total_count: 5,
      }),
    );
    await useConceptsStore.getState().loadLedger();

    mockedFetch.mockRejectedValueOnce(new Error('boom'));
    await useConceptsStore.getState().loadMoreLedger();

    const state = useConceptsStore.getState();
    expect(state.entries.map((e) => e.term_key)).toEqual(['a']);
    expect(state.loadingMore).toBe(false);
    expect(state.hasMore).toBe(true);
    expect(state.nextCursor).toBe('cursor-1');
  });

  it('setRunFilter resets data and triggers a reload with the new filter', async () => {
    mockedFetch.mockResolvedValueOnce(
      makeResponse({ entries: [makeEntry({ term_key: 'old' })], total_count: 1 }),
    );
    await useConceptsStore.getState().loadLedger();
    expect(useConceptsStore.getState().entries.map((e) => e.term_key)).toEqual(['old']);

    mockedFetch.mockResolvedValueOnce(
      makeResponse({ entries: [makeEntry({ term_key: 'new' })], total_count: 1 }),
    );
    useConceptsStore.getState().setRunFilter('run-2');

    expect(useConceptsStore.getState().runFilter).toBe('run-2');
    await vi.waitFor(() => {
      expect(useConceptsStore.getState().entries.map((e) => e.term_key)).toEqual(['new']);
    });
    expect(mockedFetch).toHaveBeenLastCalledWith({ limit: 50, run: 'run-2' });
  });

  it('invalidate clears entries and counters without triggering a fetch', async () => {
    mockedFetch.mockResolvedValueOnce(
      makeResponse({
        entries: [makeEntry({ term_key: 'a' })],
        next_cursor: 'cursor-1',
        total_count: 7,
      }),
    );
    await useConceptsStore.getState().loadLedger();
    mockedFetch.mockClear();

    useConceptsStore.getState().invalidate();

    const state = useConceptsStore.getState();
    expect(state.entries).toEqual([]);
    expect(state.nextCursor).toBeUndefined();
    expect(state.hasMore).toBe(false);
    expect(state.totalCount).toBe(0);
    expect(state.loading).toBe(false);
    expect(state.loadingMore).toBe(false);
    expect(state.error).toBe(false);
    expect(state.lastFetchedAt).toBe(0);
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it('invalidate cancels an in-flight loadLedger result via fetchGeneration', async () => {
    let resolve: ((value: ConceptLedgerResponse) => void) | undefined;
    mockedFetch.mockImplementationOnce(
      () =>
        new Promise<ConceptLedgerResponse>((r) => {
          resolve = r;
        }),
    );

    const pending = useConceptsStore.getState().loadLedger();
    expect(useConceptsStore.getState().loading).toBe(true);

    useConceptsStore.getState().invalidate();
    resolve?.(makeResponse({ entries: [makeEntry({ term_key: 'late' })], total_count: 1 }));
    await pending;

    const state = useConceptsStore.getState();
    expect(state.entries).toEqual([]);
    expect(state.totalCount).toBe(0);
    expect(state.lastFetchedAt).toBe(0);
  });
});
