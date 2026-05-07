import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  auditResponseSchema,
  configResponseSchema,
  configUpdateResponseSchema,
  doctorResponseSchema,
  installTargetsResponseSchema,
  parseResponse,
  providersResponseSchema,
  usageResponseSchema,
} from './schemas';

export interface ConfigField {
  key: string;
  value: string | number | boolean | null;
  source: string;
}

export interface CaptureConfig {
  max_files: number;
  hard_limit: number;
  max_patch_bytes: number;
  file_ranking: string;
  symbol_extractor: string;
}

export interface LlmConfig {
  input_token_budget: number;
  output_token_budget: number;
  request_timeout_seconds: number;
  max_concurrent: number;
  retry_attempts: number;
  output_lang: string;
}

export interface LearnConfig {
  learnability_threshold: number;
  desired_retention?: number;
}

export interface ConfigResponse {
  lang: string | null;
  privacy_mode: string | null;
  generate_provider: string | null;
  generate_model: string | null;
  judge_provider: string | null;
  judge_model: string | null;
  serve_port: number | null;
  key_status: Record<string, 'configured' | 'missing'>;
  capture: CaptureConfig;
  llm: LlmConfig;
  learn: LearnConfig;
}

export interface ConfigUpdateResponse {
  updated: boolean;
  scope: 'session';
}

export interface DoctorCheck {
  name: string;
  status: 'pass' | 'warn' | 'fail';
  message: string;
  category: string;
  details?: Record<string, unknown>;
}

export interface DoctorResponse {
  summary_status: 'pass' | 'warn' | 'fail';
  checks: DoctorCheck[];
}

export interface InstallTarget {
  name: string;
  display_name: string;
  detected: boolean;
  platform_supported: boolean;
  status: 'installed' | 'available' | 'unsupported' | 'error';
  description: string;
  error_message?: string | null;
}

export interface InstallTargetsResponse {
  targets: InstallTarget[];
  total: number;
}

export interface ProviderSummary {
  alias: string;
  role?: string | null;
  provider_class: string;
  provider_kind: string;
  model_name: string;
  base_url: string;
  api_key_env?: string | null;
  key_status: 'configured' | 'missing' | 'unknown';
  api_family?: string | null;
  api_family_version?: string | null;
  max_output_tokens?: number | null;
  thinking_level?: string | null;
  probed: boolean;
  probed_max_context: number | null;
  probed_tpm?: number | null;
  probed_rpm?: number | null;
  probe_timestamp?: string | null;
  available_models?: string[];
}

export interface ProvidersResponse {
  providers: ProviderSummary[];
}

export interface UsageModelSummary {
  provider_class: string;
  model_id: string;
  call_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
}

export interface UsageResponse {
  models: UsageModelSummary[];
  total_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  cache_hits: number;
  cache_misses: number;
}

export interface AuditEntry {
  timestamp?: string;
  ts?: string;
  event_type?: string;
  action?: string;
  provider_class?: string;
  provider_kind?: string;
  model_id?: string;
  prompt_name?: string;
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: number | null;
  cost_confidence?: string;
  execution_origin?: string;
  note?: string;
  files_sent?: string | number;
  file_count?: number;
  files?: unknown;
  [key: string]: unknown;
}

export interface AuditResponse {
  entries: AuditEntry[];
  total: number;
  limit: number;
  offset: number;
  page: number;
  has_more: boolean;
  next_cursor?: string | null;
  fields?: string[] | null;
}

export async function getConfig(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ConfigResponse> {
  const raw = await apiFetch<unknown>('/api/config', opts);
  return parseResponse('GET /api/config', configResponseSchema, raw);
}

export async function getDoctor(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<DoctorResponse> {
  const raw = await apiFetch<unknown>('/api/doctor', opts);
  return parseResponse('GET /api/doctor', doctorResponseSchema, raw);
}

export async function getInstallTargets(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<InstallTargetsResponse> {
  const raw = await apiFetch<unknown>('/api/install/targets', opts);
  return parseResponse('GET /api/install/targets', installTargetsResponseSchema, raw);
}

export async function getProviders(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ProvidersResponse> {
  const raw = await apiFetch<unknown>('/api/providers', opts);
  return parseResponse('GET /api/providers', providersResponseSchema, raw);
}

export async function getUsage(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<UsageResponse> {
  const raw = await apiFetch<unknown>('/api/usage', opts);
  return parseResponse('GET /api/usage', usageResponseSchema, raw);
}

export async function getAudit(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<AuditResponse> {
  const raw = await apiFetch<unknown>('/api/audit?limit=20', opts);
  return parseResponse('GET /api/audit', auditResponseSchema, raw);
}

export async function putConfig(
  body: Record<string, unknown>,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ConfigUpdateResponse> {
  const raw = await apiFetch<unknown>('/api/config', {
    method: 'PUT',
    body: JSON.stringify(body),
    signal: opts?.signal,
  });
  return parseResponse('PUT /api/config', configUpdateResponseSchema, raw);
}
