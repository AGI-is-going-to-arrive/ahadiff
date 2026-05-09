import type { ScorePayload } from '../api/types';
import { useTranslation } from '../i18n/useTranslation';
import { DIMENSION_ORDER, DIM_I18N_KEYS, DIM_HINT_KEYS } from '../utils/score-dimensions';
import { safeVerdict } from '../utils/verdict';
import './ScoreBreakdown.css';

interface ScoreBreakdownProps {
  payload: ScorePayload;
}

export default function ScoreBreakdown({ payload }: ScoreBreakdownProps) {
  const { t } = useTranslation();

  return (
    <div className="score-breakdown">
      <div className="score-breakdown__overall">
        <span className="score-breakdown__overall-label">{t('RunDetail.overall_score')}</span>
        <span className={`score-breakdown__overall-value verdict-badge verdict-badge--${safeVerdict(payload.verdict)}`}>
          {payload.overall.toFixed(1)}
        </span>
        <span className="score-breakdown__verdict">{payload.verdict}</span>
      </div>

      <dl className="score-breakdown__dims">
        {DIMENSION_ORDER.map((dim) => {
          const d = payload.dimensions?.[dim];
          if (!d) return null;
          const pct = d.max_score > 0 ? (d.score / d.max_score) * 100 : 0;
          return (
            <div key={dim} className="score-breakdown__dim-row">
              <dt className="score-breakdown__dim-name" title={t(DIM_HINT_KEYS[dim] ?? '')}>
                {t(DIM_I18N_KEYS[dim] ?? dim)}
              </dt>
              <dd className="score-breakdown__dim-bar-wrap">
                <div className="score-breakdown__dim-bar">
                  <div
                    className="score-breakdown__dim-fill"
                    style={{ width: `${Math.min(pct, 100)}%` }}
                    role="meter"
                    aria-valuenow={d.score}
                    aria-valuemin={0}
                    aria-valuemax={d.max_score}
                    aria-label={`${t(DIM_I18N_KEYS[dim] ?? dim)}: ${d.score.toFixed(1)} / ${d.max_score}`}
                  />
                </div>
                <span className="score-breakdown__dim-score">
                  {d.score.toFixed(1)}/{d.max_score}
                </span>
              </dd>
            </div>
          );
        })}
      </dl>

      {payload.hard_gates && Object.keys(payload.hard_gates).length > 0 && (
        <div className="score-breakdown__gates">
          <h3 className="score-breakdown__gates-title">{t('RunDetail.hard_gates')}</h3>
          <ul className="score-breakdown__gate-list">
            {Object.entries(payload.hard_gates).map(([name, gate]) => (
              <li key={name} className={`score-breakdown__gate ${gate.passed ? 'score-breakdown__gate--pass' : 'score-breakdown__gate--fail'}`}>
                <span className="score-breakdown__gate-indicator">
                  {gate.passed ? '✓' : '✗'}
                </span>
                <span className="score-breakdown__gate-name">{name}</span>
                {gate.detail && <span className="score-breakdown__gate-detail">{gate.detail}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {payload.notes && (
        <div className="score-breakdown__notes">
          <h3 className="score-breakdown__notes-title">{t('RunDetail.notes')}</h3>
          <p className="score-breakdown__notes-text">{payload.notes}</p>
        </div>
      )}
    </div>
  );
}
