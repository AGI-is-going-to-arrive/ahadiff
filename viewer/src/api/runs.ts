import { apiFetch, apiFetchBlob } from './client';
import type { ApiFetchOptions } from './client';
import {
  paginatedRunsResponseSchema,
  parseResponse,
  ratchetHistoryResponseSchema,
  ratchetTransparencyResponseSchema,
  runArtifactEnvelopeSchema,
  runDetailSchema,
} from './schemas';
import type {
  ArtifactKind,
  PaginatedRunsResponse,
  RatchetHistoryResponse,
  RatchetTransparencyResponse,
  RunArtifactEnvelope,
  RunDetail,
} from './types';

export async function getRunScore(
  runId: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RunArtifactEnvelope> {
  const raw = await apiFetch<unknown>(
    `/api/run/${encodeURIComponent(runId)}/score`,
    opts,
  );
  return parseResponse('GET /api/run/{runId}/score', runArtifactEnvelopeSchema, raw);
}

export async function listRuns(
  params: { source_kind?: string; cursor?: string; page_size?: number } = {},
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<PaginatedRunsResponse> {
  const q = new URLSearchParams();
  if (params.source_kind) q.set('source_kind', params.source_kind);
  if (params.cursor) q.set('cursor', params.cursor);
  if (params.page_size != null) q.set('page_size', String(params.page_size));
  const qs = q.toString();
  const raw = await apiFetch<unknown>(`/api/runs${qs ? `?${qs}` : ''}`, opts);
  return parseResponse('GET /api/runs', paginatedRunsResponseSchema, raw);
}

export async function getRun(
  runId: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RunDetail> {
  const raw = await apiFetch<unknown>(`/api/run/${encodeURIComponent(runId)}`, opts);
  return parseResponse('GET /api/run/{runId}', runDetailSchema, raw);
}

export async function getRunLesson(
  runId: string,
  level: 'full' | 'hint' | 'compact' = 'full',
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RunArtifactEnvelope> {
  const q = new URLSearchParams({ level });
  const raw = await apiFetch<unknown>(
    `/api/run/${encodeURIComponent(runId)}/lesson?${q.toString()}`,
    opts,
  );
  return parseResponse('GET /api/run/{runId}/lesson', runArtifactEnvelopeSchema, raw);
}

export async function getRunArtifact(
  runId: string,
  kind: Exclude<ArtifactKind, 'lesson'>,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RunArtifactEnvelope> {
  const raw = await apiFetch<unknown>(
    `/api/run/${encodeURIComponent(runId)}/${kind}`,
    opts,
  );
  return parseResponse(`GET /api/run/{runId}/${kind}`, runArtifactEnvelopeSchema, raw);
}

export async function getRunConcepts(
  runId: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<string> {
  const raw = await apiFetch<unknown>(
    `/api/run/${encodeURIComponent(runId)}/concepts`,
    opts,
  );
  const env = parseResponse(
    'GET /api/run/{runId}/concepts',
    runArtifactEnvelopeSchema,
    raw,
  );
  return env.content;
}

export async function getRatchetHistory(
  params: { cursor?: string; page_size?: number } = {},
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RatchetHistoryResponse> {
  const q = new URLSearchParams();
  if (params.cursor) q.set('cursor', params.cursor);
  if (params.page_size != null) q.set('page_size', String(params.page_size));
  const qs = q.toString();
  const raw = await apiFetch<unknown>(`/api/ratchet/history${qs ? `?${qs}` : ''}`, opts);
  return parseResponse('GET /api/ratchet/history', ratchetHistoryResponseSchema, raw);
}

export async function getRatchetTransparency(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RatchetTransparencyResponse> {
  const raw = await apiFetch<unknown>('/api/ratchet/transparency', opts);
  return parseResponse(
    'GET /api/ratchet/transparency',
    ratchetTransparencyResponseSchema,
    raw,
  );
}

export async function getExportResultsTsvBlob(opts?: Pick<RequestInit, 'signal'>): Promise<Blob> {
  return apiFetchBlob('/api/export/results?format=tsv', opts);
}

export async function getExportResultsJsonBlob(opts?: Pick<RequestInit, 'signal'>): Promise<Blob> {
  return apiFetchBlob('/api/export/results?format=json', opts);
}

export async function getExportApkgBlob(opts?: Pick<RequestInit, 'signal'>): Promise<Blob> {
  return apiFetchBlob('/api/export/apkg', opts);
}
