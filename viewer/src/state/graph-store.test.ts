import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchGraphStatus } from '../api/graph';
import { useGraphStore } from './graph-store';
import type { GraphStatusResponse } from '../api/types';

vi.mock('../api/graph', () => ({
  fetchGraphStatus: vi.fn(),
}));

const mockedFetch = vi.mocked(fetchGraphStatus);

function makeStatus(overrides: Partial<GraphStatusResponse> = {}): GraphStatusResponse {
  return {
    enabled: true,
    source_exists: true,
    has_graph: true,
    freshness: 'fresh',
    node_count: 10,
    edge_count: 20,
    source_path: '.ahadiff/graphify/graph.json',
    provenance: null,
    ...overrides,
  };
}

describe('graph store', () => {
  beforeEach(() => {
    vi.useRealTimers();
    mockedFetch.mockReset();
    useGraphStore.setState({
      status: null,
      loading: false,
      error: false,
      lastFetchedAt: 0,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    mockedFetch.mockReset();
  });

  it('fetch loads status and caches it', async () => {
    const status = makeStatus();
    mockedFetch.mockResolvedValue(status);

    await useGraphStore.getState().fetch();

    expect(useGraphStore.getState().status).toEqual(status);
    expect(useGraphStore.getState().loading).toBe(false);
    expect(useGraphStore.getState().error).toBe(false);
    expect(useGraphStore.getState().lastFetchedAt).toBeGreaterThan(0);
    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });

  it('fetch uses cache within TTL', async () => {
    mockedFetch.mockResolvedValue(makeStatus());
    await useGraphStore.getState().fetch();

    await useGraphStore.getState().fetch();

    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });

  it('fetch refetches after TTL expires', async () => {
    mockedFetch
      .mockResolvedValueOnce(makeStatus({ node_count: 10 }))
      .mockResolvedValueOnce(makeStatus({ node_count: 50 }));

    await useGraphStore.getState().fetch();
    expect(useGraphStore.getState().status?.node_count).toBe(10);

    useGraphStore.setState({ lastFetchedAt: Date.now() - 30_001 });
    await useGraphStore.getState().fetch();

    expect(mockedFetch).toHaveBeenCalledTimes(2);
    expect(useGraphStore.getState().status?.node_count).toBe(50);
  });

  it('fetch sets error on rejection', async () => {
    mockedFetch.mockRejectedValue(new Error('network'));

    await useGraphStore.getState().fetch();

    expect(useGraphStore.getState().status).toBeNull();
    expect(useGraphStore.getState().error).toBe(true);
    expect(useGraphStore.getState().loading).toBe(false);
  });

  it('fetch clears stale status on rejection after TTL expiry', async () => {
    mockedFetch
      .mockResolvedValueOnce(makeStatus({ node_count: 10 }))
      .mockRejectedValueOnce(new Error('network'));

    await useGraphStore.getState().fetch();
    expect(useGraphStore.getState().status?.node_count).toBe(10);

    useGraphStore.setState({ lastFetchedAt: Date.now() - 30_001 });
    await useGraphStore.getState().fetch();

    expect(useGraphStore.getState().status).toBeNull();
    expect(useGraphStore.getState().error).toBe(true);
    expect(useGraphStore.getState().loading).toBe(false);
  });

  it('fetch aborts on timeout and leaves no stale status', async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    mockedFetch.mockImplementation((opts) => {
      signal = opts?.signal ?? undefined;
      return new Promise<GraphStatusResponse>((_resolve, reject) => {
        signal?.addEventListener(
          'abort',
          () => reject(new DOMException('The operation was aborted.', 'AbortError')),
          { once: true },
        );
      });
    });

    const promise = useGraphStore.getState().fetch();
    expect(useGraphStore.getState().loading).toBe(true);

    await vi.advanceTimersByTimeAsync(15_000);
    await promise;

    expect(signal?.aborted).toBe(true);
    expect(useGraphStore.getState().status).toBeNull();
    expect(useGraphStore.getState().error).toBe(true);
    expect(useGraphStore.getState().loading).toBe(false);
  });

  it('invalidate clears TTL and triggers refetch', async () => {
    const status1 = makeStatus({ node_count: 10 });
    const status2 = makeStatus({ node_count: 50 });
    mockedFetch.mockResolvedValueOnce(status1).mockResolvedValueOnce(status2);

    await useGraphStore.getState().fetch();
    expect(useGraphStore.getState().status?.node_count).toBe(10);

    useGraphStore.getState().invalidate();
    await vi.waitFor(() => {
      expect(useGraphStore.getState().status?.node_count).toBe(50);
    });
  });

  it('concurrent fetch calls deduplicate', async () => {
    mockedFetch.mockResolvedValue(makeStatus());

    const p1 = useGraphStore.getState().fetch();
    const p2 = useGraphStore.getState().fetch();
    await Promise.all([p1, p2]);

    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });

  it('concurrent fetch does not crash on rejection', async () => {
    mockedFetch.mockRejectedValue(new Error('fail'));

    const p1 = useGraphStore.getState().fetch();
    const p2 = useGraphStore.getState().fetch();
    await Promise.all([p1, p2]);

    expect(useGraphStore.getState().error).toBe(true);
  });

  it('invalidate during in-flight fetch does not deadlock loading', async () => {
    let firstSignal: AbortSignal | undefined;
    const status2 = makeStatus({ node_count: 99 });
    mockedFetch
      .mockImplementationOnce((opts) => {
        firstSignal = opts?.signal ?? undefined;
        return new Promise<GraphStatusResponse>((_resolve, reject) => {
          firstSignal?.addEventListener(
            'abort',
            () => reject(new DOMException('The operation was aborted.', 'AbortError')),
            { once: true },
          );
        });
      })
      .mockResolvedValueOnce(status2);

    // Start first fetch — enters loading state
    const p1 = useGraphStore.getState().fetch();
    expect(useGraphStore.getState().loading).toBe(true);

    // Invalidate while first fetch is in-flight
    useGraphStore.getState().invalidate();

    // The stale fetch is aborted and the invalidate-triggered fetch wins.
    await p1;

    // Wait for second fetch triggered by invalidate
    await vi.waitFor(() => {
      expect(useGraphStore.getState().loading).toBe(false);
    });
    expect(firstSignal?.aborted).toBe(true);
    expect(useGraphStore.getState().status?.node_count).toBe(99);
  });
});
