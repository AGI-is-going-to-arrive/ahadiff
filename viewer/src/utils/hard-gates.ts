import type { ScoreHardGate } from '../api/types';
import type { TranslateFn } from '../i18n/useTranslation';

const HARD_GATE_I18N_KEYS: Record<string, string> = {
  accuracy: 'Lesson.score_gate_accuracy',
  evidence: 'Lesson.score_gate_evidence',
  contradicted_claims: 'Lesson.score_gate_contradicted_claims',
  evidence_coverage: 'Lesson.score_gate_evidence_coverage',
  secret_leak: 'Lesson.score_gate_secret_leak',
  injection_unresolved: 'Lesson.score_gate_injection_unresolved',
  critical_safety_findings: 'Lesson.score_gate_critical_safety_findings',
};

export function formatHardGateName(t: TranslateFn, name: string): string {
  return t(HARD_GATE_I18N_KEYS[name] ?? name.replaceAll('_', ' '));
}

export function formatHardGateDetail(
  t: TranslateFn,
  name: string,
  gate: ScoreHardGate,
): string {
  if (
    name === 'evidence_coverage'
    && typeof gate.score === 'number'
    && Number.isFinite(gate.score)
    && typeof gate.threshold === 'number'
    && Number.isFinite(gate.threshold)
  ) {
    return t('Lesson.score_gate_evidence_coverage_detail', {
      score: gate.score.toFixed(2),
      threshold: gate.threshold.toFixed(2),
    });
  }
  return gate.detail;
}
