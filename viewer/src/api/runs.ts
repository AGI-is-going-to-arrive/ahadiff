import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import type {
  ArtifactKind,
  RatchetHistoryEntry,
  RunArtifactEnvelope,
  RunDetail,
  RunSummary,
} from './types';

export async function listRuns(
  params: { source_kind?: string } = {},
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RunSummary[]> {
  const q = new URLSearchParams();
  if (params.source_kind) q.set('source_kind', params.source_kind);
  const qs = q.toString();
  const envelope = await apiFetch<{ runs: RunSummary[] }>(`/api/runs${qs ? `?${qs}` : ''}`, opts);
  return envelope.runs;
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
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<{ content: string }> {
  return apiFetch<{ content: string }>('/api/concepts', opts);
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
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<RatchetHistoryEntry[]> {
  return apiFetch<RatchetHistoryEntry[]>('/api/ratchet/history', opts);
}
