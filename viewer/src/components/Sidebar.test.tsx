import { describe, expect, it } from 'vitest';
import { formatProviderStatus, type ProviderStatus } from './Sidebar';

const messages: Record<string, string> = {
  'Settings_page.privacy_mode_strict_local': 'Strict local (no remote)',
  'Settings_page.privacy_mode_redacted_remote': 'Redacted remote',
  'Settings_page.privacy_mode_explicit_remote': 'Explicit remote (raw upload)',
  'Sidebar.status.config_unavailable': 'Configuration unavailable',
  'Sidebar.status.loading_config': 'Loading configuration',
  'Sidebar.status.no_provider': 'No provider configured',
  'Sidebar.status.unknown_privacy': 'Unknown privacy mode',
};

const t = ((key: string) => messages[key] ?? key) as Parameters<typeof formatProviderStatus>[1];

describe('Sidebar provider status footer', () => {
  it('renders localized privacy labels with the configured provider', () => {
    const status: ProviderStatus = {
      state: 'ready',
      privacyMode: 'strict_local',
      provider: 'ollama',
    };

    expect(formatProviderStatus(status, t)).toBe('Strict local (no remote) · ollama');
  });

  it.each([
    [{ state: 'loading' }, 'Loading configuration'],
    [{ state: 'empty' }, 'No provider configured'],
    [{ state: 'error' }, 'Configuration unavailable'],
  ] as const)('renders %s state without exposing raw config values', (status, expected) => {
    expect(formatProviderStatus(status, t)).toBe(expected);
  });
});
