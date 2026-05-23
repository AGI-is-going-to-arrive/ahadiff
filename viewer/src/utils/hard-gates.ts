import type { ScoreHardGate } from '../api/types';
import type { MessageKey, TranslateFn } from '../i18n/useTranslation';

const HARD_GATE_I18N_KEYS: Record<string, MessageKey> = {
  accuracy: 'Lesson.score_gate_accuracy' as MessageKey,
  evidence: 'Lesson.score_gate_evidence' as MessageKey,
  contradicted_claims: 'Lesson.score_gate_contradicted_claims' as MessageKey,
  evidence_coverage: 'Lesson.score_gate_evidence_coverage' as MessageKey,
  secret_leak: 'Lesson.score_gate_secret_leak' as MessageKey,
  injection_unresolved: 'Lesson.score_gate_injection_unresolved' as MessageKey,
  critical_safety_findings: 'Lesson.score_gate_critical_safety_findings' as MessageKey,
};

export function formatHardGateName(t: TranslateFn, name: string): string {
  const key = HARD_GATE_I18N_KEYS[name];
  return key ? t(key) : name.replaceAll('_', ' ');
}

export function formatHardGateDetail(
  t: TranslateFn,
  name: string,
  gate: ScoreHardGate,
): string {
  if (
    gate.policy?.kind === 'adaptive_threshold'
    && typeof gate.score === 'number'
    && Number.isFinite(gate.score)
    && typeof gate.threshold === 'number'
    && Number.isFinite(gate.threshold)
  ) {
    const regimeKey = `Lesson.score_gate_regime_${gate.policy.regime}` as MessageKey;
    return t('Lesson.score_gate_adaptive_detail' as MessageKey, {
      score: gate.score.toFixed(2),
      threshold: gate.threshold.toFixed(2),
      regime: t(regimeKey),
      ratio: (gate.policy.ratio * 100).toFixed(0),
      files: String(gate.policy.basis.visible_files),
      hunks: String(gate.policy.basis.visible_hunks),
      lines: String(gate.policy.basis.visible_changed_lines),
    });
  }
  if (
    name === 'evidence_coverage'
    && typeof gate.score === 'number'
    && Number.isFinite(gate.score)
    && typeof gate.threshold === 'number'
    && Number.isFinite(gate.threshold)
  ) {
    return t('Lesson.score_gate_evidence_coverage_detail' as MessageKey, {
      score: gate.score.toFixed(2),
      threshold: gate.threshold.toFixed(2),
    });
  }
  return gate.detail;
}
