import { memo, useEffect, useMemo, useState } from 'react';
import { useTranslation } from '../i18n/useTranslation';
import ClaimBadge from './ClaimBadge';
import type { ClaimVerdict } from './ClaimBadge';
import EvidencePanel from './EvidencePanel';
import type { Claim } from './EvidencePanel';
import InfoHint from './InfoHint';
import type { DiffSourceLine } from './DiffView';
import './ClaimInspector.css';

export type ClaimInspectorClaim = Claim & {
  source_lines?: ReadonlyArray<DiffSourceLine>;
  source_line_groups?: ReadonlyArray<ClaimSourceLineGroup>;
  confidence?: number;
  concepts?: ReadonlyArray<string>;
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
  /**
   * Optional handler invoked when the user clicks a "Jump to code" link.
   * Receives the claim's file path, 1-based line number, and optional source
   * side so the caller can scroll the diff viewport to the corresponding line.
   */
  onJumpToCode?: (file: string, line: number, side?: 'old' | 'new' | 'either') => void;
}

type ClaimFilter = 'shipped' | 'verified' | 'weak' | 'not_proven' | 'rejected';

interface DisplayConcept {
  key: string;
  label: string;
}

const CLAIM_FILTERS: ReadonlyArray<ClaimFilter> = [
  'shipped',
  'verified',
  'weak',
  'not_proven',
  'rejected',
];

const SHIPPED_VERDICTS = new Set<ClaimVerdict>(['verified', 'weak', 'not_proven']);
const REJECTED_VERDICTS = new Set<ClaimVerdict>(['contradicted', 'rejected']);

/** Truncated line length for collapsed claim cards (approx one line at 28vw). */
const COLLAPSED_SUMMARY_LIMIT = 96;

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
  const side = group.side === 'old' || group.side === 'new' ? ` · ${group.side}` : '';
  return `${group.file}:${group.line_start}${range}${side}`;
}

function truncateSummary(text: string, limit: number): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  if (flat.length <= limit) return flat;
  return `${flat.slice(0, limit - 1).trimEnd()}…`;
}

function formatConfidence(value: number): string {
  return value.toFixed(2);
}

function isDisplayableConfidence(value: number): boolean {
  return Number.isFinite(value) && value >= 0 && value <= 1;
}

function getFilterForClaim(claim: ClaimInspectorClaim): ClaimFilter {
  if (claim.verdict === 'verified') return 'verified';
  if (claim.verdict === 'weak') return 'weak';
  if (claim.verdict === 'not_proven') return 'not_proven';
  return 'rejected';
}

function getDefaultFilter(claims: ReadonlyArray<ClaimInspectorClaim>): ClaimFilter {
  if (claims.some((claim) => SHIPPED_VERDICTS.has(claim.verdict))) {
    return 'shipped';
  }
  return claims[0] ? getFilterForClaim(claims[0]) : 'shipped';
}

function claimMatchesFilter(claim: ClaimInspectorClaim, filter: ClaimFilter): boolean {
  if (filter === 'shipped') return SHIPPED_VERDICTS.has(claim.verdict);
  if (filter === 'rejected') return REJECTED_VERDICTS.has(claim.verdict);
  return claim.verdict === filter;
}

function getFilterLabel(filter: ClaimFilter, t: (key: string) => string): string {
  if (filter === 'shipped') return t('Claim_inspector.filter_shipped');
  if (filter === 'rejected') return t('Claim.rejected');
  return t(`Claim.${filter}`);
}

function getDisplayConcepts(concepts?: ReadonlyArray<string>): DisplayConcept[] {
  if (!concepts) return [];
  const seen = new Set<string>();
  const result: DisplayConcept[] = [];
  for (const raw of concepts) {
    const label = raw.trim();
    if (!label) continue;
    const key = label.normalize('NFC');
    if (seen.has(key)) continue;
    seen.add(key);
    result.push({ key, label });
  }
  return result;
}

