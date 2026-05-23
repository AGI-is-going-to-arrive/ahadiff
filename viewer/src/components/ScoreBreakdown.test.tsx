import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ScorePayload } from '../api/types';
import ScoreBreakdown from './ScoreBreakdown';

const baseScorePayload: ScorePayload = {
  run_id: 'run_0123456789abcdef0123456789abcdef',
  source_ref: 'HEAD',
  source_kind: 'git_ref',
  capability_level: 3,
  degraded_flags: {},
  overall: 87.5,
  verdict: 'PASS',
  weakest_dim: 'accuracy',
  eval_bundle_version: 'bundle-v1',
  rubric_version: 'v0.1',
  dimensions: {
    spec_alignment: {
      score: 0,
      max_score: 0,
      reason: 'not applicable',
    },
  },
  hard_gates: {},
  notes: [],
};

describe('ScoreBreakdown', () => {
  it('renders non-applicable dimensions as N/A for visual and accessible output', () => {
    const html = renderToStaticMarkup(<ScoreBreakdown payload={baseScorePayload} />);

    expect(html).toContain('N/A');
    expect(html).toContain('role="img"');
    expect(html).toContain('Spec alignment: N/A');
    expect(html).not.toContain('role="meter"');
    expect(html).not.toContain('0.0 / 0');
  });

  it('renders adaptive hard gate policy detail through localized copy', () => {
    const html = renderToStaticMarkup(
      <ScoreBreakdown
        payload={{
          ...baseScorePayload,
          hard_gates: {
            accuracy: {
              passed: true,
              detail: 'accuracy score 11.90 >= 11.90; adaptive_ratio=0.85; regime=very_large',
              score: 11.9,
              threshold: 11.9,
              policy: {
                kind: 'adaptive_threshold',
                ratio: 0.85,
                regime: 'very_large',
                basis: {
                  visible_files: 44,
                  visible_hunks: 164,
                  visible_changed_lines: 2756,
                },
              },
            },
          },
        }}
      />,
    );

    expect(html).toContain('Adaptive threshold');
    expect(html).toContain('Very Large');
    expect(html).toContain('44 files');
    expect(html).toContain('164 hunks');
    expect(html).toContain('2756 lines');
  });
});
