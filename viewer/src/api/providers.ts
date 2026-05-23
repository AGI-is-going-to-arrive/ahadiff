import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  modelLimitsResponseSchema,
  parseResponse,
  providerDeleteResponseSchema,
  providerModelsResponseSchema,
  providerMutationResponseSchema,
  providerProbeSubmitResponseSchema,
} from './schemas';
import type {
  ProviderCreateInput,
  ProviderDeleteResponse,
  ProviderModelsResponse,
  ProviderMutationResponse,
  ProviderProbeSubmitResponse,
  ProviderUpdateInput,
} from './types';

export async function createProvider(
  data: ProviderCreateInput,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ProviderMutationResponse> {
  const raw = await apiFetch<unknown>('/api/providers', {
    method: 'POST',
    body: JSON.stringify(data),
    signal: opts?.signal,
  });
  return parseResponse('POST /api/providers', providerMutationResponseSchema, raw);
}

export async function updateProvider(
  alias: string,
  data: ProviderUpdateInput,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ProviderMutationResponse> {
  const raw = await apiFetch<unknown>(
    `/api/providers/${encodeURIComponent(alias)}`,
    {
      method: 'PUT',
      body: JSON.stringify(data),
      signal: opts?.signal,
    },
  );
  return parseResponse(
    'PUT /api/providers/{alias}',
    providerMutationResponseSchema,
    raw,
  );
}

export async function deleteProvider(
  alias: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ProviderDeleteResponse> {
  const raw = await apiFetch<unknown>(
    `/api/providers/${encodeURIComponent(alias)}`,
    {
      method: 'DELETE',
      signal: opts?.signal,
    },
  );
  return parseResponse(
    'DELETE /api/providers/{alias}',
    providerDeleteResponseSchema,
    raw,
  );
}

export async function discoverModels(
  data: { base_url: string; api_key: string; provider_class: string },
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ProviderModelsResponse> {
  const raw = await apiFetch<unknown>('/api/providers/discover-models', {
    method: 'POST',
    body: JSON.stringify(data),
    signal: opts?.signal,
  });
  return parseResponse(
    'POST /api/providers/discover-models',
    providerModelsResponseSchema,
    raw,
  );
}

export async function fetchProviderModels(
  alias: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ProviderModelsResponse> {
  const raw = await apiFetch<unknown>(
    `/api/providers/${encodeURIComponent(alias)}/models`,
    { signal: opts?.signal },
  );
  return parseResponse(
    'GET /api/providers/{alias}/models',
    providerModelsResponseSchema,
    raw,
  );
}

export async function saveProviderModels(
  alias: string,
  models: string[],
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ProviderMutationResponse> {
  const raw = await apiFetch<unknown>(
    `/api/providers/${encodeURIComponent(alias)}/models`,
    {
      method: 'PUT',
      body: JSON.stringify({ models }),
      signal: opts?.signal,
    },
  );
  return parseResponse(
    'PUT /api/providers/{alias}/models',
    providerMutationResponseSchema,
    raw,
  );
}

export async function probeProvider(
  alias: string,
  force?: boolean,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ProviderProbeSubmitResponse> {
  const raw = await apiFetch<unknown>(
    `/api/providers/${encodeURIComponent(alias)}/probe`,
    {
      method: 'POST',
      body: JSON.stringify(force === undefined ? {} : { force }),
      signal: opts?.signal,
    },
  );
  return parseResponse(
    'POST /api/providers/{alias}/probe',
    providerProbeSubmitResponseSchema,
    raw,
  );
}

export async function getProviderModelLimits(
  alias: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<import('./types').ModelLimitsResponse> {
  const raw = await apiFetch<unknown>(
    `/api/providers/${encodeURIComponent(alias)}/model-limits`,
    { signal: opts?.signal },
  );
  return parseResponse('GET /api/providers/{alias}/model-limits', modelLimitsResponseSchema, raw);
}

export async function previewModelLimits(
  data: { provider_class: string; model_name: string; model_limits_name?: string | null },
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<import('./types').ModelLimitsResponse> {
  const raw = await apiFetch<unknown>('/api/providers/model-limits/preview', {
    method: 'POST',
    body: JSON.stringify(data),
    signal: opts?.signal,
  });
  return parseResponse('POST /api/providers/model-limits/preview', modelLimitsResponseSchema, raw);
}
