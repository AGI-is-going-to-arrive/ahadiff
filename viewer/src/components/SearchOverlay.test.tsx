/**
 * SearchOverlay unit tests.
 *
 * The viewer suite uses `renderToStaticMarkup` exclusively (no jsdom,
 * no @testing-library/react). Inside SSR, React's `useEffect` does not
 * fire and event handlers (onKeyDown, onClick) cannot be exercised
 * directly. We follow the OnboardingPage pattern:
 *
 *   1. Mock `react.useState` so each test can inject controlled initial
 *      values for the six SearchOverlay states (in declaration order:
 *      query, results, active, status, tableFilter, mobilePreview).
 *   2. For behaviours that only live inside event handlers / effects
 *      (escape closes, arrows cycle, enter commits, search invocation),
 *      verify the wiring via static markup attributes + source-level
 *      assertions against `SearchOverlay.tsx`.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { SearchResult } from '../api/search';

/* ---------- React useState injection ---------- */

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
      const value = (idx < stateOverrides.length
        ? (stateOverrides[idx] as S)
        : init);
      const setter = (() => undefined) as unknown as (v: S) => void;
      return [value, setter] as [S, (v: S) => void];
    },
  };
});

/* ---------- Mock dependencies ---------- */

const searchAllMock = vi.fn();

vi.mock('../api/search', async () => {
  const actual = await vi.importActual<typeof import('../api/search')>(
    '../api/search',
  );
  return {
    ...actual,
    searchAll: (...args: unknown[]) => searchAllMock(...args),
  };
});

const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('../i18n/useTranslation', () => ({
  useTranslation: () => ({
    locale: 'en' as const,
    t: (key: string, params?: Record<string, string | number>): string => {
      if (!params) return key;
      // Echo back interpolated params so tests can assert on them.
      return Object.entries(params).reduce(
        (acc, [k, v]) => acc.replace(`{${k}}`, String(v)),
        key,
      );
    },
  }),
}));

/* ---------- Helpers ---------- */

/** SearchOverlay's useState calls, in declaration order. */
interface OverlayStates {
  query?: string;
  results?: SearchResult[];
  active?: number;
  status?: 'idle' | 'loading' | 'error' | 'empty' | 'ready';
  tableFilter?: '' | 'concepts' | 'cards' | 'result_events' | 'graph_nodes';
  mobilePreview?: boolean;
}

function setStates(opts: OverlayStates = {}) {
  stateOverrides.length = 0;
  stateOverrides.push(opts.query ?? '');
  stateOverrides.push(opts.results ?? []);
  stateOverrides.push(opts.active ?? 0);
  stateOverrides.push(opts.status ?? 'idle');
  stateOverrides.push(opts.tableFilter ?? '');
  stateOverrides.push(opts.mobilePreview ?? false);
}

function makeResult(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    kind: 'concept',
    sourceTable: 'graph_nodes',
    id: 'c-1',
    focusText: 'sample concept',
    title: 'sample concept',
    snippet: 'a snippet',
    rank: 1,
    href: null,
    ...overrides,
  };
}

async function renderOverlay(props: {
  open: boolean;
  initialQuery?: string;
}): Promise<string> {
  stateCallCounter = 0;
  const { default: SearchOverlay } = await import('./SearchOverlay');
  return renderToStaticMarkup(
    <SearchOverlay
      open={props.open}
      onClose={() => undefined}
      initialQuery={props.initialQuery}
    />,
  );
}

/* ---------- Lifecycle ---------- */

beforeEach(() => {
  vi.clearAllMocks();
  stateOverrides.length = 0;
  stateCallCounter = 0;
});

afterEach(() => {
  stateOverrides.length = 0;
  stateCallCounter = 0;
});

/* ---------- Tests ---------- */

