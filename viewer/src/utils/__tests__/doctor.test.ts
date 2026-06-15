import { describe, expect, it } from 'vitest';
import { isProviderOnlySensitiveCheck } from '../doctor';
import type { DoctorCheck } from '../../api/config';

function check(overrides: Partial<DoctorCheck> = {}): DoctorCheck {
  return {
    name: 'config_sensitive_keys',
    status: 'fail',
    message: 'Sensitive config keys found',
    category: 'config',
    details: { count: 1, keys: ['providers.openai.api_key_env'] },
    ...overrides,
  };
}

describe('isProviderOnlySensitiveCheck', () => {
  it('is true when every sensitive key is a provider api_key_env literal', () => {
    expect(
      isProviderOnlySensitiveCheck(
        check({
          details: {
            count: 2,
            keys: ['providers.openai.api_key_env', 'providers.azure.api_key_env'],
          },
        }),
      ),
    ).toBe(true);
  });

  it('is false when a non-provider sensitive key is present', () => {
    expect(
      isProviderOnlySensitiveCheck(
        check({
          details: {
            count: 2,
            keys: ['providers.openai.api_key_env', 'safety.webhook_secret'],
          },
        }),
      ),
    ).toBe(false);
  });

  it('is false for a non-provider secret/token key', () => {
    expect(
      isProviderOnlySensitiveCheck(
        check({ details: { count: 1, keys: ['integrations.github_token'] } }),
      ),
    ).toBe(false);
  });

  it('is false when not the config_sensitive_keys check', () => {
    expect(isProviderOnlySensitiveCheck(check({ name: 'config_unknown_keys' }))).toBe(false);
  });

  it('is false when status is not fail', () => {
    expect(isProviderOnlySensitiveCheck(check({ status: 'pass' }))).toBe(false);
  });

  it('is false when the keys list is empty', () => {
    expect(isProviderOnlySensitiveCheck(check({ details: { count: 0, keys: [] } }))).toBe(false);
  });

  it('is false (conservative) when details.keys was truncated below count', () => {
    expect(
      isProviderOnlySensitiveCheck(
        check({ details: { count: 25, keys: ['providers.openai.api_key_env'] } }),
      ),
    ).toBe(false);
  });

  it('is false when details is missing', () => {
    expect(isProviderOnlySensitiveCheck(check({ details: undefined }))).toBe(false);
  });
});
