import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchGraphConcepts } from '../api/graph';
import type { ConceptGraphResponse } from '../api/types';
import AppShell from '../components/AppShell';
import ConceptGraph from '../components/ConceptGraph';
import { useTranslation } from '../i18n/useTranslation';
import '../components/Concepts.css';

type ErrorFlag = 'fetch_failed' | string | null;

export default function ConceptsPage() {
  const { t } = useTranslation();
  const [graphData, setGraphData] = useState<ConceptGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorFlag, setErrorFlag] = useState<ErrorFlag>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchData = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setErrorFlag(null);
    try {
      const data = await fetchGraphConcepts({}, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setGraphData(data);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (controller.signal.aborted) return;
      setErrorFlag(err instanceof Error ? err.message : 'fetch_failed');
      setGraphData(null);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
    return () => abortRef.current?.abort();
  }, [fetchData]);

  const errorMessage =
    errorFlag === null
      ? null
      : t('Error.fetch_failed', { resource: t('Shell.concept_graph') });

  return (
    <AppShell>
      <header className="concepts-page__header">
        <h1 className="concepts-page__title">{t('Concept.title')}</h1>
      </header>

      {loading && (
        <div role="status" aria-live="polite" className="concepts-page__loading">
          <span className="loading-spinner" />{t('Serve.loading')}
        </div>
      )}

      {errorMessage && (
        <div role="alert" className="concepts-page__error">
          {errorMessage}
          <button type="button" className="retry-btn" onClick={() => void fetchData()}>
            {t('Error.retry')}
          </button>
        </div>
      )}

      {!loading && !errorMessage && graphData && (
        <ConceptGraph
          nodes={graphData.nodes}
          edges={graphData.edges}
          status={graphData.status}
          truncated={graphData.truncated}
        />
      )}

      {!loading && !errorMessage && !graphData && (
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
    </AppShell>
  );
}
