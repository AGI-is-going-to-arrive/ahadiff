import { useCallback, useEffect, useRef, useState } from 'react';
import { getGlobalConcepts } from '../api/runs';
import type { GraphifyMode } from '../api/types';
import AppShell from '../components/AppShell';
import ConceptGraph from '../components/ConceptGraph';
import type { Concept } from '../components/ConceptGraph';
import { useTranslation } from '../i18n/useTranslation';
import '../components/Concepts.css';

/* ---------- Type-safe array hardening ---------- */

function toStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const out = value.filter((v): v is string => typeof v === 'string');
  return out.length > 0 ? out : undefined;
}

/* ---------- JSONL parser ---------- */

function parseConceptsJsonl(raw: string): Concept[] {
  const results: Concept[] = [];
  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const obj: Record<string, unknown> = JSON.parse(trimmed);
      results.push({
        concept: typeof obj.concept === 'string' ? obj.concept : '',
        term_key: typeof obj.term_key === 'string' ? obj.term_key : '',
        display_name:
          typeof obj.display_name === 'string'
            ? obj.display_name
            : typeof obj.term === 'string'
              ? obj.term
              : typeof obj.concept === 'string'
                ? obj.concept
                : '',
        surface: typeof obj.surface === 'string' ? obj.surface : undefined,
        related_claims: toStringArray(obj.related_claims),
        file_refs: toStringArray(obj.file_refs),
        aliases: toStringArray(obj.aliases),
      });
    } catch {
      /* skip malformed lines */
    }
  }
  return results;
}

/* ---------- Mode inference ---------- */

function inferMode(concepts: Concept[]): GraphifyMode {
  if (concepts.length === 0) return 'empty';
  const hasEdges = concepts.some((c) => c.related_claims && c.related_claims.length > 0);
  return hasEdges ? 'full' : 'learning_only';
}

/* ---------- Page component ---------- */

type ErrorFlag = 'fetch_failed' | string | null;

export default function ConceptsPage() {
  const { t } = useTranslation();
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [mode, setMode] = useState<GraphifyMode>('empty');
  const [loading, setLoading] = useState(true);
  // Raw error flag (or runtime Error.message); i18n string computed at render time
  const [errorFlag, setErrorFlag] = useState<ErrorFlag>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchConcepts = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setErrorFlag(null);
    try {
      const data = await getGlobalConcepts({}, { signal: controller.signal });
      if (controller.signal.aborted) return;
      const parsed = parseConceptsJsonl(data.content ?? '');
      setConcepts(parsed);
      setMode(inferMode(parsed));
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (controller.signal.aborted) return;
      // Store raw error info; localized message rendered below
      setErrorFlag(err instanceof Error ? err.message : 'fetch_failed');
      setConcepts([]);
      setMode('empty');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  // Fetch concepts. AbortController ensures in-flight requests are cancelled
  // on unmount or rapid remounts.
  useEffect(() => {
    void fetchConcepts();
    return () => abortRef.current?.abort();
  }, [fetchConcepts]);

  // Always use localized error — never render raw Error.message to DOM
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
          <button type="button" className="retry-btn" onClick={() => void fetchConcepts()}>
            {t('Error.retry')}
          </button>
        </div>
      )}

      {!loading && !errorMessage && <ConceptGraph concepts={concepts} mode={mode} />}
    </AppShell>
  );
}
