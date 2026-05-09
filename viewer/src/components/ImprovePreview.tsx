import { useCallback, useEffect, useState } from 'react';
import { getImprovePreflight } from '../api/improve';
import type { ImprovePreflightResponse } from '../api/types';
import { useTranslation } from '../i18n/useTranslation';
import './ImprovePreview.css';

export default function ImprovePreview() {
  const { t } = useTranslation();
  const [data, setData] = useState<ImprovePreflightResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchPreflight = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const result = await getImprovePreflight();
      setData(result);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchPreflight();
  }, [fetchPreflight]);

  if (loading) {
    return (
      <div role="status" aria-live="polite" className="improve-preview__loading">
        <span className="loading-spinner" />
        {t('Serve.loading')}
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert" className="improve-preview__error">
        {t('Error.fetch_failed', { resource: t('Improve.heading') })}
        <button type="button" className="retry-btn" onClick={() => void fetchPreflight()}>
          {t('Error.retry')}
        </button>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="improve-preview">
      <div className="improve-preview__banner" role="status" aria-live="polite">
        {t('Improve.read_only_banner')}
      </div>

      {!data.available && (
        <div className="improve-preview__unavailable">
          <p>{t(`Improve.unavailable_${data.reason ?? 'unknown'}`)}</p>
        </div>
      )}

      {data.available && (
        <>
          <section className="improve-preview__section">
            <h3 className="improve-preview__section-title">{t('Improve.section_plan')}</h3>
            <dl className="improve-preview__dl">
              {data.anchor_run && (
                <div className="improve-preview__dl-row">
                  <dt>{t('Improve.anchor_run')}</dt>
                  <dd>
                    <code>{data.anchor_run.run_id.slice(0, 16)}</code>
                    <span className="improve-preview__score">
                      {data.anchor_run.overall.toFixed(1)}
                    </span>
                  </dd>
                </div>
              )}
              {data.baseline_run && (
                <div className="improve-preview__dl-row">
                  <dt>{t('Improve.baseline_run')}</dt>
                  <dd>
                    <code>{data.baseline_run.run_id.slice(0, 16)}</code>
                    <span className="improve-preview__score">
                      {data.baseline_run.overall.toFixed(1)}
                    </span>
                  </dd>
                </div>
              )}
              {data.target_dimension && (
                <div className="improve-preview__dl-row">
                  <dt>{t('Improve.target_dim')}</dt>
                  <dd>{data.target_dimension}</dd>
                </div>
              )}
              {data.target_prompt_file && (
                <div className="improve-preview__dl-row">
                  <dt>{t('Improve.target_prompt_file')}</dt>
                  <dd><code>{data.target_prompt_file}</code></dd>
                </div>
              )}
            </dl>
          </section>

          {data.phase25_eligible && (
            <div className="improve-preview__phase25">
              <span className="improve-preview__phase25-badge">Phase 2.5</span>
              {data.phase25_trigger_reason && (
                <span className="improve-preview__phase25-reason">
                  {data.phase25_trigger_reason}
                </span>
              )}
            </div>
          )}
        </>
      )}

      <section className="improve-preview__section">
        <h3 className="improve-preview__section-title">{t('Improve.section_repo')}</h3>
        <dl className="improve-preview__dl">
          <div className="improve-preview__dl-row">
            <dt>{t('Improve.repo_branch')}</dt>
            <dd><code>{data.repo_state.branch ?? '—'}</code></dd>
          </div>
          <div className="improve-preview__dl-row">
            <dt>{t('Improve.repo_head')}</dt>
            <dd>
              <code>
                {data.repo_state.head_sha
                  ? data.repo_state.head_sha.slice(0, 12)
                  : '—'}
              </code>
            </dd>
          </div>
          {data.repo_state.prompts_dirty && (
            <div className="improve-preview__dl-row improve-preview__dl-row--warn">
              <dt>{t('Improve.repo_prompts_dirty')}</dt>
              <dd>⚠</dd>
            </div>
          )}
        </dl>
      </section>

      <section className="improve-preview__section">
        <h3 className="improve-preview__section-title">{t('Improve.section_provider')}</h3>
        <div className={`improve-preview__provider-badge ${data.provider_configured ? 'improve-preview__provider-badge--ok' : 'improve-preview__provider-badge--missing'}`}>
          {data.provider_configured
            ? t('Improve.provider_configured')
            : t('Improve.provider_missing')}
        </div>
      </section>

      {data.mutable_prompts.length > 0 && (
        <section className="improve-preview__section">
          <h3 className="improve-preview__section-title">{t('Improve.mutable_prompts')}</h3>
          <ul className="improve-preview__prompt-list">
            {data.mutable_prompts.map((p) => (
              <li key={p} className="improve-preview__prompt-item">
                <code>{p}</code>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data.existing_sessions.length > 0 && (
        <section className="improve-preview__section">
          <h3 className="improve-preview__section-title">{t('Improve.section_sessions')}</h3>
          <div className="improve-preview__sessions">
            {data.existing_sessions.map((s) => (
              <div key={s.session_id} className="improve-preview__session-card">
                <div className="improve-preview__session-header">
                  <code className="improve-preview__session-id">{s.session_id.slice(0, 16)}</code>
                  {s.last_status && (
                    <span className={`improve-preview__status-pill improve-preview__status-pill--${s.last_status}`}>
                      {s.last_status}
                    </span>
                  )}
                </div>
                <div className="improve-preview__session-meta">
                  {t('Improve.session_rounds')}: {s.rounds_completed}
                  {s.phase25_attempted && (
                    <span className="improve-preview__phase25-badge">P2.5</span>
                  )}
                  {s.has_pending_worktree && (
                    <span className="improve-preview__warn-badge">
                      {t('Improve.session_pending_worktree')}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
