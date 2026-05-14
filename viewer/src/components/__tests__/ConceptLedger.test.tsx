import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ConceptLedgerEntry } from '../../api/types';

const MOCK_ENTRIES: ConceptLedgerEntry[] = [
  {
    term_key: 'learn-from-diff',
    concept: 'learn-from-diff',
    display_name: 'Learn-from-diff',
    related_claims: ['c1', 'c2'],
    file_refs: ['demo.py', 'config.py'],
    source_refs: ['abc123'],
    updated_by_runs: ['run-1'],
    graphify_node_id: 'node-learn-from-diff',
  },
  {
    term_key: 'branding',
    concept: 'branding',
    display_name: 'Branding',
    related_claims: [],
    file_refs: [],
    source_refs: [],
    updated_by_runs: ['run-1', 'run-2'],
  },
];

const mockState = vi.hoisted(() => ({
  entries: [] as ConceptLedgerEntry[],
  loading: false,
  loadingMore: false,
  error: false,
  hasMore: false,
  totalCount: 0,
  runFilter: undefined as string | undefined,
  nextCursor: undefined as string | undefined,
  lastFetchedAt: 0,
  loadLedger: vi.fn(),
  loadMoreLedger: vi.fn(),
  setRunFilter: vi.fn(),
  invalidate: vi.fn(),
}));

vi.mock('../../i18n/useTranslation', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../../state/concepts-store', () => ({
  useConceptsStore: (selector: (s: typeof mockState) => unknown) => selector(mockState),
}));

describe('ConceptLedger', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.assign(mockState, {
      entries: [],
      loading: false,
      loadingMore: false,
      error: false,
      hasMore: false,
      totalCount: 0,
      runFilter: undefined,
    });
  });

  it('renders loading state', async () => {
    Object.assign(mockState, { loading: true });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger />);
    expect(html).toContain('Serve.loading');
    expect(html).toContain('loading-spinner');
  });

  it('renders error state with retry', async () => {
    Object.assign(mockState, { error: true });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger />);
    expect(html).toContain('Error.fetch_failed');
    expect(html).toContain('Error.retry');
  });

  it('renders empty state', async () => {
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger />);
    expect(html).toContain('Concept.ledger_empty');
  });

  it('renders populated table with correct columns', async () => {
    Object.assign(mockState, { entries: MOCK_ENTRIES, totalCount: 2 });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger />);
    expect(html).toContain('Concept.ledger_col_concept');
    expect(html).toContain('Concept.ledger_col_runs');
    expect(html).toContain('Concept.ledger_col_files');
    expect(html).toContain('Concept.ledger_col_claims');
    expect(html).toContain('Learn-from-diff');
    expect(html).toContain('Branding');
    expect(html).toContain('2 / 2');
  });

  it('renders run filter pill when active', async () => {
    Object.assign(mockState, { entries: MOCK_ENTRIES, totalCount: 2, runFilter: 'run-1' });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger />);
    expect(html).toContain('Concept.ledger_filter_run');
    expect(html).toContain('run-1');
    expect(html).toContain('Concept.ledger_clear_filter');
  });

  it('renders load more button when hasMore', async () => {
    Object.assign(mockState, { entries: MOCK_ENTRIES, totalCount: 10, hasMore: true });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger />);
    expect(html).toContain('Concept.ledger_load_more');
  });

  it('does not render load more when no more data', async () => {
    Object.assign(mockState, { entries: MOCK_ENTRIES, totalCount: 2, hasMore: false });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger />);
    expect(html).not.toContain('Concept.ledger_load_more');
  });

  it('truncates run chips beyond MAX_CHIPS', async () => {
    const entry: ConceptLedgerEntry = {
      ...MOCK_ENTRIES[0],
      updated_by_runs: ['r1', 'r2', 'r3', 'r4', 'r5'],
    };
    Object.assign(mockState, { entries: [entry], totalCount: 1 });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger />);
    expect(html).toContain('+2');
  });

  it('renders file refs as basename chips', async () => {
    const entry: ConceptLedgerEntry = {
      ...MOCK_ENTRIES[0],
      file_refs: ['src/core/module.py'],
    };
    Object.assign(mockState, { entries: [entry], totalCount: 1 });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger />);
    expect(html).toContain('module.py');
  });

  it('renders Windows and Unicode file refs as basename chips', async () => {
    const entry: ConceptLedgerEntry = {
      ...MOCK_ENTRIES[0],
      file_refs: ['src\\模块\\配置.py'],
    };
    Object.assign(mockState, { entries: [entry], totalCount: 1 });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger />);
    expect(html).toContain('配置.py');
    expect(html).not.toContain('src\\模块\\配置.py</span>');
  });

  it('renders graph links from real Graphify node ids when available', async () => {
    Object.assign(mockState, { entries: MOCK_ENTRIES, totalCount: 2 });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger graphifyAvailable />);
    expect(html).toContain('Concept.ledger_view_in_graph');
    expect(html).toContain('#/concepts?tab=graph&amp;focus=node-learn-from-diff');
  });

  it('encodes graph link focus values with query-special characters', async () => {
    const entry: ConceptLedgerEntry = {
      ...MOCK_ENTRIES[0],
      term_key: 'c++ & hash#query?',
      concept: 'c++ & hash#query?',
      display_name: 'C++ & hash#query?',
      graphify_node_id: 'node/c++ & hash#query?',
    };
    Object.assign(mockState, { entries: [entry], totalCount: 1 });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger graphifyAvailable />);
    expect(html).toContain(
      '#/concepts?tab=graph&amp;focus=node%2Fc%2B%2B%20%26%20hash%23query%3F',
    );
  });

  it('does not render graph links for ledger rows without a real Graphify node id', async () => {
    Object.assign(mockState, { entries: [{ ...MOCK_ENTRIES[0], graphify_node_id: null }], totalCount: 1 });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger graphifyAvailable />);
    expect(html).not.toContain('Concept.ledger_view_in_graph');
  });

  it('does not render graph links when Graphify is unavailable', async () => {
    Object.assign(mockState, { entries: MOCK_ENTRIES, totalCount: 2 });
    const { default: ConceptLedger } = await import('../ConceptLedger');
    const html = renderToStaticMarkup(<ConceptLedger graphifyAvailable={false} />);
    expect(html).not.toContain('Concept.ledger_view_in_graph');
  });

  it('wires focus concepts to smooth scroll and row highlight', () => {
    const src = readFileSync(resolve(__dirname, '../ConceptLedger.tsx'), 'utf-8');
    expect(src).toMatch(/focusConcept/);
    expect(src).toMatch(/conceptMatchesFocus\(entry, focusConcept\)/);
    expect(src).toMatch(/behavior: shouldUseSmoothScroll\(\) \? 'smooth' : 'auto'/);
    expect(src).toMatch(/row\.focus\(\{ preventScroll: true \}\)/);
    expect(src).toMatch(/aria-current=\{focusedTermKey === entry\.term_key \? 'true' : undefined\}/);
    expect(src).toContain('concept-ledger__row--focused');
  });

  it('matches focus by exact, display, term key, and normalized containment', async () => {
    const { conceptMatchesFocus } = await import('../ConceptLedger');
    expect(conceptMatchesFocus(MOCK_ENTRIES[1], 'Branding')).toBe(true);
    expect(conceptMatchesFocus(MOCK_ENTRIES[1], 'branding')).toBe(true);
    expect(conceptMatchesFocus(MOCK_ENTRIES[0], 'learn-from-diff evidence')).toBe(true);
    expect(conceptMatchesFocus(MOCK_ENTRIES[0], 'missing')).toBe(false);
  });
});
