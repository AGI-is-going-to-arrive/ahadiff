import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import AppShell from '../components/AppShell';
import DiffView, { type DiffStats } from '../components/DiffView';
import BottomMiniPanel, { type MiniPanelItem } from '../components/BottomMiniPanel';
import { useTranslation } from '../i18n/useTranslation';
import { getRunArtifact } from '../api/runs';
import '../components/Diff.css';

type Phase = 'loading' | 'error' | 'empty' | 'ready';

export default function DiffViewerPage() {
  const { runId } = useParams<{ runId: string }>();
  const { t } = useTranslation();

  const [phase, setPhase] = useState<Phase>('loading');
  const [content, setContent] = useState('');
  const [stats, setStats] = useState<DiffStats | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchDiff = useCallback(() => {
    if (!runId) {
      setPhase('empty');
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPhase('loading');

    getRunArtifact(runId, 'diff', { signal: controller.signal })
      .then((envelope) => {
        if (controller.signal.aborted) return;
        const text = envelope.content ?? '';
        if (text.trim().length === 0) {
          setPhase('empty');
        } else {
          setContent(text);
          setPhase('ready');
        }
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (controller.signal.aborted) return;
        if (import.meta.env.DEV) console.error('DiffViewerPage fetch error:', err);
        setPhase('error');
      });
  }, [runId]);

  useEffect(() => {
    fetchDiff();
    return () => abortRef.current?.abort();
  }, [fetchDiff]);

  const handleStats = useCallback((s: DiffStats) => {
    setStats(s);
  }, []);

  /* Build mini-panel items from stats */
  const panelItems: MiniPanelItem[] = stats
    ? [
        { label: t('Diff.stats_files'), value: String(stats.files) },
        { label: t('Diff.stats_additions'), value: `+${stats.additions}` },
        { label: t('Diff.stats_deletions'), value: `-${stats.deletions}` },
      ]
    : [];

  return (
    <AppShell>
      <div className="diff-page">
        <div className="diff-page__header">
          <h1>{t('Diff.title')}</h1>
        </div>

        <div className="diff-page__split">
          <div className="diff-page__body">
            {phase === 'loading' && (
              <div className="diff-page__loading" role="status" aria-live="polite">
                <span className="loading-spinner" />{t('Serve.loading')}
              </div>
            )}

            {phase === 'error' && (
              <div className="diff-page__error" role="alert">
                {t('Error.fetch_failed', { resource: t('Diff.title') })}
                <button type="button" className="retry-btn" onClick={fetchDiff}>
                  {t('Error.retry')}
                </button>
              </div>
            )}

            {phase === 'empty' && (
              <div className="diff-page__empty">{t('Diff.empty')}</div>
            )}

            {phase === 'ready' && (
              <DiffView content={content} onStats={handleStats} />
            )}
          </div>

          <aside
            className="diff-page__aside"
            aria-label={t('Diff.inspector_title')}
          >
            <h2 className="diff-page__aside-title">{t('Diff.inspector_title')}</h2>
            <p className="diff-page__aside-empty">{t('Diff.inspector_empty')}</p>
          </aside>
        </div>

        {phase === 'ready' && <BottomMiniPanel items={panelItems} />}
      </div>
    </AppShell>
  );
}
