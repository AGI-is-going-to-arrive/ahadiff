/**
 * Phase 4B: Cmd/Ctrl+K command palette over `/api/search`.
 *
 * The viewer's topbar already had a placeholder search input (Phase 2C);
 * this component supplies the actual interaction. Behaviour parallels V6
 * (AhaDiff Warm v6.html L1440 + L80-82): a global keyboard shortcut opens
 * a centred modal with debounced search, keyboard-navigable result list,
 * and Esc/backdrop-click to dismiss. Backend may return 404 / network
 * error before `/api/search` ships — we degrade gracefully to "no results"
 * messaging instead of throwing, so the shortcut is always responsive.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { flushSync } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../api/client';
import { searchAll, type SearchResponse, type SearchResult } from '../api/search';
import { ValidationError } from '../api/schemas';
import { useTranslation } from '../i18n/useTranslation';
import './SearchOverlay.css';

const DEBOUNCE_MS = 200;
const MIN_QUERY = 2;
const TABLE_FILTERS = ['', 'concepts', 'cards', 'result_events', 'graph_nodes'] as const;
type TableFilter = (typeof TABLE_FILTERS)[number];
const KIND_ORDER: SearchResult['kind'][] = ['run', 'concept', 'claim', 'card'];

function restoreFocus(target: HTMLElement | null): void {
  if (!target?.isConnected) return;
  target.focus({ preventScroll: true });
}

/** Resolve a result to its in-app navigation target. */
function hrefFor(result: SearchResult): string | null {
  switch (result.kind) {
    case 'run':
      if (result.href && result.href.startsWith('#/')) return result.href;
      return `#/run/${encodeURIComponent(result.id)}/lesson`;
    case 'concept':
      if (result.href && result.href.startsWith('#/')) return result.href;
      return `#/concepts?tab=ledger&focus=${encodeURIComponent(result.focusText)}`;
    case 'claim': {
      if (result.href && result.href.startsWith('#/')) return result.href;
      // Claim id format is `{run_id}:c{n}`; navigate to the diff with the
      // claim selected via hash query parameter consumed by DiffViewerPage.
      const [runId] = result.id.split(':');
      if (!runId) return null;
      return `#/run/${encodeURIComponent(runId)}/diff?claim=${encodeURIComponent(result.id)}`;
    }
    case 'card':
      if (result.href && result.href.startsWith('#/')) return result.href;
      return `#/review?card=${encodeURIComponent(result.id)}`;
    default:
      return null;
  }
}

interface SearchOverlayProps {
  open: boolean;
  onClose: () => void;
  /**
   * Optional query string to seed the input on each open transition. When
   * provided the overlay also debounces a search immediately so the user
   * sees results without typing. Cleared on close (next open with no
   * `initialQuery` starts fresh).
   */
  initialQuery?: string;
}

