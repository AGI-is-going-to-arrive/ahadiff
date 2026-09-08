import type { ReactElement } from 'react';
import type { SourceAnchor } from '../api/types';
import { useTranslation } from '../i18n/useTranslation';
import './SourceAnchors.css';

interface SourceAnchorsProps {
  anchors: ReadonlyArray<SourceAnchor>;
  onJump?: (anchor: SourceAnchor) => void;
}

export default function SourceAnchors({ anchors, onJump }: SourceAnchorsProps): ReactElement | null {
  const { t } = useTranslation();
  if (anchors.length === 0) return null;
  return (
    <ul className="source-anchors" aria-label={t('Evidence.anchors')}>
      {anchors.map((anchor) => (
        <li key={`${anchor.anchor_id}:${anchor.side}`} className="source-anchors__item">
          <div className="source-anchors__location">
            <strong>{t(`Evidence.kind_${anchor.locator.kind}`)}</strong>
            <span>{t(`Evidence.side_${anchor.side}`)} · {anchor.format}</span>
            {onJump ? <button type="button" className="claim-inspector__jump-btn" onClick={() => onJump(anchor)}>
              {anchor.file}:{anchor.start}{anchor.end !== anchor.start ? `–${anchor.end}` : ''}
            </button> : <code>{anchor.file}:{anchor.start}{anchor.end !== anchor.start ? `–${anchor.end}` : ''}</code>}
          </div>
          {anchor.locator.heading_path.length > 0 && <p>{anchor.locator.heading_path.join(' › ')}</p>}
          {anchor.locator.paragraph_index != null && <p>{t('Evidence.paragraph', { index: anchor.locator.paragraph_index })}</p>}
          {anchor.locator.cell_index != null && <p>{t('Evidence.cell', { index: anchor.locator.cell_index })}{anchor.locator.cell_id ? ` · ${anchor.locator.cell_id}` : ''}</p>}
          {anchor.locator.key_path.length > 0 && <code>{JSON.stringify(anchor.locator.key_path)}</code>}
          {anchor.locator.fallback_reason && <p role="note">{t('Evidence.weak_fallback')}</p>}
          <pre className="evidence-panel__evidence">{anchor.quote}</pre>
          <details><summary>{t('Evidence.content_hash')}</summary><code className="source-anchors__hash">{anchor.content_hash}</code></details>
        </li>
      ))}
    </ul>
  );
}
