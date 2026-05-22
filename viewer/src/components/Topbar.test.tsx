import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import Topbar, { docsUrlForLocale } from './Topbar';

let learnPhase = 'idle';
const submitLearn = vi.fn();

vi.mock('../state/learn-store', () => ({
  useLearnStore: (selector: (state: { phase: string; submitLearn: typeof submitLearn }) => unknown) =>
    selector({ phase: learnPhase, submitLearn }),
}));

describe('Topbar', () => {
  beforeEach(() => {
    learnPhase = 'idle';
    submitLearn.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('uses the busy label as the accessible name while a learn run is active', () => {
    learnPhase = 'running';

    const html = renderToStaticMarkup(
      <MemoryRouter>
        <Topbar isMenuOpen={false} onMenuToggle={() => undefined} />
      </MemoryRouter>,
    );

    expect(html).toContain('aria-label="Running');
    expect(html).not.toContain('aria-label="Start a new learn run"');
  });

  it('disables the busy pulse animation for reduced-motion users', () => {
    const css = readFileSync(resolve(__dirname, 'Topbar.css'), 'utf-8');
    const reducedMotionBlock = css.match(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[\s\S]*?\n\}/);

    expect(reducedMotionBlock?.[0]).toContain('.topbar__btn--busy');
    expect(reducedMotionBlock?.[0]).toContain('animation: none');
  });

  it.each([
    ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', '⌘K'],
    ['Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Ctrl+K'],
    ['Mozilla/5.0 (X11; Linux x86_64)', 'Ctrl+K'],
  ])('renders platform shortcut for %s', (userAgent, expectedShortcut) => {
    vi.stubGlobal('navigator', { userAgent });

    const html = renderToStaticMarkup(
      <MemoryRouter>
        <Topbar isMenuOpen={false} onMenuToggle={() => undefined} onSearchOpen={() => undefined} />
      </MemoryRouter>,
    );

    expect(html).toContain(`<kbd>${expectedShortcut}</kbd>`);
  });

  it('uses the canonical AGI-is-going-to-arrive docs URL at the default locale', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <Topbar isMenuOpen={false} onMenuToggle={() => undefined} />
      </MemoryRouter>,
    );

    // SSR initial-state snapshot — default locale resolves to 'en', so the
    // English #readme anchor must render. The legacy lowercased org name must
    // never reappear in the rendered tree.
    expect(html).toContain('href="https://github.com/AGI-is-going-to-arrive/ahadiff#readme"');
    expect(html).not.toContain('agi-is-coming');
  });

  it('selects the localized docs URL through the helper in the source', () => {
    // Zustand 5.x routes useSyncExternalStore through getInitialState() during
    // SSR (renderToStaticMarkup), so runtime locale switches do not flow into
    // the rendered output without a DOM. Pin the locale-aware URL contract via
    // the source so the legacy org name cannot regress and both branches stay
    // exercised.
    const src = readFileSync(resolve(__dirname, 'Topbar.tsx'), 'utf-8');

    expect(src).toContain("docsUrlForLocale(locale)");
    expect(src).toContain('https://github.com/AGI-is-going-to-arrive/ahadiff');
    expect(src).toContain('/blob/main/README.zh.md');
    expect(src).toContain('#readme');
    expect(src).not.toContain('agi-is-coming');
  });

  it('keeps docs URL selection tolerant of future string variants and null locale', () => {
    expect(docsUrlForLocale('zh-Hant')).toBe(
      'https://github.com/AGI-is-going-to-arrive/ahadiff/blob/main/README.zh.md',
    );
    expect(docsUrlForLocale('en-AU')).toBe(
      'https://github.com/AGI-is-going-to-arrive/ahadiff#readme',
    );
    expect(docsUrlForLocale(null)).toBe(
      'https://github.com/AGI-is-going-to-arrive/ahadiff#readme',
    );
  });
});
