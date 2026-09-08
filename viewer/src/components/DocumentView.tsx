import { useEffect, useMemo, useState, type ReactElement } from 'react';
import { useTranslation } from '../i18n/useTranslation';

interface DocumentViewProps {
  content: string;
  file: string;
  focusLine?: number;
  endLine?: number;
  focusRequest?: number;
}

const PAGE_LINES = 2000;

export default function DocumentView({ content, file, focusLine, endLine, focusRequest }: DocumentViewProps): ReactElement {
  const { t } = useTranslation();
  const lines = useMemo(() => content.split('\n'), [content]);
  const [offset, setOffset] = useState(0);
  useEffect(() => { setOffset(0); }, [content]);
  useEffect(() => {
    if (!focusLine || focusLine < 1) return;
    setOffset(Math.floor((focusLine - 1) / PAGE_LINES) * PAGE_LINES);
  }, [focusLine, focusRequest]);
  const visibleLines = lines.slice(offset, offset + PAGE_LINES);
  return (
    <section className="diff-view document-view" aria-label={t('Evidence.document_title')}>
      <p className="document-view__note" role="note">{t('Evidence.document_scope')}</p>
      <div className="document-view__header">
        <strong>{file}</strong>
        <span>{t('Evidence.document_lines', { first: offset + 1, last: offset + visibleLines.length, total: lines.length })}</span>
      </div>
      <pre className="document-view__text" tabIndex={0} aria-label={t('Evidence.document_title')}>
        <code>{visibleLines.map((line, index) => {
          const number = offset + index + 1;
          const selected = focusLine != null && number >= focusLine && number <= (endLine ?? focusLine);
          return <span key={number} className={`document-view__line${selected ? ' document-view__line--selected' : ''}`}
            data-line-anchor={`${file}:${number}`} data-line-side="document">
            <span className="document-view__number" aria-hidden="true">{number}</span>{line || ' '}<br />
          </span>;
        })}</code>
      </pre>
      {lines.length > PAGE_LINES && <div className="document-view__navigation">
        <button type="button" className="chip" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_LINES))}>{t('Evidence.previous_lines')}</button>
        <button type="button" className="chip" disabled={offset + PAGE_LINES >= lines.length} onClick={() => setOffset(offset + PAGE_LINES)}>{t('Evidence.next_lines')}</button>
      </div>}
    </section>
  );
}
