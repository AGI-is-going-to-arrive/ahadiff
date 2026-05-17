import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('../../components/AppShell', () => ({
  default: ({ children }: { children: ReactNode }) => (
    <div data-testid="app-shell-mock">{children}</div>
  ),
}));

vi.mock('../../components/CommandBlock', () => ({
  CommandBlock: ({ command }: { command: string }) => (
    <pre data-testid="guide-command" data-command={command}>
      {command}
    </pre>
  ),
}));

vi.mock('../../api/config', async () => {
  const actual = await vi.importActual<typeof import('../../api/config')>(
    '../../api/config',
  );
  return {
    ...actual,
    getInstallTargets: vi.fn().mockResolvedValue({ targets: [], total: 0 }),
  };
});

vi.mock('../../utils/platform', async () => {
  const actual = await vi.importActual<typeof import('../../utils/platform')>(
    '../../utils/platform',
  );
  return {
    ...actual,
    detectPlatform: () => 'linux' as const,
    getEnvVarCommand: (_p: unknown, name: string, value: string) =>
      `export ${name}="${value}"`,
  };
});

vi.mock('../../i18n/useTranslation', async () => {
  const zhCNMessages = (await import('../../i18n/messages/zh-CN.json'))
    .default as Record<string, unknown>;
  function lookup(tree: Record<string, unknown>, dotKey: string): string | undefined {
    const parts = dotKey.split('.');
    let current: unknown = tree;
    for (const p of parts) {
      if (current && typeof current === 'object' && p in (current as Record<string, unknown>)) {
        current = (current as Record<string, unknown>)[p];
      } else {
        return undefined;
      }
    }
    return typeof current === 'string' ? current : undefined;
  }
  function interpolate(t: string, params?: Record<string, string | number>): string {
    if (!params) return t;
    return t.replace(/\{(\w+)\}/g, (_, k) => String(params[k] ?? `{${k}}`));
  }
  return {
    useTranslation: () => ({
      locale: 'zh-CN' as const,
      t: (key: string, params?: Record<string, string | number>): string => {
        const msg = lookup(zhCNMessages, key);
        return msg ? interpolate(msg, params) : key;
      },
    }),
  };
});

function extractRenderedCommands(html: string): string[] {
  return [...html.matchAll(/data-command="([^"]+)"/g)].map((match) =>
    match[1]
      .replace(/&quot;/g, '"')
      .replace(/&#x27;/g, "'")
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>'),
  );
}

describe('GuidePage command examples', () => {
  it('renders copyable commands with simple daily commands and required setup arguments', async () => {
    const { default: GuidePage } = await import('../GuidePage');
    const html = renderToStaticMarkup(<GuidePage />);
    const commands = extractRenderedCommands(html);

    expect(commands).toContain('uv tool install --editable .');
    expect(commands).toContain('ahadiff learn HEAD~1..HEAD');
    expect(commands).toContain('ahadiff learn --staged');
    expect(commands).toContain('ahadiff learn --unstaged --changed-path src/example.py');
    expect(commands).toContain('ahadiff regenerate RUN_ID --only quiz');
    expect(commands).toContain('export AHADIFF_PROVIDER_API_KEY="<your-key>"\nexport AHADIFF_PROVIDER_BASE_URL="https://api.openai.com/v1"');
    expect(commands).toContain(
      'ahadiff provider test --name gpt55 --provider-class openai_responses --base-url "$AHADIFF_PROVIDER_BASE_URL" --model gpt-5.5 --api-key-env AHADIFF_PROVIDER_API_KEY --privacy-mode explicit_remote',
    );
    expect(commands).toContain('ahadiff claims RUN_ID --force');
    expect(commands).toContain('ahadiff db restore PATH/TO/review.sqlite.bak');
    expect(commands).toContain(
      'ahadiff db import-results results.tsv --i-understand-this-is-lossy',
    );
    expect(commands).toContain('ahadiff db finalize-targeted RUN_ID');
    expect(commands).toContain('ahadiff unlock --force');
    expect(commands).toContain('ahadiff mark CLAIM_ID wrong');

    expect(commands).not.toContain('ahadiff db restore');
    expect(commands).not.toContain('ahadiff db import-results');
    expect(commands).not.toContain('ahadiff db finalize-targeted');
    expect(commands).not.toContain('ahadiff unlock');
    expect(commands).not.toContain('ahadiff mark');
    expect(commands).not.toContain('pip install ahadiff');
    expect(commands).not.toContain(
      'ahadiff learn HEAD~1..HEAD --provider gpt55 --privacy-mode explicit_remote',
    );
  });
});
