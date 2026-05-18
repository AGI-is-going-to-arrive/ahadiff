import './ClaimBadge.css';
import { useTranslation } from '../i18n/useTranslation';

export type ClaimVerdict =
  | 'verified'
  | 'weak'
  | 'not_proven'
  | 'contradicted'
  | 'rejected';

interface ClaimBadgeProps {
  verdict: ClaimVerdict;
}

const verdictClassMap: Record<ClaimVerdict, string> = {
  verified: 'claim-badge--verified',
  weak: 'claim-badge--weak',
  not_proven: 'claim-badge--not-proven',
  contradicted: 'claim-badge--contradicted',
  rejected: 'claim-badge--rejected',
};

// Per WCAG 1.4.1 (Use of Color), pair the color with a glyph so the verdict
// remains distinguishable in monochrome / forced-colors / printed output. The
// glyph is decorative (aria-hidden) since the localized label already carries
// the semantic meaning.
const verdictGlyphMap: Record<ClaimVerdict, string> = {
  verified: '✓',
  weak: '◆',
  not_proven: '○',
  contradicted: '✕',
  rejected: '⊘',
};

export default function ClaimBadge({ verdict }: ClaimBadgeProps) {
  const { t } = useTranslation();
  const cls = verdictClassMap[verdict] ?? 'claim-badge--not-proven';
  const glyph = verdictGlyphMap[verdict] ?? verdictGlyphMap.not_proven;
  const stampClass = verdict === 'verified' ? ' badge-stamp' : '';
  return (
    <span className={`claim-badge ${cls}${stampClass}`}>
      <span aria-hidden="true" className="claim-badge__glyph">{glyph}</span>
      {t(`Claim.${verdict}`)}
    </span>
  );
}
