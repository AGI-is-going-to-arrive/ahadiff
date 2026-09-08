import { apiFetch, type ApiFetchOptions } from './client';
import {
  parseResponse, snapshotDeleteResponseSchema, snapshotListResponseSchema,
  snapshotRecordSchema, snapshotSummarySchema,
} from './schemas';
import type { LearnFileInput, SnapshotListResponse, SnapshotRecord, SnapshotSummary } from './types';

type RequestOptions = Pick<ApiFetchOptions, 'signal'>;

export async function listSnapshots(opts?: RequestOptions): Promise<SnapshotListResponse> {
  const raw = await apiFetch<unknown>('/api/snapshots', opts);
  return parseResponse('GET /api/snapshots', snapshotListResponseSchema, raw);
}

export async function saveSnapshot(
  payload: { name: string; file: LearnFileInput }, opts?: RequestOptions,
): Promise<SnapshotSummary> {
  const raw = await apiFetch<unknown>('/api/snapshots', {
    ...opts, method: 'POST', body: JSON.stringify(payload),
  });
  return parseResponse('POST /api/snapshots', snapshotSummarySchema, raw);
}

export async function getSnapshot(snapshotId: string, opts?: RequestOptions): Promise<SnapshotRecord> {
  const raw = await apiFetch<unknown>(`/api/snapshots/${encodeURIComponent(snapshotId)}`, opts);
  return parseResponse('GET /api/snapshots/{id}', snapshotRecordSchema, raw);
}

export async function deleteSnapshot(
  snapshotId: string, expectedHash: string, opts?: RequestOptions,
): Promise<{ snapshot_id: string; deleted: true }> {
  const raw = await apiFetch<unknown>(`/api/snapshots/${encodeURIComponent(snapshotId)}`, {
    ...opts, method: 'DELETE', body: JSON.stringify({ expected_hash: expectedHash }),
  });
  return parseResponse('DELETE /api/snapshots/{id}', snapshotDeleteResponseSchema, raw);
}
