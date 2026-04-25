import { create } from 'zustand';
import { getRun, listRuns } from '../api/runs';
import type { RunDetail, RunSummary } from '../api/types';

const TTL_MS = 30_000;
const DETAIL_TTL_MS = 60_000;

interface RunsState {
  runs: RunSummary[];
  details: Record<string, RunDetail>;
  detailLoadedAt: Record<string, number>;
  lastLoadedAt: number | null;
  lastSourceKind: string | undefined;
  loadRuns: (sourceKind?: string, opts?: { signal?: AbortSignal }) => Promise<void>;
  loadDetail: (runId: string, opts?: { signal?: AbortSignal }) => Promise<RunDetail>;
  getCachedRun: (runId: string) => RunSummary | undefined;
}

export const useRunsStore = create<RunsState>((set, get) => ({
  runs: [],
  details: {},
  detailLoadedAt: {},
  lastLoadedAt: null,
  lastSourceKind: undefined,

  loadRuns: async (sourceKind, opts) => {
    const now = Date.now();
    const { lastLoadedAt, lastSourceKind } = get();
    if (lastLoadedAt && now - lastLoadedAt < TTL_MS && lastSourceKind === sourceKind) return;
    const data = await listRuns(
      sourceKind ? { source_kind: sourceKind } : {},
      opts ? { signal: opts.signal } : undefined,
    );
    set({ runs: data, lastLoadedAt: now, lastSourceKind: sourceKind });
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
