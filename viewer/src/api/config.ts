import { apiFetch } from './client';
import type { ApiFetchOptions } from './client';

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
}

export interface DoctorResponse {
  checks: DoctorCheck[];
}

export interface InstallTarget {
  name: string;
  detected: boolean;
  platform_supported: boolean;
  description: string;
}

export interface InstallTargetsResponse {
  targets: InstallTarget[];
}

export async function getConfig(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<ConfigResponse> {
  return apiFetch<ConfigResponse>('/api/config', opts);
}

export async function getDoctor(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<DoctorResponse> {
  return apiFetch<DoctorResponse>('/api/doctor', opts);
}

export async function getInstallTargets(
  opts?: Pick<ApiFetchOptions, 'signal'>,
): Promise<InstallTargetsResponse> {
  return apiFetch<InstallTargetsResponse>('/api/install/targets', opts);
}
