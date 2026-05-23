import { describe, expect, it } from 'vitest';
import { judgeReportSchema } from './JudgeReport';

const validJudgeReport = {
  artifact: 'llm_judge',
  schema_version: 1,
  run_id: 'run_0123456789abcdef0123456789abcdef',
  source_ref: 'HEAD',
  source_kind: 'git_ref',
  model_id: 'gpt-5.5',
  provider_class: 'openai_responses',
  prompt_fingerprint: 'prompt123',
  eval_bundle_version: 'bundle-v1',
  overall: 87.78,
  dimensions: {
    accuracy: {
      score: 18,
      max_score: 20,
      reason: 'strong claim verification',
    },
    spec_alignment: {
      score: 0,
      max_score: 0,
      reason: 'not applicable in deterministic score',
    },
  },
  usage: {
    input_tokens: 11,
    output_tokens: 22,
  },
  finish_reason: null,
  request_id: null,
  notes: ['advisory only'],
};

describe('JudgeReport schema', () => {
  it('accepts the current LlmJudgeReport.to_payload artifact shape', () => {
    const parsed = judgeReportSchema.parse(validJudgeReport);

    expect(parsed.artifact).toBe('llm_judge');
    expect(parsed.dimensions.spec_alignment?.max_score).toBe(0);
    expect(parsed.usage.input_tokens).toBe(11);
  });

  it('keeps the judge artifact schema strict', () => {
    expect(() => judgeReportSchema.parse({ ...validJudgeReport, extra: true })).toThrow();
    expect(() =>
      judgeReportSchema.parse({
        ...validJudgeReport,
        dimensions: {
          accuracy: {
            score: 18,
            max_score: 20,
            reason: 'ok',
            extra: true,
          },
        },
      }),
    ).toThrow();
  });

  it('rejects invalid judge dimension and usage numbers', () => {
    expect(() =>
      judgeReportSchema.parse({
        ...validJudgeReport,
        dimensions: {
          accuracy: {
            score: 21,
            max_score: 20,
            reason: 'bad',
          },
        },
      }),
    ).toThrow();
    expect(() =>
      judgeReportSchema.parse({
        ...validJudgeReport,
        usage: {
          input_tokens: -1,
          output_tokens: 22,
        },
      }),
    ).toThrow();
  });
});
