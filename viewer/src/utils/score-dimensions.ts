export const DIMENSION_ORDER = [
  'accuracy',
  'evidence',
  'diff_coverage',
  'learnability',
  'quiz_transfer',
  'spec_alignment',
  'conciseness',
  'safety_privacy',
] as const;

export const DIM_I18N_KEYS: Record<string, string> = {
  accuracy: 'Ratchet.dim_accuracy',
  evidence: 'Ratchet.dim_evidence',
  diff_coverage: 'Ratchet.dim_diff_coverage',
  learnability: 'Ratchet.dim_learnability',
  quiz_transfer: 'Ratchet.dim_quiz_transfer',
  spec_alignment: 'Ratchet.dim_spec_alignment',
  conciseness: 'Ratchet.dim_conciseness',
  safety_privacy: 'Ratchet.dim_safety_privacy',
};

export const DIM_HINT_KEYS: Record<string, string> = {
  accuracy: 'Ratchet.dim_accuracy_hint',
  evidence: 'Ratchet.dim_evidence_hint',
  diff_coverage: 'Ratchet.dim_diff_coverage_hint',
  learnability: 'Ratchet.dim_learnability_hint',
  quiz_transfer: 'Ratchet.dim_quiz_transfer_hint',
  spec_alignment: 'Ratchet.dim_spec_alignment_hint',
  conciseness: 'Ratchet.dim_conciseness_hint',
  safety_privacy: 'Ratchet.dim_safety_privacy_hint',
};