function countByFilter(
  claims: ClaimInspectorClaim[],
): Record<ClaimFilter, number> {
  const counts: Record<ClaimFilter, number> = {
    shipped: 0,
    verified: 0,
    weak: 0,
    not_proven: 0,
    rejected: 0,
  };
  for (const claim of claims) {
    if (SHIPPED_VERDICTS.has(claim.verdict)) counts.shipped += 1;
    if (claim.verdict === 'verified') counts.verified += 1;
    if (claim.verdict === 'weak') counts.weak += 1;
    if (claim.verdict === 'not_proven') counts.not_proven += 1;
    if (REJECTED_VERDICTS.has(claim.verdict)) counts.rejected += 1;
  }
  return counts;
}

export default memo(function ClaimInspector({
  claims = [],
  selectedClaimId = null,
  onSelect,
  onCopyAnchor,
  onJumpToCode,
}: ClaimInspectorProps) {
  const { t } = useTranslation();
  const [activeFilter, setActiveFilter] = useState<ClaimFilter>(() => getDefaultFilter(claims));

  useEffect(() => {
    setActiveFilter(getDefaultFilter(claims));
  }, [claims]);

  useEffect(() => {
    if (!selectedClaimId) return;
    const selected = claims.find((claim) => claim.claim_id === selectedClaimId);
    if (selected && !claimMatchesFilter(selected, activeFilter)) {
      setActiveFilter(getFilterForClaim(selected));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- only react to selection changes, not filter changes
  }, [claims, selectedClaimId]);

  const counts = useMemo(() => countByFilter(claims), [claims]);

  const filteredClaims = useMemo(
    () => claims.filter((claim) => claimMatchesFilter(claim, activeFilter)),
    [claims, activeFilter],
  );

  const selectedClaim = selectedClaimId
    ? filteredClaims.find((c) => c.claim_id === selectedClaimId) ?? null
    : null;
  const selectedSourceGroups = selectedClaim?.source_line_groups ?? [];
  const selectedJumpTargets: ReadonlyArray<ClaimSourceLineGroup> = selectedClaim
    ? selectedSourceGroups.length > 0
      ? selectedSourceGroups
      : hasSourceHunk(selectedClaim)
        ? [
            {
              file: selectedClaim.file,
              line_start: selectedClaim.line_start,
              line_end: selectedClaim.line_end,
              lines: [],
            },
          ]
        : []
    : [];
  const selectedConcepts = getDisplayConcepts(selectedClaim?.concepts);

  if (claims.length === 0 && !selectedClaim) {
    return (
      <aside
        className="claim-inspector claim-inspector--empty"
        aria-label={t('Claim_inspector.title')}
      >
        <header className="claim-inspector__header">
          <h2 className="claim-inspector__title">{t('Claim_inspector.title')}</h2>
          <InfoHint label={t('Claim_inspector.onboarding_what_is_claim')} />
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
        <InfoHint label={t('Claim_inspector.onboarding_what_is_claim')} />
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

      {/* Onboarding hint shown only when no claim is selected. */}
      {!selectedClaim && (
        <p className="claim-inspector__onboarding" role="note">
          {t('Claim_inspector.onboarding_hint')}
        </p>
      )}

      {/* Filter chips */}
      {claims.length > 1 && (
        <div className="claim-inspector__filters" role="toolbar" aria-label={t('Claim_inspector.filter_label')}>
          {CLAIM_FILTERS.map((filter) => {
            const count = counts[filter] ?? 0;
            if (count === 0) return null;
            const isActive = filter === activeFilter;
            return (
              <button
                key={filter}
                type="button"
                className={`claim-inspector__chip${isActive ? ' claim-inspector__chip--on' : ''} claim-inspector__chip--${filter}`}
                aria-pressed={isActive}
                onClick={() => setActiveFilter(filter)}
              >
                {getFilterLabel(filter, t)}
                <span className="claim-inspector__chip-count">{count}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Claim list */}
      {filteredClaims.length > 0 && (
        <section className="claim-inspector__list" aria-label={t('Claim_inspector.list_title')}>
          <ul className="claim-inspector__list-items">
            {filteredClaims.map((claim) => {
              const isSelected = claim.claim_id === selectedClaimId;
              return (
                <li key={claim.claim_id}>
                  <button
                    type="button"
                    id={`claim-${claim.claim_id}`}
                    className={`claim-inspector__item claim-inspector__item--${claim.verdict}${isSelected ? ' claim-inspector__item--selected' : ''}${isSelected ? ' claim-inspector__item--expanded' : ' claim-inspector__item--collapsed'}`}
                    aria-pressed={isSelected}
                    onClick={() => onSelect?.(claim.claim_id)}
                  >
                    <div className="claim-inspector__item-row">
                      <span className="claim-inspector__item-id">{claim.claim_id}</span>
                      <ClaimBadge verdict={claim.verdict} />
                    </div>
                    <p
                      className={
                        isSelected
                          ? 'claim-inspector__item-text'
                          : 'claim-inspector__item-text claim-inspector__item-text--collapsed'
                      }
                    >
                      {isSelected
                        ? claim.statement
                        : truncateSummary(claim.statement, COLLAPSED_SUMMARY_LIMIT)}
                    </p>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {filteredClaims.length === 0 && (
        <p className="claim-inspector__empty" role="status">
          {t('Claim_inspector.filter_no_results')}
        </p>
      )}

      {/* Selected claim detail */}
      {selectedClaim && (
        <div className="claim-inspector__detail" aria-live="polite">
          <div className="claim-inspector__row">
            <span className="claim-inspector__row-label">
              {t('Claim_inspector.status_label')}
            </span>
            <ClaimBadge verdict={selectedClaim.verdict} />
            {selectedClaim.confidence != null &&
              isDisplayableConfidence(selectedClaim.confidence) && (
                <span className="claim-inspector__conf-score">
                  {t('Claim_inspector.confidence_short')}{' '}
                  {formatConfidence(selectedClaim.confidence)}
                </span>
              )}
          </div>

          <EvidencePanel claim={selectedClaim} />

          {selectedConcepts.length > 0 && (
            <div className="claim-inspector__concepts-row">
              <span className="claim-inspector__row-label">
                {t('Claim_inspector.concepts_label')}
              </span>
              <div className="claim-inspector__concepts-list">
                {selectedConcepts.map((concept) => (
                  <span
                    key={concept.key}
                    className="claim-inspector__concept-tag"
                    title={concept.label}
                  >
                    {concept.label}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Jump-to-code links replace the in-panel source code preview. The
              full source hunk is rendered in the .diff-page__selected-hunk
              section below the diff, avoiding horizontal scroll inside this
              narrow panel. */}
          {selectedJumpTargets.length > 0 ? (
            <div className="claim-inspector__jumps">
              <span className="claim-inspector__row-label">
                {t('Claim_inspector.source_hunk_title')}
              </span>
              <ul className="claim-inspector__jump-list">
                {selectedJumpTargets.map((group, index) => {
                  const ref = formatSourceGroupRef(group);
                  return (
                    <li key={`${ref}-${index}`}>
                      <button
                        type="button"
                        className="claim-inspector__jump-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          onJumpToCode?.(group.file, group.line_start, group.side);
                        }}
                        aria-label={`${t('Claim_inspector.jump_to_code')}: ${ref}`}
                        disabled={!onJumpToCode}
                      >
                        <span aria-hidden="true" className="claim-inspector__jump-icon">
                          ➥
                        </span>
                        <code className="claim-inspector__jump-ref">{ref}</code>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : (
            hasSourceHunk(selectedClaim) ? null : (
              <p className="claim-inspector__source-empty">
                {t('Claim_inspector.source_unavailable')}
              </p>
            )
          )}

          {/* Backwards-compat ref for selected-claim location (kept so callers
              that read the existing source ref formatter from props still see
              the value). */}
          {hasSourceHunk(selectedClaim) && selectedJumpTargets.length === 0 && (
            <code className="claim-inspector__item-loc">{formatSourceRef(selectedClaim)}</code>
          )}
        </div>
      )}
    </aside>
  );
});
