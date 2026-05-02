import { create } from 'zustand';
import { fetchGraphStatus } from '../api/graph';
import type { GraphStatusResponse } from '../api/types';

const CACHE_TTL_MS = 30_000;
const FETCH_TIMEOUT_MS = 15_000;

let inflight: Promise<GraphStatusResponse | null> | null = null;
let fetchGeneration = 0;
let activeController: AbortController | null = null;

interface GraphState {
  status: GraphStatusResponse | null;
  loading: boolean;
  error: boolean;
  lastFetchedAt: number;

  fetch: () => Promise<void>;
  invalidate: () => void;
}

export const useGraphStore = create<GraphState>(() => ({
  status: null,
  loading: false,
  error: false,
  lastFetchedAt: 0,

  fetch: async () => {
    const state = useGraphStore.getState();
    if (state.loading) {
      if (inflight) {
        try { await inflight; } catch { /* handled by original caller */ }
      }
      return;
    }
    if (state.status && Date.now() - state.lastFetchedAt < CACHE_TTL_MS) return;

    const gen = ++fetchGeneration;
    useGraphStore.setState({ loading: true, error: false });
    const controller = new AbortController();
    activeController = controller;
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    const promise = fetchGraphStatus({ signal: controller.signal })
      .then((r) => r as GraphStatusResponse | null)
      .catch(() => null);
    inflight = promise;
    try {
      const result = await promise;
      if (fetchGeneration !== gen) return;
      if (result) {
        useGraphStore.setState({
          status: result,
          loading: false,
          error: false,
          lastFetchedAt: Date.now(),
        });
      } else {
        useGraphStore.setState({ status: null, loading: false, error: true });
      }
    } finally {
      clearTimeout(timer);
      if (fetchGeneration === gen) {
        inflight = null;
        activeController = null;
      }
    }
  },

  invalidate: () => {
    fetchGeneration += 1;
    activeController?.abort();
    activeController = null;
    inflight = null;
    useGraphStore.setState({ status: null, lastFetchedAt: 0, loading: false });
    void useGraphStore.getState().fetch();
  },
}));
