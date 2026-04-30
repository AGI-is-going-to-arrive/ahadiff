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
  source_hunks?: ReadonlyArray<ClaimSourceHunk>;
}

export interface ClaimSourceHunk {
  file: string;
  display_path?: string;
  start: number;
  end: number;
  side?: 'old' | 'new' | 'either';
}

interface EvidencePanelProps {
  claim: Claim | null;
}

function formatLocation(file: string, start: number, end: number): string {
  if (!file || start <= 0) return file || '';
  const range = end > 0 && end !== start ? `-${end}` : '';
  return `${file}:${start}${range}`;
}

function getClaimLocations(claim: Claim): string[] {
  const hunkLocations =
    claim.source_hunks
      ?.map((hunk) => formatLocation(hunk.display_path ?? hunk.file, hunk.start, hunk.end))
      .filter(Boolean) ?? [];
  if (hunkLocations.length > 0) return hunkLocations;
  return [formatLocation(claim.file, claim.line_start, claim.line_end)].filter(Boolean);
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
            {getClaimLocations(claim).map((location) => (
              <code key={location}>{location}</code>
            ))}
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
