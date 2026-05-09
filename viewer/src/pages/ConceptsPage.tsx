import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { fetchGraphConcepts, refreshGraph } from '../api/graph';
import type { ConceptGraphResponse } from '../api/types';
import AppShell from '../components/AppShell';
import ConceptGraph from '../components/ConceptGraph';
import ConceptLedger from '../components/ConceptLedger';
import { useTranslation } from '../i18n/useTranslation';
import '../components/Concepts.css';

type ConceptsTab = 'ledger' | 'graph';
const CONCEPTS_TABS: ConceptsTab[] = ['ledger', 'graph'];
const TAB_LABEL_KEYS: Record<ConceptsTab, string> = {
  ledger: 'Concept.tab_ledger',
  graph: 'Concept.tab_graph',
};
const TAB_IDS: Record<ConceptsTab, string> = {
  ledger: 'concepts-tab-ledger',
  graph: 'concepts-tab-graph',
};
const TAB_PANEL_IDS: Record<ConceptsTab, string> = {
  ledger: 'concepts-panel-ledger',
  graph: 'concepts-panel-graph',
};

function parseHashParams(): { tab?: string; focus?: string; run?: string } {
  const query = window.location.hash.split('?')[1] ?? '';
  const params = new URLSearchParams(query);
  return {
    tab: params.get('tab') ?? undefined,
    focus: params.get('focus') ?? undefined,
    run: params.get('run') ?? undefined,
  };
}

function writeHashParams(
  currentTab: ConceptsTab,
  next: { tab?: ConceptsTab; focus?: string | null; run?: string | null },
) {
  const [hashPath, rawQuery = ''] = window.location.hash.split('?');
  const params = new URLSearchParams(rawQuery);
  params.set('tab', next.tab ?? currentTab);
  if ('focus' in next) {
    if (next.focus) params.set('focus', next.focus);
    else params.delete('focus');
  }
  if ('run' in next) {
    if (next.run) params.set('run', next.run);
    else params.delete('run');
  }
  const query = params.toString();
  const nextHash = `${hashPath || '#/concepts'}${query ? `?${query}` : ''}`;
  window.history.replaceState(
    null,
    '',
    `${window.location.pathname}${window.location.search}${nextHash}`,
  );
}

type ErrorFlag = 'fetch_failed' | string | null;

