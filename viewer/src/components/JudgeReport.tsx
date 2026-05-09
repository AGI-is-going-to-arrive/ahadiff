import { useCallback, useEffect, useState } from 'react';
import { z } from 'zod';
import { getRunArtifact } from '../api/runs';
import { useTranslation } from '../i18n/useTranslation';
import './JudgeReport.css';

const judgeDimensionSchema = z.record(z.string(), z.object({
  reason: z.string().optional(),
  score: z.number().optional(),
}).passthrough());

const judgeReportSchema = z.object({
  model_id: z.string().optional(),
  notes: z.union([z.string(), z.array(z.string())]).optional(),
  dimensions: judgeDimensionSchema.optional(),
}).passthrough();

interface JudgeReportProps {
  runId: string;
}

interface JudgeData {
  [key: string]: unknown;
}

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
      setData(result.success ? result.data as JudgeData : raw as JudgeData);
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

  const modelId = typeof data.model_id === 'string' ? data.model_id : null;
  const rawNotes = data.notes;
  const overallNotes =
    typeof rawNotes === 'string'
      ? [rawNotes]
      : Array.isArray(rawNotes) && rawNotes.every((note) => typeof note === 'string')
        ? rawNotes
        : [];
  const rawDims = data.dimensions;
  const dimsParsed = judgeDimensionSchema.safeParse(rawDims);
  const dimensions = dimsParsed.success ? dimsParsed.data : undefined;

  return (
    <div className="judge-report">
      {modelId && (
        <div className="judge-report__model">
          <span className="judge-report__model-label">{t('RunDetail.judge_model')}</span>
          <code className="judge-report__model-value">{modelId}</code>
        </div>
      )}

      {dimensions && Object.keys(dimensions).length > 0 && (
        <dl className="judge-report__feedback">
          {Object.entries(dimensions).map(([dim, val]) => (
            <div key={dim} className="judge-report__feedback-row">
              <dt className="judge-report__feedback-dim">{dim}</dt>
              <dd className="judge-report__feedback-reason">
                {typeof val === 'object' && val?.reason ? String(val.reason) : '—'}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {overallNotes.length > 0 && (
        <div className="judge-report__notes">
          <h3 className="judge-report__notes-title">{t('RunDetail.notes')}</h3>
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
