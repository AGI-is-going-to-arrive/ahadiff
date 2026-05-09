import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { fetchGraphConcepts } from '../api/graph';
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

type ErrorFlag = 'fetch_failed' | string | null;

export default function ConceptsPage() {
  const { t } = useTranslation();
  const hashParams = parseHashParams();
  const initialTab: ConceptsTab =
    hashParams.tab === 'graph' ? 'graph' : 'ledger';
  const [activeTab, setActiveTab] = useState<ConceptsTab>(initialTab);

  const [graphData, setGraphData] = useState<ConceptGraphResponse | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState<ErrorFlag>(null);
  const [showAll, setShowAll] = useState(false);
  const [focusNodeId, setFocusNodeId] = useState<string | null>(
    () => hashParams.focus ?? null,
  );
  const [runFilter] = useState<string | undefined>(hashParams.run);
  const abortRef = useRef<AbortController | null>(null);

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
    const syncFocus = () => {
      const params = parseHashParams();
      setFocusNodeId(params.focus ?? null);
    };
    window.addEventListener('hashchange', syncFocus);
    return () => window.removeEventListener('hashchange', syncFocus);
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
      setActiveTab(CONCEPTS_TABS[next]);
      document.getElementById(TAB_IDS[CONCEPTS_TABS[next]])?.focus();
    },
    [activeTab],
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
            onClick={() => setActiveTab(tab)}
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
        {activeTab === 'ledger' && <ConceptLedger runFilter={runFilter} />}
      </section>

      <section
        id={TAB_PANEL_IDS.graph}
        role="tabpanel"
        aria-labelledby={TAB_IDS.graph}
        hidden={activeTab !== 'graph'}
      >
        {activeTab === 'graph' && (
          <>
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
