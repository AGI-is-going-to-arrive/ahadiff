import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';
import {
  configResponseSchema,
  doctorResponseSchema,
  installTargetsResponseSchema,
  parseResponse,
} from './schemas';

export interface ConfigField {
  key: string;
  value: string | number | boolean | null;
  source: string;
}

export interface ConfigResponse {
  lang: string | null;
  privacy_mode: string | null;
  generate_model: string | null;
  judge_model: string | null;
  serve_port: number | null;
  key_status: Record<string, 'configured' | 'missing'>;
}

export interface DoctorCheck {
  name: string;
  status: 'pass' | 'warn' | 'fail';
  message: string;
  category?: string;
  details?: Record<string, unknown>;
}

export interface DoctorResponse {
  summary_status?: 'pass' | 'warn' | 'fail';
  checks: DoctorCheck[];
}

export interface InstallTarget {
  name: string;
  display_name?: string;
  detected: boolean;
  platform_supported: boolean;
  status?: 'installed' | 'available' | 'unsupported' | 'error';
  description: string;
  error_message?: string | null;
}

export interface InstallTargetsResponse {
  targets: InstallTarget[];
  total?: number;
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
