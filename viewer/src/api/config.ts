import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  auditResponseSchema,
  configResponseSchema,
  configUpdateResponseSchema,
  dbCheckResultSchema,
  doctorResponseSchema,
  installTargetMutationResponseSchema,
  installTargetPreviewResponseSchema,
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

export interface QuizConfig {
  quiz_question_count: number;
  quiz_question_count_mode: 'fixed' | 'auto';
  quiz_auto_range_min: number;
  quiz_auto_range_max: number;
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
  quiz: QuizConfig;
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

export interface DbCheckResult {
  healthy: boolean;
  schema_version: number;
  quick_check: string;
  event_count: number;
  card_count: number;
}

export interface InstallTarget {
  name: string;
  display_name: string;
  detected: boolean;
  platform_supported: boolean;
  status: 'installed' | 'available' | 'unsupported' | 'error';
  description: string;
  install_command?: string;
  uninstall_command?: string;
  manifest?: InstallManifestSummary | null;
  manifest_hash?: string | null;
  manifest_error?: string | null;
  error_message?: string | null;
}

export interface InstallManifestAction {
  action: string;
  file_strategy: 'generated' | 'user-managed';
  path: string;
}

export interface InstallManifestSummary {
  preview: InstallManifestAction[];
  write: InstallManifestAction[];
  uninstall: InstallManifestAction[];
}

export interface InstallTargetsResponse {
  targets: InstallTarget[];
  total: number;
}

export interface InstallTargetPreviewResponse {
  target: InstallTarget;
  manifest_hash: string;
}

export interface InstallTargetMutationResponse {
  target: InstallTarget;
  operation: 'install' | 'uninstall';
  updated: boolean;
  updated_paths: string[];
  manifest_hash: string;
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

export async function fetchDbCheck(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<DbCheckResult> {
  const raw = await apiFetch<unknown>('/api/db/check', { method: 'POST', ...opts });
  return parseResponse('POST /api/db/check', dbCheckResultSchema, raw);
}

export async function getInstallTargets(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<InstallTargetsResponse> {
  const raw = await apiFetch<unknown>('/api/install/targets', opts);
  return parseResponse('GET /api/install/targets', installTargetsResponseSchema, raw);
}

function installTargetPath(name: string, suffix = ''): string {
  return `/api/install/${encodeURIComponent(name)}${suffix}`;
}

export async function previewInstallTarget(
  name: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<InstallTargetPreviewResponse> {
  const raw = await apiFetch<unknown>(installTargetPath(name, '/preview'), {
    method: 'POST',
    body: JSON.stringify({}),
    signal: opts?.signal,
  });
  return parseResponse(
    `POST /api/install/${name}/preview`,
    installTargetPreviewResponseSchema,
    raw,
  );
}

export async function applyInstallTarget(
  name: string,
  confirmedManifestHash: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<InstallTargetMutationResponse> {
  const raw = await apiFetch<unknown>(installTargetPath(name), {
    method: 'POST',
    body: JSON.stringify({ confirmed_manifest_hash: confirmedManifestHash }),
    signal: opts?.signal,
  });
  return parseResponse(
    `POST /api/install/${name}`,
    installTargetMutationResponseSchema,
    raw,
  );
}

export async function removeInstallTarget(
  name: string,
  confirmedManifestHash: string,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<InstallTargetMutationResponse> {
  const raw = await apiFetch<unknown>(installTargetPath(name, '/uninstall'), {
    method: 'POST',
    body: JSON.stringify({ confirmed_manifest_hash: confirmedManifestHash }),
    signal: opts?.signal,
  });
  return parseResponse(
    `POST /api/install/${name}/uninstall`,
    installTargetMutationResponseSchema,
    raw,
  );
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
  limit = 20,
  offset = 0,
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<AuditResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const raw = await apiFetch<unknown>(`/api/audit?${params.toString()}`, opts);
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