describe('SearchOverlay', () => {
  it('renders nothing when open=false', async () => {
    setStates();
    const html = await renderOverlay({ open: false });
    expect(html).toBe('');
  });

  it('renders the dialog with an autofocus-ready input when open=true', async () => {
    setStates();
    const html = await renderOverlay({ open: true });
    // role="dialog" with aria-modal and a labelled search input.
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('id="search-overlay-input"');
    expect(html).toContain('SearchOverlay.placeholder');
    // The input is focused asynchronously via requestAnimationFrame inside
    // the open effect (SearchOverlay.tsx). useEffect does not fire under
    // SSR, so we assert the focus wiring is present in source.
    const src = readFileSync(
      resolve(__dirname, 'SearchOverlay.tsx'),
      'utf-8',
    );
    expect(src).toMatch(/inputRef\.current\?\.focus\(\)/);
  });

  it('invokes onClose via Escape and backdrop wiring', async () => {
    setStates();
    const html = await renderOverlay({ open: true });
    // Backdrop button has aria-label A11y.close and calls onClose onClick.
    expect(html).toContain('search-overlay__backdrop');
    expect(html).toContain('aria-label="A11y.close"');
    // Escape handling lives inside onKeyDown. Confirm it's bound to the
    // dialog root and that the branch exists.
    expect(html).toMatch(/class="search-overlay"[^>]*role="dialog"/);
    const src = readFileSync(
      resolve(__dirname, 'SearchOverlay.tsx'),
      'utf-8',
    );
    expect(src).toMatch(/event\.key === 'Escape'[\s\S]*mobilePreview[\s\S]*close\(\)/);
  });

  it('debounces search by deferring searchAll until the user has typed', async () => {
    // useEffect does not fire in SSR, so we assert the debounce contract
    // (DEBOUNCE_MS + MIN_QUERY) plus the searchAll call site. With the
    // default empty query, searchAll should never be invoked even after
    // render.
    setStates({ query: '', status: 'idle' });
    await renderOverlay({ open: true });
    expect(searchAllMock).not.toHaveBeenCalled();

    const src = readFileSync(
      resolve(__dirname, 'SearchOverlay.tsx'),
      'utf-8',
    );
    expect(src).toContain('const DEBOUNCE_MS = 200');
    expect(src).toContain('const MIN_QUERY = 2');
    // Search effect goes through window.setTimeout with the debounce.
    expect(src).toMatch(/window\.setTimeout\([\s\S]*searchAll\(trimmed/);
    // Trimmed length gate prevents short / blank queries from hitting the API.
    expect(src).toMatch(/trimmed\.length < MIN_QUERY/);
  });

  it('cycles the active result with ArrowDown/ArrowUp on the dialog', async () => {
    const results: SearchResult[] = [
      makeResult({ kind: 'run', id: 'run-1', title: 'Run one' }),
      makeResult({ kind: 'concept', id: 'c-2', title: 'Concept two' }),
      makeResult({ kind: 'claim', id: 'run-1:c1', title: 'Claim three' }),
    ];
    // Inject active=1 so we can confirm aria-selected tracks the active idx.
    setStates({ results, status: 'ready', active: 1 });
    const html = await renderOverlay({ open: true });
    // Exactly one option is aria-selected, and it matches the active index.
    const selectedMatches = html.match(/aria-selected="true"/g) ?? [];
    expect(selectedMatches.length).toBe(1);
    expect(html).toContain('Concept two');
    // ArrowDown/ArrowUp branches and modular cycling live inside onKeyDown.
    const src = readFileSync(
      resolve(__dirname, 'SearchOverlay.tsx'),
      'utf-8',
    );
    expect(src).toMatch(/event\.key === 'ArrowDown'[\s\S]{0,120}flatResults\.length/);
    expect(src).toMatch(/event\.key === 'ArrowUp'[\s\S]{0,160}flatResults\.length/);
  });

  it('commits the active result on Enter via navigate + onClose', async () => {
    const results: SearchResult[] = [
      makeResult({ kind: 'concept', id: 'c-9', title: 'Pick me' }),
    ];
    setStates({ results, status: 'ready', active: 0 });
    const html = await renderOverlay({ open: true });
    // Preview pane exposes the Enter affordance (`SearchOverlay.hint_open ⏎`).
    expect(html).toContain('SearchOverlay.hint_open');
    expect(html).toContain('⏎');
    expect(html).toContain('Pick me');
    // Enter branch lives inside onKeyDown -> commit() -> navigate().
    const src = readFileSync(
      resolve(__dirname, 'SearchOverlay.tsx'),
      'utf-8',
    );
    expect(src).toMatch(/event\.key === 'Enter'[\s\S]{0,160}commit\(target\)/);
    expect(src).toMatch(/const close = useCallback\([\s\S]{0,120}flushSync\(\(\) => onClose\(\)\)/);
    expect(src).toMatch(/const commit = useCallback\([\s\S]{0,220}close\(\)/);
    expect(src).toMatch(/window\.location\.hash === href/);
    expect(src).toMatch(/window\.dispatchEvent\(new Event\('hashchange'\)\)/);
    expect(src).toMatch(/window\.location\.hash = href\.slice\(1\)/);
  });

  it('routes every concept result to ledger focus links', async () => {
    const src = readFileSync(
      resolve(__dirname, 'SearchOverlay.tsx'),
      'utf-8',
    );

    expect(src).not.toMatch(/result\.sourceTable !== 'graph_nodes'/);
    expect(src).toMatch(/case 'concept':[\s\S]{0,120}result\.href && result\.href\.startsWith\('#\/'\)/);
    expect(src).toMatch(
      /#\/concepts\?tab=ledger&focus=\$\{encodeURIComponent\(result\.focusText\)\}/,
    );
    expect(src).not.toMatch(/#\/concepts\?focus=\$\{encodeURIComponent\(result\.id\)\}/);
  });

  it('renders the filter chip group with the active filter checked', async () => {
    setStates({ tableFilter: 'concepts' });
    const html = await renderOverlay({ open: true });
    // radiogroup wrapper with translated label.
    expect(html).toContain('role="radiogroup"');
    expect(html).toContain('aria-label="SearchOverlay.filter_label"');
    // Five chips rendered (All, Concepts, Cards, Events, Graph) — each as a
    // <button role="radio"> with aria-checked.
    const radios = html.match(/role="radio"/g) ?? [];
    expect(radios.length).toBe(5);
    // Exactly one chip is aria-checked="true" and it is the concepts chip.
    const checked = html.match(/aria-checked="true"/g) ?? [];
    expect(checked.length).toBe(1);
    expect(html).toMatch(
      /aria-checked="true"[^>]*tabindex="0"[^>]*search-overlay__filter-chip--active[^>]*>SearchOverlay\.filter_concepts/,
    );
  });

  it('groups results by kind (run → concept → claim → card) with a section header per group', async () => {
    const results: SearchResult[] = [
      makeResult({ kind: 'card', id: 'card-1', title: 'card one' }),
      makeResult({ kind: 'run', id: 'run-1', title: 'run one' }),
      makeResult({ kind: 'concept', id: 'c-1', title: 'concept one' }),
      makeResult({ kind: 'claim', id: 'run-1:c1', title: 'claim one' }),
      makeResult({ kind: 'concept', id: 'c-2', title: 'concept two' }),
    ];
    setStates({ results, status: 'ready' });
    const html = await renderOverlay({ open: true });

    // One header per distinct kind (4 kinds → 4 section headers, even though
    // there are 5 results because the second concept reuses the concept group).
    const headerMatches = html.match(/search-overlay__section-header/g) ?? [];
    expect(headerMatches.length).toBe(4);

    // Section header labels are localised via `SearchOverlay.kind_*` keys.
    expect(html).toContain('SearchOverlay.kind_run');
    expect(html).toContain('SearchOverlay.kind_concept');
    expect(html).toContain('SearchOverlay.kind_claim');
    expect(html).toContain('SearchOverlay.kind_card');

    // Order is the KIND_ORDER constant (run → concept → claim → card).
    const order = ['kind_run', 'kind_concept', 'kind_claim', 'kind_card'].map(
      (k) => html.indexOf(`SearchOverlay.${k}`),
    );
    expect(order.every((idx) => idx >= 0)).toBe(true);
    expect(order).toEqual([...order].sort((a, b) => a - b));

    // All five result titles render in the list.
    for (const r of results) {
      expect(html).toContain(r.title);
    }
  });

  it('renders the mobile preview back affordance only in preview mode', async () => {
    const results: SearchResult[] = [
      makeResult({ kind: 'concept', id: 'c-9', title: 'Mobile pick' }),
    ];
    setStates({ results, status: 'ready', active: 0, mobilePreview: true });
    const html = await renderOverlay({ open: true });

    expect(html).toContain('data-mobile-view="preview"');
    expect(html).toContain('SearchOverlay.back_to_results');

    const src = readFileSync(
      resolve(__dirname, 'SearchOverlay.tsx'),
      'utf-8',
    );
    expect(src).toMatch(/setMobilePreview\(false\)[\s\S]*inputRef\.current\?\.focus\(\)/);
    expect(src).toMatch(/previewBackRef\.current\?\.focus\(\)/);
  });
});
