import { useTranslation } from '../i18n/useTranslation';
import ClaimBadge from './ClaimBadge';
import EvidencePanel from './EvidencePanel';
import type { Claim } from './EvidencePanel';
import type { DiffSourceLine } from './DiffView';
import './ClaimInspector.css';

export type ClaimInspectorClaim = Claim & {
  source_lines?: ReadonlyArray<DiffSourceLine>;
  source_line_groups?: ReadonlyArray<ClaimSourceLineGroup>;
};

export interface ClaimSourceLineGroup {
  file: string;
  line_start: number;
  line_end: number;
  side?: 'old' | 'new' | 'either';
  lines: ReadonlyArray<DiffSourceLine>;
}

export interface ClaimInspectorProps {
  claims?: ClaimInspectorClaim[];
  selectedClaimId?: string | null;
  onSelect?: (claimId: string) => void;
  onCopyAnchor?: (claimId: string) => void;
}

function hasSourceHunk(claim: ClaimInspectorClaim): boolean {
  return Boolean(claim.file) && claim.line_start > 0;
}

function formatSourceRef(claim: ClaimInspectorClaim): string {
  if (!hasSourceHunk(claim)) return '';
  const range =
    claim.line_end !== claim.line_start && claim.line_end > 0 ? `-${claim.line_end}` : '';
  return `${claim.file}:${claim.line_start}${range}`;
}

function formatSourceGroupRef(group: ClaimSourceLineGroup): string {
  const range =
    group.line_end !== group.line_start && group.line_end > 0 ? `-${group.line_end}` : '';
  return `${group.file}:${group.line_start}${range}`;
}

function formatSourceLine(line: DiffSourceLine): string {
  const marker = line.type === 'add' ? '+' : line.type === 'del' ? '-' : ' ';
  return `${marker}${String(line.line_no).padStart(4, ' ')} ${line.text}`;
}

export default function ClaimInspector({
  claims = [],
  selectedClaimId = null,
  onSelect,
  onCopyAnchor,
}: ClaimInspectorProps) {
  const { t } = useTranslation();
  const selectedClaim = selectedClaimId
    ? claims.find((c) => c.claim_id === selectedClaimId) ?? null
    : null;
  const selectedSourceLines = selectedClaim?.source_lines ?? [];
  const selectedSourceGroups = selectedClaim?.source_line_groups ?? [];

  if (claims.length === 0 && !selectedClaim) {
    return (
      <aside
        className="claim-inspector claim-inspector--empty"
        aria-label={t('Claim_inspector.title')}
      >
        <header className="claim-inspector__header">
          <h2 className="claim-inspector__title">{t('Claim_inspector.title')}</h2>
        </header>
        <div className="claim-inspector__empty" role="status">
          {t('Claim_inspector.no_selection')}
        </div>
      </aside>
    );
  }

  return (
    <aside className="claim-inspector" aria-label={t('Claim_inspector.title')}>
      <header className="claim-inspector__header">
        <h2 className="claim-inspector__title">{t('Claim_inspector.title')}</h2>
        {selectedClaim && onCopyAnchor && (
          <button
            type="button"
            className="claim-inspector__action"
            aria-label={t('Claim_inspector.copy_anchor')}
            onClick={() => onCopyAnchor(selectedClaim.claim_id)}
          >
            &#x29C9;
          </button>
        )}
      </header>

      {claims.length > 0 && (
        <section className="claim-inspector__list" aria-label={t('Claim_inspector.list_title')}>
          <ul className="claim-inspector__list-items">
            {claims.map((claim) => {
              const isSelected = claim.claim_id === selectedClaimId;
              return (
                <li key={claim.claim_id}>
                  <button
                    type="button"
                    id={`claim-${claim.claim_id}`}
                    className={`claim-inspector__item${isSelected ? ' claim-inspector__item--selected' : ''}`}
                    aria-pressed={isSelected}
                    onClick={() => onSelect?.(claim.claim_id)}
                  >
                    <div className="claim-inspector__item-row">
                      <span className="claim-inspector__item-id">{claim.claim_id}</span>
                      <ClaimBadge verdict={claim.verdict} />
                    </div>
                    <p className="claim-inspector__item-text">{claim.statement}</p>
                    {hasSourceHunk(claim) && (
                      <code className="claim-inspector__item-loc">{formatSourceRef(claim)}</code>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {selectedClaim && (
        <>
          <div className="claim-inspector__row">
            <span className="claim-inspector__row-label">
              {t('Claim_inspector.status_label')}
            </span>
            <ClaimBadge verdict={selectedClaim.verdict} />
          </div>

          <EvidencePanel claim={selectedClaim} />

          <div
            className="claim-inspector__source"
            role="region"
            aria-label={t('Claim_inspector.source_hunk_title')}
          >
            <span className="claim-inspector__row-label">
              {t('Claim_inspector.source_hunk_title')}
            </span>
            {hasSourceHunk(selectedClaim) && selectedSourceLines.length > 0 ? (
              <div className="claim-inspector__source-groups">
                {(selectedSourceGroups.length > 0
                  ? selectedSourceGroups
                  : [
                      {
                        file: selectedClaim.file,
                        line_start: selectedClaim.line_start,
                        line_end: selectedClaim.line_end,
                        lines: selectedSourceLines,
                      },
                    ]
                ).map((group, index) => (
                  <div
                    key={`${formatSourceGroupRef(group)}-${index}`}
                    className="claim-inspector__source-group"
                  >
                    <code className="claim-inspector__source-ref">
                      {formatSourceGroupRef(group)}
                    </code>
                    <pre className="claim-inspector__source-code">
                      <code>{group.lines.map(formatSourceLine).join('\n')}</code>
                    </pre>
                  </div>
                ))}
              </div>
            ) : (
              <p className="claim-inspector__source-empty">
                {t('Claim_inspector.source_unavailable')}
              </p>
            )}
          </div>
        </>
      )}
    </aside>
  );
}
