/**
 * Platform detection helpers for the Onboarding page.
 *
 * Detection is based on `navigator.userAgent` only — we do not depend on
 * `navigator.platform` (deprecated) or `navigator.userAgentData` (Chromium-only).
 * The detection is best-effort and is used to surface platform-appropriate
 * shell hints and environment-variable syntax in onboarding copy. Server-side
 * (or non-browser) callers should fall back to `'linux'`.
 */

export type Platform = 'windows' | 'macos' | 'linux';

export function detectPlatform(): Platform {
  if (typeof navigator === 'undefined' || !navigator.userAgent) return 'linux';
  const ua = navigator.userAgent.toLowerCase();
  if (ua.includes('win')) return 'windows';
  if (ua.includes('mac')) return 'macos';
  return 'linux';
}

export function getInstallCommand(_platform: Platform): string {
  // AhaDiff is not published on PyPI yet. Install the CLI from the current
  // source checkout into uv's isolated tool environment.
  return 'uv tool install --editable .';
}

export function getShellHint(platform: Platform): string {
  switch (platform) {
    case 'windows':
      return 'PowerShell';
    case 'macos':
      return 'Terminal';
    case 'linux':
      return 'Terminal';
  }
}

/**
 * Returns the platform-appropriate command to set an environment variable.
 *
 * Windows uses PowerShell `$env:NAME = "value"` syntax. macOS / Linux use
 * POSIX `export NAME="value"`. Values are wrapped in double quotes; callers
 * must not pass values containing double quotes (the value is a placeholder
 * in the onboarding hint, not user input).
 */
export function getEnvVarCommand(
  platform: Platform,
  name: string,
  value: string,
): string {
  if (platform === 'windows') {
    return `$env:${name} = "${value}"`;
  }
  return `export ${name}="${value}"`;
}

export function getPlatformLabel(platform: Platform): string {
  switch (platform) {
    case 'windows':
      return 'Windows';
    case 'macos':
      return 'macOS';
    case 'linux':
      return 'Linux';
  }
}
