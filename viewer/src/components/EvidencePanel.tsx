import { useTranslation } from '../i18n/useTranslation';
import ClaimBadge from './ClaimBadge';
import type { ClaimVerdict } from './ClaimBadge';

export interface Claim {
  claim_id: string;
  verdict: ClaimVerdict;
  file: string;
  line_start: number;
  line_end: number;
  statement: string;
  evidence?: string;
}

interface EvidencePanelProps {
  claim: Claim | null;
}

export default function EvidencePanel({ claim }: EvidencePanelProps) {
  const { t } = useTranslation();

  return (
    <article className="evidence-panel" aria-live="polite">
      <h2 className="evidence-panel__title">{t('Lesson.evidence_panel_title')}</h2>
      {claim ? (
        <div className="evidence-panel__body">
          <div className="evidence-panel__header">
            <span className="evidence-panel__claim-id">{claim.claim_id}</span>
            <ClaimBadge verdict={claim.verdict} />
          </div>
          <p className="evidence-panel__statement">{claim.statement}</p>
          <div className="evidence-panel__location">
            <code>
              {claim.file}:{claim.line_start}
              {claim.line_end !== claim.line_start ? `-${claim.line_end}` : ''}
            </code>
          </div>
          {claim.evidence ? (
            <pre className="evidence-panel__evidence">{claim.evidence}</pre>
          ) : null}
        </div>
      ) : (
        <p className="evidence-panel__empty">{t('Lesson.evidence_empty')}</p>
      )}
    </article>
  );
}
