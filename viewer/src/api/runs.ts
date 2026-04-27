import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import type {
  ArtifactKind,
  PaginatedConceptsResponse,
  PaginatedRunsResponse,
  RatchetHistoryResponse,
  RunArtifactEnvelope,
  RunDetail,
} from './types';

export async function listRuns(
  params: { source_kind?: string; cursor?: string; page_size?: number } = {},
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<PaginatedRunsResponse> {
  const q = new URLSearchParams();
  if (params.source_kind) q.set('source_kind', params.source_kind);
  if (params.cursor) q.set('cursor', params.cursor);
  if (params.page_size != null) q.set('page_size', String(params.page_size));
  const qs = q.toString();
  return apiFetch<PaginatedRunsResponse>(`/api/runs${qs ? `?${qs}` : ''}`, opts);
}

export async function getRun(
  runId: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RunDetail> {
  return apiFetch<RunDetail>(`/api/run/${encodeURIComponent(runId)}`, opts);
}

export async function getRunLesson(
  runId: string,
  level: 'full' | 'hint' | 'compact' = 'full',
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RunArtifactEnvelope> {
  const q = new URLSearchParams({ level });
  return apiFetch<RunArtifactEnvelope>(
    `/api/run/${encodeURIComponent(runId)}/lesson?${q.toString()}`,
    opts,
  );
}

export async function getRunArtifact(
  runId: string,
  kind: Exclude<ArtifactKind, 'lesson'>,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RunArtifactEnvelope> {
  return apiFetch<RunArtifactEnvelope>(
    `/api/run/${encodeURIComponent(runId)}/${kind}`,
    opts,
  );
}

export async function getGlobalConcepts(
  params: { cursor?: string; page_size?: number } = {},
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<PaginatedConceptsResponse> {
  const q = new URLSearchParams();
  if (params.cursor) q.set('cursor', params.cursor);
  if (params.page_size != null) q.set('page_size', String(params.page_size));
  const qs = q.toString();
  return apiFetch<PaginatedConceptsResponse>(`/api/concepts${qs ? `?${qs}` : ''}`, opts);
}

export async function getRunConcepts(
  runId: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RunArtifactEnvelope> {
  return apiFetch<RunArtifactEnvelope>(
    `/api/run/${encodeURIComponent(runId)}/concepts`,
    opts,
  );
}

export async function getRatchetHistory(
  params: { cursor?: string; page_size?: number } = {},
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RatchetHistoryResponse> {
  const q = new URLSearchParams();
  if (params.cursor) q.set('cursor', params.cursor);
  if (params.page_size != null) q.set('page_size', String(params.page_size));
  const qs = q.toString();
  return apiFetch<RatchetHistoryResponse>(`/api/ratchet/history${qs ? `?${qs}` : ''}`, opts);
}
