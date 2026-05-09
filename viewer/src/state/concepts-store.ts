import { create } from 'zustand';
import { getConceptLedger } from '../api/concepts';
import type { ConceptLedgerEntry } from '../api/types';

const CACHE_TTL_MS = 30_000;
const PAGE_SIZE = 50;

let fetchGeneration = 0;

interface ConceptsState {
  entries: ConceptLedgerEntry[];
  nextCursor: string | undefined;
  hasMore: boolean;
  totalCount: number;
  loading: boolean;
  loadingMore: boolean;
  error: boolean;
  runFilter: string | undefined;
  lastFetchedAt: number;

  loadLedger: (runFilter?: string) => Promise<void>;
  loadMoreLedger: () => Promise<void>;
  setRunFilter: (run: string | undefined) => void;
  invalidate: () => void;
}

export const useConceptsStore = create<ConceptsState>(() => ({
  entries: [],
  nextCursor: undefined,
  hasMore: false,
  totalCount: 0,
  loading: false,
  loadingMore: false,
  error: false,
  runFilter: undefined,
  lastFetchedAt: 0,

  loadLedger: async (runFilter?: string) => {
    const state = useConceptsStore.getState();
    if (state.loading) return;
    if (
      state.entries.length > 0 &&
      Date.now() - state.lastFetchedAt < CACHE_TTL_MS &&
      state.runFilter === runFilter
    ) return;

    const gen = ++fetchGeneration;
    useConceptsStore.setState({ loading: true, error: false, runFilter });
    try {
      const data = await getConceptLedger({ limit: PAGE_SIZE, run: runFilter });
      if (fetchGeneration !== gen) return;
      useConceptsStore.setState({
        entries: data.entries,
        nextCursor: data.next_cursor ?? undefined,
        hasMore: data.next_cursor != null,
        totalCount: data.total_count,
        loading: false,
        lastFetchedAt: Date.now(),
      });
    } catch {
      if (fetchGeneration !== gen) return;
      useConceptsStore.setState({ loading: false, error: true });
    }
  },

  loadMoreLedger: async () => {
    const state = useConceptsStore.getState();
    if (state.loadingMore || !state.hasMore || !state.nextCursor) return;

    const gen = fetchGeneration;
    useConceptsStore.setState({ loadingMore: true });
    try {
      const data = await getConceptLedger({
        cursor: state.nextCursor,
        limit: PAGE_SIZE,
        run: state.runFilter,
      });
      if (fetchGeneration !== gen) return;
      useConceptsStore.setState((prev) => ({
        entries: [...prev.entries, ...data.entries],
        nextCursor: data.next_cursor ?? undefined,
        hasMore: data.next_cursor != null,
        totalCount: data.total_count,
        loadingMore: false,
      }));
    } catch {
      if (fetchGeneration !== gen) return;
      useConceptsStore.setState({ loadingMore: false });
    }
  },

  setRunFilter: (run: string | undefined) => {
    fetchGeneration += 1;
    useConceptsStore.setState({
      entries: [],
      nextCursor: undefined,
      hasMore: false,
      totalCount: 0,
      lastFetchedAt: 0,
      runFilter: run,
    });
    void useConceptsStore.getState().loadLedger(run);
  },

  invalidate: () => {
    fetchGeneration += 1;
    useConceptsStore.setState({
      entries: [],
      nextCursor: undefined,
      hasMore: false,
      totalCount: 0,
      lastFetchedAt: 0,
    });
  },
}));
