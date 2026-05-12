import type { ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ExportPreviewManifest } from '../api/client';

const previewManifest: ExportPreviewManifest = {
  path: '.ahadiff/exports/run-1',
  manifest_digest: 'sha256:abc',
  file_count: 4,
  total_bytes: 128,
  created_at_utc: '2026-05-12T00:00:00Z',
  privacy_mode: 'strict_local',
  run_id: 'run-1',
  cleared_stale_files: ['old/index.html', '旧数据.json'],
};

const stateOverrides: unknown[] = [];
let stateCallCounter = 0;

vi.mock('react', async () => {
  const actual = await vi.importActual<typeof import('react')>('react');
  return {
    ...actual,
    useState: <S,>(initial: S | (() => S)) => {
      const idx = stateCallCounter++;
      const init =
        typeof initial === 'function' ? (initial as () => S)() : initial;
      const value = (idx < stateOverrides.length ? stateOverrides[idx] : init) as S;
      return [value, (() => undefined) as unknown as (value: S) => void] as [
        S,
        (value: S) => void,
      ];
    },
  };
});

vi.mock('react-dom', async () => {
  const actual = await vi.importActual<typeof import('react-dom')>('react-dom');
  return {
    ...actual,
    createPortal: (children: ReactNode) => children,
  };
});

vi.mock('../i18n/useTranslation', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, string | number>): string => {
      if (key === 'Export.preview_cleared_stale_files') {
        return `cleared ${String(params?.count ?? '{count}')}`;
      }
      if (!params) return key;
      return Object.entries(params).reduce(
        (acc, [name, value]) => acc.replace(`{${name}}`, String(value)),
        key,
      );
    },
  }),
}));

describe('ExportModal', () => {
  beforeEach(() => {
    stateOverrides.length = 0;
    stateCallCounter = 0;
    vi.stubGlobal('document', { body: {} });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders a warning when preview export cleared stale files', async () => {
    stateOverrides.push({
      busyKey: null,
      error: null,
      previewManifest,
    });
    const { default: ExportModal } = await import('./ExportModal');

    const html = renderToStaticMarkup(
      <ExportModal open onClose={() => undefined} runId="run-1" />,
    );

    expect(html).toContain('cleared 2');
  });
});
