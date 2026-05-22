import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
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

describe('Sidebar GitHub footer link', () => {
  const src = readFileSync(resolve(__dirname, 'Sidebar.tsx'), 'utf-8');
  const css = readFileSync(resolve(__dirname, 'Sidebar.css'), 'utf-8');

  it('renders a GitHub repo link with target=_blank and noopener', () => {
    expect(src).toContain('side-foot__github');
    expect(src).toContain('href="https://github.com/AGI-is-going-to-arrive/ahadiff"');
    expect(src).toContain('target="_blank"');
    expect(src).toContain('rel="noopener noreferrer"');
    expect(src).toContain("t('Sidebar.github_link')");
    expect(src).toContain("t('Sidebar.github_aria')");
  });

  it('uses an inline GitHub SVG with aria-hidden so the icon does not bleed into AT names', () => {
    expect(src).toContain('side-foot__github-icon');
    expect(src).toMatch(/<svg[^>]+aria-hidden="true"/);
  });

  it('styles the GitHub link with tokens, reduced-motion, and forced-colors fallbacks', () => {
    expect(css).toContain('.side-foot__github');
    // No new hex colours: only token references / CSS system colours.
    const block = css.match(/\.side-foot__github\s*\{[\s\S]*?\n\}/);
    expect(block).not.toBeNull();
    expect(block?.[0]).toContain('var(--muted)');

    const reducedMotion = css.match(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[\s\S]*?\n\}/);
    expect(reducedMotion?.[0]).toContain('.side-foot__github');

    const forcedColors = css.match(/@media\s*\(forced-colors:\s*active\)\s*\{[\s\S]*?\n\}/);
    expect(forcedColors?.[0]).toContain('.side-foot__github');
    expect(forcedColors?.[0]).toContain('LinkText');
  });
});
