import { useCallback, useEffect, useState } from 'react';
import { z } from 'zod';
import { getRunArtifact } from '../api/runs';
import { useTranslation, type TranslateFn, type MessageKey } from '../i18n/useTranslation';
import { DIMENSION_ORDER, DIM_I18N_KEYS } from '../utils/score-dimensions';
import './JudgeReport.css';

function translateDimName(t: TranslateFn, dim: string): string {
  const key = DIM_I18N_KEYS[dim];
  if (key) return t(key);
  return dim.replaceAll('_', ' ');
}

const judgeDimensionSchema = z.record(
  z.string(),
  z
    .object({
      reason: z.string(),
      score: z.number().finite().nonnegative(),
      max_score: z.number().finite().nonnegative(),
    })
    .strict()
    .refine((dimension) => dimension.score <= dimension.max_score, {
      message: 'score must be <= max_score',
      path: ['score'],
    }),
);

export const judgeReportSchema = z
  .object({
    artifact: z.literal('llm_judge'),
    schema_version: z.number().int().positive(),
    run_id: z.string().min(1),
    source_ref: z.string(),
    source_kind: z.string().min(1),
    model_id: z.string().min(1),
    provider_class: z.string().min(1),
    prompt_fingerprint: z.string().min(1),
    eval_bundle_version: z.string().min(1),
    overall: z.number().finite().nonnegative(),
    dimensions: judgeDimensionSchema,
    usage: z
      .object({
        input_tokens: z.number().int().nonnegative(),
        output_tokens: z.number().int().nonnegative(),
      })
      .strict(),
    finish_reason: z.string().nullable(),
    request_id: z.string().nullable(),
    notes: z.array(z.string()),
  })
  .strict();

interface JudgeReportProps {
  runId: string;
}

type JudgeData = z.infer<typeof judgeReportSchema>;

export default function JudgeReport({ runId }: JudgeReportProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<JudgeData | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState(false);
  const [rawExpanded, setRawExpanded] = useState(false);

  const fetchJudge = useCallback(async () => {
    setLoading(true);
    setError(false);
    setNotFound(false);
    try {
      const envelope = await getRunArtifact(runId, 'judge');
      const raw = JSON.parse(envelope.content);
      const result = judgeReportSchema.safeParse(raw);
      if (!result.success) {
        throw new Error('judge artifact schema validation failed');
      }
      setData(result.data);
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'status' in err && (err as { status: number }).status === 404) {
        setNotFound(true);
      } else {
        setError(true);
      }
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void fetchJudge();
  }, [fetchJudge]);

  if (loading) {
    return (
      <div role="status" aria-live="polite" className="judge-report__loading">
        <span className="loading-spinner" />
        {t('RunDetail.judge_loading')}
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="judge-report__empty">
        <p>{t('RunDetail.judge_unavailable')}</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div role="alert" className="judge-report__error">
        {t('RunDetail.judge_load_failed')}
        <button type="button" className="retry-btn" onClick={() => void fetchJudge()}>
          {t('Error.retry')}
        </button>
      </div>
    );
  }

  const modelId = data.model_id;
  const overall = data.overall;
  const rawNotes = data.notes;
  const overallNotes = rawNotes;
  const dimensions = data.dimensions;

  const orderedDims = Object.keys(dimensions).sort((a, b) => {
    const idxA = DIMENSION_ORDER.indexOf(a as typeof DIMENSION_ORDER[number]);
    const idxB = DIMENSION_ORDER.indexOf(b as typeof DIMENSION_ORDER[number]);
    if (idxA !== -1 && idxB !== -1) return idxA - idxB;
    if (idxA !== -1) return -1;
    if (idxB !== -1) return 1;
    return a.localeCompare(b);
  });

  return (
    <div className="judge-report">
      {modelId && (
        <div className="judge-report__model">
          <span className="judge-report__model-label">{t('RunDetail.judge_model')}</span>
          <code className="judge-report__model-value">{modelId}</code>
        </div>
      )}

      <div className="judge-report__summary">
        <span className="judge-report__summary-label">{t('RunDetail.judge_score')}</span>
        <span className="judge-report__summary-value">{overall.toFixed(1)}</span>
        <p className="judge-report__summary-note">{t('RunDetail.judge_advisory_note')}</p>
      </div>

      {Object.keys(dimensions).length > 0 && (
        <dl className="judge-report__feedback">
          {orderedDims.map((dim) => {
            const val = dimensions[dim];
            const score = val.score;
            const maxScore = val.max_score;
            return (
              <div key={dim} className="judge-report__feedback-row">
                <dt className="judge-report__feedback-dim">
                  {translateDimName(t, dim)}
                  <span className={`judge-report__feedback-score ${maxScore === 0 ? 'judge-report__feedback-score--na' : ''}`}>
                    {maxScore === 0 ? t('Lesson.score_dim_na' as MessageKey) : score.toFixed(1)}
                  </span>
                </dt>
                <dd className="judge-report__feedback-reason">
                  {val.reason}
                </dd>
              </div>
            );
          })}
        </dl>
      )}

      {overallNotes.length > 0 && (
        <div className="judge-report__notes">
          <h2 className="judge-report__notes-title">{t('RunDetail.notes')}</h2>
          <ul className="judge-report__notes-list">
            {overallNotes.map((note, index) => (
              <li key={index} className="judge-report__notes-text">
                {note}
              </li>
            ))}
          </ul>
        </div>
      )}

      <details
        className="judge-report__raw"
        open={rawExpanded}
        onToggle={(e) => setRawExpanded((e.target as HTMLDetailsElement).open)}
      >
        <summary className="judge-report__raw-summary">
          {t('RunDetail.judge_raw_json')}
        </summary>
        <pre className="judge-report__raw-content">
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </div>
  );
}
