import { afterEach, describe, expect, it, vi } from 'vitest';
import { exportPreview, resetToken, setToken } from './client';
import { ValidationError } from './schemas';

describe('exportPreview API boundary', () => {
  afterEach(() => {
    resetToken();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('validates the serve response shape before returning it', async () => {
    vi.stubGlobal('window', { location: { origin: 'http://localhost:8765' } });
    setToken('test-token');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          path: 'exports/run-1',
          manifest_digest: '0'.repeat(64),
          file_count: '4',
          total_bytes: 123,
          created_at_utc: '2026-05-12T00:00:00Z',
          privacy_mode: 'strict_local',
          run_id: 'run-1',
          cleared_stale_files: [],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    );

    await expect(exportPreview('run-1')).rejects.toBeInstanceOf(ValidationError);
  });
});