export default function SearchOverlay({ open, onClose, initialQuery }: SearchOverlayProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const previewBackRef = useRef<HTMLButtonElement>(null);
  const filterRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const debounceRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [active, setActive] = useState(0);
  const [status, setStatus] = useState<'idle' | 'loading' | 'error' | 'empty' | 'ready'>(
    'idle',
  );
  const [tableFilter, setTableFilter] = useState<TableFilter>('');
  const [mobilePreview, setMobilePreview] = useState(false);

  /* Reset on open/close so the next invocation starts from a clean state. */
  useEffect(() => {
    if (!open) {
      if (debounceRef.current != null) window.clearTimeout(debounceRef.current);
      abortRef.current?.abort();
      setResults([]);
      setActive(0);
      setStatus('idle');
      setTableFilter('');
      setMobilePreview(false);
      return undefined;
    }
    setMobilePreview(false);
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    /* aria-modal=true alone does not stop tab navigation in WCAG-compliant
     * browsers; mark the rest of the page as inert while the overlay is open
     * so Tab/Shift+Tab cannot cross into the background app. */
    const previouslyInert: Array<{
      el: HTMLElement;
      had: boolean;
      value: string | null;
    }> = [];
    const inertTargets = new Set<HTMLElement>();
    const addInertTarget = (el: Element | null) => {
      if (el instanceof HTMLElement) inertTargets.add(el);
    };
    const dialog = dialogRef.current;
    const root = document.getElementById('root');
    if (dialog?.parentElement) {
      for (const child of Array.from(dialog.parentElement.children)) {
        if (child !== dialog) addInertTarget(child);
      }
    }
    if (root && dialog) {
      for (const child of Array.from(root.children)) {
        if (!child.contains(dialog)) addInertTarget(child);
      }
    }
    for (const el of inertTargets) {
      previouslyInert.push({
        el,
        had: el.hasAttribute('inert'),
        value: el.getAttribute('inert'),
      });
      el.setAttribute('inert', '');
    }
    /* requestAnimationFrame so the input renders before we focus it. */
    const handle = window.requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
    return () => {
      window.cancelAnimationFrame(handle);
      for (const { el, had, value } of previouslyInert) {
        if (had) el.setAttribute('inert', value ?? '');
        else el.removeAttribute('inert');
      }
      const restoreTarget = restoreFocusRef.current;
      restoreFocus(restoreTarget);
      window.requestAnimationFrame(() => restoreFocus(restoreTarget));
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      setQuery('');
      return;
    }
    setQuery(initialQuery ?? '');
  }, [initialQuery, open]);

  useEffect(() => {
    if (!open || !mobilePreview) return undefined;
    const handle = window.requestAnimationFrame(() => {
      previewBackRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(handle);
  }, [mobilePreview, open]);

  /* Debounced fetch when query changes. */
  useEffect(() => {
    if (!open) return undefined;
    if (debounceRef.current != null) window.clearTimeout(debounceRef.current);
    abortRef.current?.abort();
    const trimmed = query.trim();
    if (trimmed.length < MIN_QUERY) {
      setResults([]);
      setStatus('idle');
      setMobilePreview(false);
      return undefined;
    }
    setStatus('loading');
    setMobilePreview(false);
    const controller = new AbortController();
    abortRef.current = controller;
    debounceRef.current = window.setTimeout(() => {
      void searchAll(trimmed, {
        signal: controller.signal,
        limit: 20,
        tables: tableFilter || undefined,
      })
        .then((res: SearchResponse) => {
          if (controller.signal.aborted) return;
          setResults(res.results);
          setActive(0);
          setMobilePreview(false);
          setStatus(res.results.length === 0 ? 'empty' : 'ready');
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          if (err instanceof DOMException && err.name === 'AbortError') return;
          if (err instanceof ApiError && err.status === 404) {
            /* Endpoint not yet shipped — degrade gracefully to empty. */
            setResults([]);
            setMobilePreview(false);
            setStatus('empty');
            return;
          }
          if (err instanceof ValidationError) {
            setResults([]);
            setMobilePreview(false);
            setStatus('error');
            return;
          }
          setResults([]);
          setMobilePreview(false);
          setStatus('error');
        });
    }, DEBOUNCE_MS);
    return () => {
      controller.abort();
      if (debounceRef.current != null) window.clearTimeout(debounceRef.current);
    };
  }, [open, query, tableFilter]);

  const grouped = useMemo(() => {
    const map = new Map<SearchResult['kind'], SearchResult[]>();
    for (const r of results) {
      const arr = map.get(r.kind) ?? [];
      arr.push(r);
      map.set(r.kind, arr);
    }
    const rank = new Map(KIND_ORDER.map((kind, idx) => [kind, idx]));
    return Array.from(map.keys())
      .sort((a, b) => (rank.get(a) ?? KIND_ORDER.length) - (rank.get(b) ?? KIND_ORDER.length))
      .map((k) => ({ kind: k, items: map.get(k)! }));
  }, [results]);

  const flatResults = useMemo(
    () => grouped.flatMap((g) => g.items),
    [grouped],
  );

  const close = useCallback(() => {
    onClose();
  }, [onClose]);

  const commit = useCallback(
    (result: SearchResult) => {
      const href = hrefFor(result);
      if (!href) return;
      flushSync(() => close());
      if (href.startsWith('#')) {
        if (window.location.hash === href) {
          window.dispatchEvent(new Event('hashchange'));
        } else {
          window.location.hash = href.slice(1);
        }
      } else {
        navigate(href);
      }
    },
    [close, navigate],
  );

  const tableFilterOptions = useMemo(
    () => [
      { value: '', label: t('SearchOverlay.filter_all') },
      { value: 'concepts', label: t('SearchOverlay.filter_concepts') },
      { value: 'cards', label: t('SearchOverlay.filter_cards') },
      { value: 'result_events', label: t('SearchOverlay.filter_events') },
      { value: 'graph_nodes', label: t('SearchOverlay.filter_graph') },
    ] satisfies Array<{ value: TableFilter; label: string }>,
    [t],
  );

  const focusFilterAt = useCallback(
    (index: number) => {
      const next = tableFilterOptions[index];
      if (!next) return;
      setTableFilter(next.value);
      setMobilePreview(false);
      window.requestAnimationFrame(() => filterRefs.current[index]?.focus());
    },
    [tableFilterOptions],
  );

  const onFilterKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>) => {
      const current = Math.max(0, tableFilterOptions.findIndex((f) => f.value === tableFilter));
      let next = current;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
        next = (current + 1) % tableFilterOptions.length;
      } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
        next = (current - 1 + tableFilterOptions.length) % tableFilterOptions.length;
      } else if (event.key === 'Home') {
        next = 0;
      } else if (event.key === 'End') {
        next = tableFilterOptions.length - 1;
      } else {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      focusFilterAt(next);
    },
    [focusFilterAt, tableFilter, tableFilterOptions],
  );

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        if (mobilePreview) {
          setMobilePreview(false);
          inputRef.current?.focus();
          return;
        }
        close();
        return;
      }
      /* Focus trap: cycle Tab/Shift+Tab inside the dialog so keyboard users
       * cannot escape into the (inerted) background. The dialog only has the
       * input + result buttons + footer; we cycle between the first and last
       * focusable. */
      if (event.key === 'Tab' && dialogRef.current) {
        const focusables = Array.from(
          dialogRef.current.querySelectorAll<HTMLElement>(
            'button:not([disabled]):not([tabindex="-1"]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
          ),
        ).filter((el) => el.offsetParent !== null || el === document.activeElement);
        if (focusables.length === 0) return;
        const first = focusables[0]!;
        const last = focusables[focusables.length - 1]!;
        const activeEl = document.activeElement as HTMLElement | null;
        if (event.shiftKey && activeEl === first) {
          event.preventDefault();
          last.focus();
          return;
        }
        if (!event.shiftKey && activeEl === last) {
          event.preventDefault();
          first.focus();
          return;
        }
      }
      if (status !== 'ready' || flatResults.length === 0) return;
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setActive((i) => (i + 1) % flatResults.length);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        setActive((i) => (i - 1 + flatResults.length) % flatResults.length);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        const target = flatResults[active];
        if (target) commit(target);
      }
    },
    [active, close, commit, flatResults, mobilePreview, status],
  );

  const activeResult = flatResults[active] ?? null;

  const announce = useMemo(() => {
    switch (status) {
      case 'loading':
        return t('SearchOverlay.status_loading');
      case 'error':
        return t('SearchOverlay.status_error');
      case 'empty':
        return t('SearchOverlay.status_empty', { query });
      case 'ready':
        return t('SearchOverlay.status_ready', {
          count: String(flatResults.length),
        });
      default:
        return t('SearchOverlay.status_idle', { min: String(MIN_QUERY) });
    }
  }, [query, flatResults.length, status, t]);

  if (!open) return null;

  return (
    <div
      ref={dialogRef}
      className="search-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="search-overlay-label"
      onKeyDown={onKeyDown}
    >
      <button
        type="button"
        className="search-overlay__backdrop"
        aria-label={t('A11y.close')}
        tabIndex={-1}
        onClick={close}
      />
      <div
        className={`search-overlay__panel${flatResults.length > 0 ? ' search-overlay__panel--wide' : ''}`}
        data-mobile-view={mobilePreview ? 'preview' : undefined}
      >
        <header className="search-overlay__header">
          <label id="search-overlay-label" className="search-overlay__label" htmlFor="search-overlay-input">
            {t('SearchOverlay.title')}
          </label>
          <span className="search-overlay__kbd" aria-hidden="true">Esc</span>
        </header>
        <div className="search-overlay__input-row">
          <span className="search-overlay__icon" aria-hidden="true">⌕</span>
          <input
            id="search-overlay-input"
            ref={inputRef}
            type="search"
            className="search-overlay__input"
            value={query}
            placeholder={t('SearchOverlay.placeholder')}
            aria-controls="search-overlay-results"
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div
          className="search-overlay__filters"
          role="radiogroup"
          aria-label={t('SearchOverlay.filter_label')}
        >
          {tableFilterOptions.map((f, index) => (
            <button
              key={f.value || 'all'}
              ref={(el) => {
                filterRefs.current[index] = el;
              }}
              type="button"
              role="radio"
              aria-checked={tableFilter === f.value}
              tabIndex={tableFilter === f.value ? 0 : -1}
              className={`search-overlay__filter-chip${tableFilter === f.value ? ' search-overlay__filter-chip--active' : ''}`}
              onClick={() => {
                setTableFilter(f.value);
                setMobilePreview(false);
              }}
              onKeyDown={onFilterKeyDown}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="search-overlay__status" role="status" aria-live="polite">
          {announce}
        </div>
        <div className="search-overlay__body">
          <ul
            id="search-overlay-results"
            className="search-overlay__results"
            role="listbox"
            aria-label={t('SearchOverlay.results_label')}
          >
            {grouped.map((group) => {
              const kindLabel = t(`SearchOverlay.kind_${group.kind}` as never);
              return group.items.map((result, idxInGroup) => {
                const globalIdx = flatResults.indexOf(result);
                const isActive = globalIdx === active;
                const showHeader = idxInGroup === 0;
                return (
                  <li
                    key={`${result.kind}-${result.sourceTable}-${result.id}`}
                    className={`search-overlay__result${isActive ? ' search-overlay__result--active' : ''}`}
                    role="option"
                    aria-selected={isActive}
                  >
                    {showHeader && (
                      <div className="search-overlay__section-header" aria-hidden="true">
                        {kindLabel}
                      </div>
                    )}
                    <button
                      type="button"
                      className="search-overlay__result-btn"
                      onMouseEnter={() => setActive(globalIdx)}
                      onClick={() => {
                        if (window.innerWidth <= 768) {
                          setActive(globalIdx);
                          setMobilePreview(true);
                        } else {
                          commit(result);
                        }
                      }}
                    >
                      <span className={`search-overlay__chip search-overlay__chip--${result.kind}`}>
                        {kindLabel}
                      </span>
                      <span className="search-overlay__title">{result.title}</span>
                      {result.snippet ? (
                        <span className="search-overlay__snippet">{result.snippet}</span>
                      ) : null}
                    </button>
                  </li>
                );
              });
            })}
          </ul>
          <div className="search-overlay__preview-col">
            {mobilePreview && (
              <button
                ref={previewBackRef}
                type="button"
                className="search-overlay__preview-back"
                onClick={() => {
                  setMobilePreview(false);
                  inputRef.current?.focus();
                }}
              >
                ← {t('SearchOverlay.back_to_results')}
              </button>
            )}
            {activeResult ? (
              <div className="search-overlay__preview">
                <span className={`search-overlay__chip search-overlay__chip--${activeResult.kind}`}>
                  {t(`SearchOverlay.kind_${activeResult.kind}` as never)}
                </span>
                <h3 className="search-overlay__preview-title">{activeResult.title}</h3>
                <dl className="search-overlay__preview-meta">
                  <dt>{t('SearchOverlay.preview_id')}</dt>
                  <dd className="search-overlay__preview-mono">{activeResult.id}</dd>
                  {activeResult.snippet && (
                    <>
                      <dt>{t('SearchOverlay.preview_excerpt')}</dt>
                      <dd>{activeResult.snippet}</dd>
                    </>
                  )}
                </dl>
                <div className="search-overlay__preview-actions">
                  <button
                    type="button"
                    className="search-overlay__preview-btn"
                    onClick={() => commit(activeResult)}
                  >
                    {t('SearchOverlay.hint_open')} ⏎
                  </button>
                </div>
              </div>
            ) : (
              <div className="search-overlay__preview-empty">
                <span className="search-overlay__preview-empty-icon" aria-hidden="true">⌕</span>
                <p>{t('SearchOverlay.preview_empty')}</p>
              </div>
            )}
          </div>
        </div>
        <footer className="search-overlay__footer" aria-hidden="true">
          <span className="search-overlay__hint">
            <span className="search-overlay__kbd">↑</span>
            <span className="search-overlay__kbd">↓</span>
            {t('SearchOverlay.hint_navigate')}
          </span>
          <span className="search-overlay__hint">
            <span className="search-overlay__kbd">⏎</span>
            {t('SearchOverlay.hint_open')}
          </span>
        </footer>
      </div>
    </div>
  );
}
