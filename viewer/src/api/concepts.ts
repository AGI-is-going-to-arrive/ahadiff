import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import { conceptLedgerResponseSchema, parseResponse } from './schemas';
import type { ConceptLedgerResponse } from './types';

export async function getConceptLedger(
  params: { cursor?: string; limit?: number; run?: string } = {},
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ConceptLedgerResponse> {
  const q = new URLSearchParams();
  if (params.cursor != null) q.set('cursor', params.cursor);
  if (params.limit != null) q.set('limit', String(params.limit));
  if (params.run != null) q.set('run', params.run);
  const qs = q.toString();
  const raw = await apiFetch<unknown>(`/api/concepts/ledger${qs ? `?${qs}` : ''}`, opts);
  return parseResponse('GET /api/concepts/ledger', conceptLedgerResponseSchema, raw);
}
