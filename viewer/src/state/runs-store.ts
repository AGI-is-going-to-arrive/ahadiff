import { create } from 'zustand';
import { getRun, listRuns } from '../api/runs';
import type { RunDetail, RunSummary } from '../api/types';

const TTL_MS = 30_000;
const DETAIL_TTL_MS = 60_000;

interface RunsState {
  runs: RunSummary[];
  nextCursor: string | null;
  hasMore: boolean;
  details: Record<string, RunDetail>;
  detailLoadedAt: Record<string, number>;
  lastLoadedAt: number | null;
  lastSourceKind: string | undefined;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  _generation: number;
  loadRuns: (sourceKind?: string, opts?: { signal?: AbortSignal }) => Promise<void>;
  loadMoreRuns: (opts?: { signal?: AbortSignal }) => Promise<void>;
  loadDetail: (runId: string, opts?: { signal?: AbortSignal }) => Promise<RunDetail>;
  getCachedRun: (runId: string) => RunSummary | undefined;
}

export const useRunsStore = create<RunsState>((set, get) => ({
  runs: [],
  nextCursor: null,
  hasMore: false,
  details: {},
  detailLoadedAt: {},
  lastLoadedAt: null,
  lastSourceKind: undefined,
  loading: false,
  loadingMore: false,
  error: null,
  _generation: 0,

  loadRuns: async (sourceKind, opts) => {
    const now = Date.now();
    const { lastLoadedAt, lastSourceKind } = get();
    if (lastLoadedAt && now - lastLoadedAt < TTL_MS && lastSourceKind === sourceKind) return;
    const gen = get()._generation + 1;
    set({ _generation: gen, lastSourceKind: sourceKind, loading: true, error: null });
    try {
      const res = await listRuns(
        sourceKind ? { source_kind: sourceKind } : {},
        opts ? { signal: opts.signal } : undefined,
      );
      if (get()._generation !== gen) return;
      set({
        runs: res.runs,
        nextCursor: res.next_cursor ?? null,
        hasMore: !!res.next_cursor,
        lastLoadedAt: Date.now(),
        loading: false,
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        set({ loading: false });
        return;
      }
      if (get()._generation !== gen) return;
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
      throw e;
    }
  },

  loadMoreRuns: async (opts) => {
    const { nextCursor, hasMore, loadingMore } = get();
    if (!hasMore || !nextCursor || loadingMore) return;
    const gen = get()._generation;
    const cursorAtCall = nextCursor;
    set({ loadingMore: true });
    try {
      const res = await listRuns(
        { source_kind: get().lastSourceKind, cursor: cursorAtCall },
        opts ? { signal: opts.signal } : undefined,
      );
      if (get()._generation !== gen || get().nextCursor !== cursorAtCall) {
        set({ loadingMore: false });
        return;
      }
      set((state) => ({
        runs: [...state.runs, ...res.runs],
        nextCursor: res.next_cursor ?? null,
        hasMore: !!res.next_cursor,
        loadingMore: false,
      }));
    } catch (e) {
      set({ loadingMore: false });
      throw e;
    }
  },

  loadDetail: async (runId, opts) => {
    const now = Date.now();
    const cached = get().details[runId];
    const loadedAt = get().detailLoadedAt[runId];
    if (cached && loadedAt && now - loadedAt < DETAIL_TTL_MS) return cached;
    const detail = await getRun(runId, opts ? { signal: opts.signal } : undefined);
    set((state) => ({
      details: { ...state.details, [runId]: detail },
      detailLoadedAt: { ...state.detailLoadedAt, [runId]: Date.now() },
    }));
    return detail;
  },

  getCachedRun: (runId) => get().runs.find((r) => r.run_id === runId),
}));
