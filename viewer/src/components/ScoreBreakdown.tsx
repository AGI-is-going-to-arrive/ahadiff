import type { ScorePayload } from '../api/types';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import { formatHardGateDetail, formatHardGateName } from '../utils/hard-gates';
import { DIMENSION_ORDER, DIM_I18N_KEYS, DIM_HINT_KEYS } from '../utils/score-dimensions';
import { safeVerdict } from '../utils/verdict';
import './ScoreBreakdown.css';

interface ScoreBreakdownProps {
  payload: ScorePayload;
}

function dimColor(pct: number): string {
  if (pct >= 80) return 'var(--success)';
  if (pct >= 50) return 'var(--warning)';
  return 'var(--danger)';
}

export default function ScoreBreakdown({ payload }: ScoreBreakdownProps) {
  const { t } = useTranslation();
  const gateEntries = payload.hard_gates ? Object.entries(payload.hard_gates) : [];
  const failedGates = gateEntries.filter(([, g]) => !g.passed);
  const passedGates = gateEntries.filter(([, g]) => g.passed);

  return (
    <div className="score-breakdown">
      <div className="score-breakdown__header">
        <div className="score-breakdown__overall">
          <span className={`score-breakdown__overall-value verdict-badge verdict-badge--${safeVerdict(payload.verdict)}`}>
            {payload.overall.toFixed(1)}
          </span>
          <div className="score-breakdown__overall-meta">
            <span className="score-breakdown__verdict">{payload.verdict}</span>
            <span className="score-breakdown__overall-label">{t('RunDetail.overall_score')}</span>
          </div>
        </div>
        {gateEntries.length > 0 && (
          <div className="score-breakdown__gate-summary">
            <span className={`score-breakdown__gate-badge ${failedGates.length > 0 ? 'score-breakdown__gate-badge--fail' : 'score-breakdown__gate-badge--pass'}`}>
              {failedGates.length > 0
                ? t('RunDetail.gates_failed', { count: String(failedGates.length) })
                : t('RunDetail.gates_all_passed')}
            </span>
          </div>
        )}
      </div>

      <div className="score-breakdown__dims-grid">
        {DIMENSION_ORDER.map((dim) => {
          const d = payload.dimensions?.[dim];
          if (!d) return null;
          const pct = d.max_score > 0 ? (d.score / d.max_score) * 100 : 0;
          return (
            <div key={dim} className="score-breakdown__dim-card" title={t(DIM_HINT_KEYS[dim] ?? '')}>
              <div className="score-breakdown__dim-top">
                <span className="score-breakdown__dim-name">{t(DIM_I18N_KEYS[dim] ?? dim)}</span>
                <span className="score-breakdown__dim-score" style={{ color: d.max_score > 0 ? dimColor(pct) : 'var(--muted)' }}>
                  {d.max_score > 0 ? (
                    <>
                      {d.score.toFixed(1)}
                      <span className="score-breakdown__dim-max">/{d.max_score}</span>
                    </>
                  ) : (
                    t('Lesson.score_dim_na' as MessageKey)
                  )}
                </span>
              </div>
              <div className="score-breakdown__dim-bar">
                {d.max_score > 0 ? (
                  <div
                    className="score-breakdown__dim-fill"
                    style={{ width: `${Math.min(pct, 100)}%`, background: dimColor(pct) }}
                    role="meter"
                    aria-valuenow={d.score}
                    aria-valuemin={0}
                    aria-valuemax={d.max_score}
                    aria-label={`${t(DIM_I18N_KEYS[dim] ?? dim)}: ${d.score.toFixed(1)} / ${d.max_score}`}
                  />
                ) : (
                  <div
                    className="score-breakdown__dim-fill score-breakdown__dim-fill--na"
                    role="img"
                    aria-label={`${t(DIM_I18N_KEYS[dim] ?? dim)}: ${t('Lesson.score_dim_na' as MessageKey)}`}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>

      {gateEntries.length > 0 && (
        <div className="score-breakdown__gates">
          <h2 className="score-breakdown__gates-title">{t('RunDetail.hard_gates')}</h2>
          {failedGates.length > 0 && (
            <div className="score-breakdown__gate-group">
              {failedGates.map(([name, gate]) => (
                <div key={name} className="score-breakdown__gate score-breakdown__gate--fail">
                  <span className="score-breakdown__gate-indicator" aria-hidden="true">✗</span>
                  <div className="score-breakdown__gate-content">
                    <span className="score-breakdown__gate-name">{formatHardGateName(t, name)}</span>
                    {gate.detail && (
                      <span className="score-breakdown__gate-detail">{formatHardGateDetail(t, name, gate)}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="score-breakdown__gate-group score-breakdown__gate-group--pass">
            {passedGates.map(([name, gate]) => (
              <div key={name} className="score-breakdown__gate score-breakdown__gate--pass">
                <span className="score-breakdown__gate-indicator" aria-hidden="true">✓</span>
                <div className="score-breakdown__gate-content">
                  <span className="score-breakdown__gate-name">{formatHardGateName(t, name)}</span>
                  {gate.detail && (
                    <span className="score-breakdown__gate-detail">{formatHardGateDetail(t, name, gate)}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {payload.notes.length > 0 && (
        <div className="score-breakdown__notes">
          <h2 className="score-breakdown__notes-title">{t('RunDetail.notes')}</h2>
          <ul className="score-breakdown__notes-list">
            {payload.notes.map((note, index) => (
              <li key={index} className="score-breakdown__notes-text">
                {note}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
