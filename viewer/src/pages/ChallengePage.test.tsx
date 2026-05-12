import { describe, expect, it } from 'vitest';
import { ApiError } from '../api/client';
import {
  buildAdvanceFallbackEnvelope,
  deriveChallengeErrorMessage,
  renderChallengeErrorMessage,
} from './ChallengePage';

const t = (key: string, params?: Record<string, string | number>): string => {
  if (!params) return key;
  return Object.entries(params).reduce(
    (acc, [name, value]) => acc.replace(`{${name}}`, String(value)),
    `${key}:{resource}`,
  );
};

describe('ChallengePage error mapping', () => {
  it('uses stable backend ErrorCode keys only', () => {
    expect(
      deriveChallengeErrorMessage(
        new ApiError(404, { error_code: 'RUN_NOT_FOUND', error: 'missing' }),
      ),
    ).toEqual({ key: 'errors.RUN_NOT_FOUND' });

    expect(
      deriveChallengeErrorMessage(
        new ApiError(400, { error_code: 'INPUT_VALIDATION', error: 'bad input' }),
      ),
    ).toEqual({ key: 'errors.INPUT_VALIDATION' });

    expect(
      deriveChallengeErrorMessage(
        new ApiError(501, {
          error_code: 'FEATURE_UNAVAILABLE',
          error: 'feature disabled',
        }),
      ),
    ).toEqual({ key: 'errors.FEATURE_UNAVAILABLE' });
  });

  it('passes a Challenge resource when falling back to Error.fetch_failed', () => {
    const message = renderChallengeErrorMessage(
      t,
      deriveChallengeErrorMessage(new Error('network down')),
    );
    expect(message).toBe('Error.fetch_failed:Challenge.title');
  });

  it('keeps the advanced state if the follow-up envelope refresh fails', () => {
    const fallback = buildAdvanceFallbackEnvelope(
      {
        challenge_id: 'challenge-1',
        source_run_id: 'run-1',
        stage: 'tour',
      },
      {
        state: {
          challenge_id: 'challenge-1',
          source_run_id: 'run-1',
          stage: 'build',
        },
        manifest: {
          challenge_id: 'challenge-1',
          source_run_id: 'run-1',
          canonical_patch: 'diff --git a/a b/a',
        },
      },
    );

    expect(fallback.state.stage).toBe('tour');
    expect(fallback.manifest?.canonical_patch).toBe('diff --git a/a b/a');
  });
});
