import { useCallback, useEffect, useState } from 'react';
import { getImprovePreflight } from '../api/improve';
import type { ImprovePreflightResponse } from '../api/types';
import { useTranslation, type MessageKey, type TranslateFn } from '../i18n/useTranslation';
import './ImprovePreview.css';

const STATUS_LABEL_KEYS = {
  baseline: 'Ratchet.status_baseline',
  keep: 'Ratchet.status_keep',
  keep_final: 'Ratchet.status_keep_final',
  discard: 'Ratchet.status_discard',
  crash: 'Ratchet.status_crash',
  targeted_verify: 'Ratchet.status_targeted_verify',
  phase25_rewrite: 'Ratchet.status_phase25_rewrite',
  non_ratcheted: 'Ratchet.status_non_ratcheted',
} as const satisfies Record<string, MessageKey>;

type KnownStatus = keyof typeof STATUS_LABEL_KEYS;
type StatusTone = 'kept' | 'discarded' | 'other';

function phase25ReasonKey(reason: string | null | undefined) {
  if (reason === 'latest_session_discarded') {
    return 'Improve.phase25_reason_latest_session_discarded';
  }
  return 'Improve.phase25_reason_unknown';
}

function isKnownStatus(status: string): status is KnownStatus {
  return Object.prototype.hasOwnProperty.call(STATUS_LABEL_KEYS, status);
}

function statusTone(status: string): StatusTone {
  switch (status) {
    case 'baseline':
    case 'keep':
    case 'keep_final':
      return 'kept';
    case 'discard':
    case 'crash':
      return 'discarded';
    default:
      return 'other';
  }
}

function statusLabel(status: string, t: TranslateFn): string {
  if (isKnownStatus(status)) {
    return t(STATUS_LABEL_KEYS[status]);
  }
  return status.replace(/_/g, ' ');
}

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
      <div className="ratchet-card__body" role="status" aria-live="polite">
        <span className="loading-spinner" />
        {t('Serve.loading')}
      </div>
    );
  }

  if (error) {
    return (
      <div className="ratchet-card__body" role="alert">
        <div className="improve-preview__error">
          {t('Error.fetch_failed', { resource: t('Improve.heading') })}
        </div>
        <button type="button" className="retry-btn" onClick={() => void fetchPreflight()}>
          {t('Error.retry')}
        </button>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="ratchet-card__body">
      <aside className="improve-preview__banner" role="status" aria-live="polite">
        {t('Improve.read_only_banner')}
      </aside>

      {!data.available && (
        <div className="improve-preview__unavailable">
          <p>{t(`Improve.unavailable_${data.reason ?? 'unknown'}`)}</p>
        </div>
      )}

      {data.available && (
        <>
          <section className="improve-preview__section">
            <h3 className="improve-preview__section-title">{t('Improve.section_plan')}</h3>
            <div className="improve-preview__tile-grid">
              {data.anchor_run && (
                <div className="improve-preview__tile">
                  <div className="improve-preview__tile-eyebrow">{t('Improve.anchor_run')}</div>
                  <div className="improve-preview__tile-value">
                    <code>{data.anchor_run.run_id.slice(0, 16)}</code>
                    <span className="improve-preview__score">{data.anchor_run.overall.toFixed(1)}</span>
                  </div>
                </div>
              )}
              {data.baseline_run && (
                <div className="improve-preview__tile">
                  <div className="improve-preview__tile-eyebrow">{t('Improve.baseline_run')}</div>
                  <div className="improve-preview__tile-value">
                    <code>{data.baseline_run.run_id.slice(0, 16)}</code>
                    <span className="improve-preview__score">{data.baseline_run.overall.toFixed(1)}</span>
                  </div>
                </div>
              )}
              {data.target_dimension && (
                <div className="improve-preview__tile">
                  <div className="improve-preview__tile-eyebrow">{t('Improve.target_dim')}</div>
                  <div className="improve-preview__tile-value">{data.target_dimension}</div>
                </div>
              )}
              {data.target_prompt_file && (
                <div className="improve-preview__tile">
                  <div className="improve-preview__tile-eyebrow">{t('Improve.target_prompt_file')}</div>
                  <div className="improve-preview__tile-value"><code>{data.target_prompt_file}</code></div>
                </div>
              )}
            </div>
          </section>

          {data.phase25_eligible && (
            <aside className="improve-preview__phase25">
              <span className="improve-preview__phase25-badge">{t('Improve.phase25_badge')}</span>
              {data.phase25_trigger_reason && (
                <span className="improve-preview__phase25-reason">{t(phase25ReasonKey(data.phase25_trigger_reason))}</span>
              )}
            </aside>
          )}
        </>
      )}

      <section className="improve-preview__section">
        <h3 className="improve-preview__section-title">{t('Improve.section_repo')}</h3>
        <div className="improve-preview__tile-grid improve-preview__tile-grid--2">
          <div className="improve-preview__tile">
            <div className="improve-preview__tile-eyebrow">{t('Improve.repo_branch')}</div>
            <div className="improve-preview__tile-value"><code>{data.repo_state.branch ?? '—'}</code></div>
          </div>
          <div className="improve-preview__tile">
            <div className="improve-preview__tile-eyebrow">{t('Improve.repo_head')}</div>
            <div className="improve-preview__tile-value">
              <code>{data.repo_state.head_sha ? data.repo_state.head_sha.slice(0, 12) : '—'}</code>
            </div>
          </div>
        </div>
        {data.repo_state.prompts_dirty && (
          <div className="improve-preview__tile improve-preview__tile--warn">
            <div className="improve-preview__tile-eyebrow">{t('Improve.repo_prompts_dirty')}</div>
            <div className="improve-preview__tile-value">⚠</div>
          </div>
        )}
      </section>

      <section className="improve-preview__section">
        <h3 className="improve-preview__section-title">{t('Improve.section_provider')}</h3>
        <div className="improve-preview__tile improve-preview__provider-tile">
          <span className={`ratchet-status ${data.provider_configured ? 'ratchet-status--kept' : 'ratchet-status--discarded'}`}>
            {data.provider_configured ? t('Improve.provider_configured') : t('Improve.provider_missing')}
          </span>
        </div>
      </section>

      {data.mutable_prompts.length > 0 && (
        <section className="improve-preview__section">
          <h3 className="improve-preview__section-title">{t('Improve.mutable_prompts')}</h3>
          <ul className="improve-preview__prompt-list">
            {data.mutable_prompts.map((p) => (
              <li key={p} className="improve-preview__prompt-item"><code>{p}</code></li>
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
                    <span className={`ratchet-status ratchet-status--${statusTone(s.last_status)}`}>
                      {statusLabel(s.last_status, t)}
                    </span>
                  )}
                </div>
                <div className="improve-preview__session-meta">
                  {t('Improve.session_rounds')}: {s.rounds_completed}
                  {s.phase25_attempted && (
                    <span className="improve-preview__phase25-badge">{t('Improve.phase25_badge_short')}</span>
                  )}
                  {s.has_pending_worktree && (
                    <span className="improve-preview__warn-badge">{t('Improve.session_pending_worktree')}</span>
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