export default function ConceptsPage() {
  const { t } = useTranslation();
  const hashParams = parseHashParams();
  const initialTab: ConceptsTab =
    hashParams.tab === 'graph' || hashParams.focus ? 'graph' : 'ledger';
  const [activeTab, setActiveTab] = useState<ConceptsTab>(initialTab);

  const [graphData, setGraphData] = useState<ConceptGraphResponse | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState<ErrorFlag>(null);
  const [showAll, setShowAll] = useState(false);
  const [focusNodeId, setFocusNodeId] = useState<string | null>(
    () => hashParams.focus ?? null,
  );
  const [runFilter, setRunFilter] = useState<string | undefined>(hashParams.run);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<{
    kind: 'success' | 'error';
    text: string;
  } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const refreshAbortRef = useRef<AbortController | null>(null);

  const fetchGraphData = useCallback(async (all = false) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setGraphLoading(true);
    setGraphError(null);
    try {
      const params = all ? { limit: 2000 } : {};
      const data = await fetchGraphConcepts(params, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setGraphData(data);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (controller.signal.aborted) return;
      setGraphError(err instanceof Error ? err.message : 'fetch_failed');
      setGraphData(null);
    } finally {
      if (!controller.signal.aborted) setGraphLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'graph') {
      void fetchGraphData(showAll);
    }
    return () => abortRef.current?.abort();
  }, [activeTab, fetchGraphData, showAll]);

  useEffect(() => {
    const syncHashState = () => {
      const params = parseHashParams();
      setActiveTab(params.tab === 'graph' || params.focus ? 'graph' : 'ledger');
      setFocusNodeId(params.focus ?? null);
      setRunFilter(params.run);
    };
    window.addEventListener('hashchange', syncHashState);
    return () => window.removeEventListener('hashchange', syncHashState);
  }, []);

  useEffect(() => {
    if (!focusNodeId || !graphData?.truncated || showAll) return;
    const visible = graphData.nodes.some(
      (node) => node.id === focusNodeId || node.name === focusNodeId,
    );
    if (!visible) setShowAll(true);
  }, [focusNodeId, graphData, showAll]);

  const handleShowAll = useCallback(() => {
    setShowAll(true);
  }, []);

  const handleRefreshGraph = useCallback(async () => {
    refreshAbortRef.current?.abort();
    const controller = new AbortController();
    refreshAbortRef.current = controller;
    setRefreshing(true);
    setRefreshMessage(null);
    try {
      const result = await refreshGraph({ signal: controller.signal });
      if (controller.signal.aborted) return;
      setRefreshMessage({
        kind: 'success',
        text: t('Concept.refresh_success', {
          nodes: result.nodes,
          edges: result.edges,
        }),
      });
      await fetchGraphData(showAll);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (controller.signal.aborted) return;
      setRefreshMessage({ kind: 'error', text: t('Concept.refresh_failed') });
    } finally {
      if (!controller.signal.aborted) setRefreshing(false);
    }
  }, [fetchGraphData, showAll, t]);

  useEffect(() => () => refreshAbortRef.current?.abort(), []);

  const activateTab = useCallback((tab: ConceptsTab) => {
    setActiveTab(tab);
    writeHashParams(activeTab, { tab, focus: tab === 'ledger' ? null : undefined });
  }, [activeTab]);

  const handleRunFilterChange = useCallback((run: string | undefined) => {
    setRunFilter(run);
    writeHashParams(activeTab, { run: run ?? null });
  }, [activeTab]);

  const handleTabKeyDown = useCallback(
    (e: KeyboardEvent<HTMLButtonElement>) => {
      const idx = CONCEPTS_TABS.indexOf(activeTab);
      let next = idx;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        next = (idx + 1) % CONCEPTS_TABS.length;
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        next = (idx - 1 + CONCEPTS_TABS.length) % CONCEPTS_TABS.length;
      } else if (e.key === 'Home') {
        next = 0;
      } else if (e.key === 'End') {
        next = CONCEPTS_TABS.length - 1;
      } else {
        return;
      }
      e.preventDefault();
      activateTab(CONCEPTS_TABS[next]);
      document.getElementById(TAB_IDS[CONCEPTS_TABS[next]])?.focus();
    },
    [activeTab, activateTab],
  );

  const graphErrorMessage =
    graphError === null
      ? null
      : t('Error.fetch_failed', { resource: t('Shell.concept_graph') });

  return (
    <AppShell>
      <header className="concepts-page__header">
        <h1 className="concepts-page__title">{t('Concept.title')}</h1>
      </header>

      <div className="concepts-page__tabs" role="tablist" aria-label={t('Concept.title')}>
        {CONCEPTS_TABS.map((tab) => (
          <button
            key={tab}
            id={TAB_IDS[tab]}
            role="tab"
            type="button"
            className={`concepts-page__tab${activeTab === tab ? ' concepts-page__tab--active' : ''}`}
            aria-selected={activeTab === tab}
            aria-controls={TAB_PANEL_IDS[tab]}
            tabIndex={activeTab === tab ? 0 : -1}
            onClick={() => activateTab(tab)}
            onKeyDown={handleTabKeyDown}
          >
            {t(TAB_LABEL_KEYS[tab])}
          </button>
        ))}
      </div>

      <section
        id={TAB_PANEL_IDS.ledger}
        role="tabpanel"
        aria-labelledby={TAB_IDS.ledger}
        hidden={activeTab !== 'ledger'}
      >
        {activeTab === 'ledger' && (
          <ConceptLedger runFilter={runFilter} onRunFilterChange={handleRunFilterChange} />
        )}
      </section>

      <section
        id={TAB_PANEL_IDS.graph}
        role="tabpanel"
        aria-labelledby={TAB_IDS.graph}
        hidden={activeTab !== 'graph'}
      >
        {activeTab === 'graph' && (
          <>
            <div className="concepts-page__graph-toolbar">
              <button
                type="button"
                className="concepts-page__refresh-btn"
                onClick={() => void handleRefreshGraph()}
                disabled={refreshing}
                aria-busy={refreshing}
              >
                {refreshing && <span className="loading-spinner" aria-hidden="true" />}
                {t('Concept.refresh_graph')}
              </button>
              {refreshMessage && (
                <span
                  role={refreshMessage.kind === 'error' ? 'alert' : 'status'}
                  aria-live="polite"
                  className={`concepts-page__refresh-msg concepts-page__refresh-msg--${refreshMessage.kind}`}
                >
                  {refreshMessage.text}
                </span>
              )}
            </div>

            {graphLoading && (
              <div role="status" aria-live="polite" className="concepts-page__loading">
                <span className="loading-spinner" />
                {t('Serve.loading')}
              </div>
            )}

            {graphErrorMessage && (
              <div role="alert" className="concepts-page__error">
                {graphErrorMessage}
                <button
                  type="button"
                  className="retry-btn"
                  onClick={() => void fetchGraphData(showAll)}
                >
                  {t('Error.retry')}
                </button>
              </div>
            )}

            {!graphLoading && !graphErrorMessage && graphData && (
              <ConceptGraph
                nodes={graphData.nodes}
                edges={graphData.edges}
                status={graphData.status}
                truncated={graphData.truncated}
                focusNodeId={focusNodeId}
                onShowAll={graphData.truncated && !showAll ? handleShowAll : undefined}
              />
            )}

            {!graphLoading && !graphErrorMessage && !graphData && (
              <ConceptGraph
                nodes={[]}
                edges={[]}
                status={{
                  enabled: false,
                  source_exists: false,
                  has_graph: false,
                  freshness: null,
                  node_count: 0,
                  edge_count: 0,
                  source_path: null,
                  provenance: null,
                }}
                truncated={false}
              />
            )}
          </>
        )}
      </section>
    </AppShell>
  );
}
