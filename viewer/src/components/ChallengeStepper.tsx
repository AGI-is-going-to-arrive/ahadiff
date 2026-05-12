import { useTranslation } from '../i18n/useTranslation';
import { CHALLENGE_STAGES, type ChallengeStage } from '../api/challenge';

interface ChallengeStepperProps {
  current: ChallengeStage;
}

type SteppedStage = Exclude<ChallengeStage, 'idle'>;

const STAGE_LABEL_KEYS: Record<SteppedStage, string> = {
  build: 'Challenge.stage_build',
  tour: 'Challenge.stage_tour',
  challenge: 'Challenge.stage_challenge',
  review: 'Challenge.stage_review',
  adapt: 'Challenge.stage_adapt',
};

function stageRank(stage: ChallengeStage): number {
  if (stage === 'idle') return -1;
  return (CHALLENGE_STAGES as readonly ChallengeStage[]).indexOf(stage);
}

export default function ChallengeStepper({ current }: ChallengeStepperProps) {
  const { t } = useTranslation();
  const currentIndex = stageRank(current);

  return (
    <ol className="challenge-stepper" aria-label={t('Challenge.current_stage')}>
      {CHALLENGE_STAGES.map((stage, index) => {
        const status =
          currentIndex < 0
            ? 'pending'
            : index < currentIndex
              ? 'complete'
              : index === currentIndex
                ? 'current'
                : 'pending';
        const isCurrent = status === 'current';
        return (
          <li
            key={stage}
            className={`challenge-stepper__step challenge-stepper__step--${status}`}
            aria-current={isCurrent ? 'step' : undefined}
          >
            <span className="challenge-stepper__marker" aria-hidden="true">
              {status === 'complete' ? (
                <svg
                  viewBox="0 0 16 16"
                  width="12"
                  height="12"
                  role="presentation"
                  focusable="false"
                >
                  <path
                    d="M3 8.5l3 3 7-7"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              ) : (
                <span className="challenge-stepper__index">{index + 1}</span>
              )}
            </span>
            <span className="challenge-stepper__label">{t(STAGE_LABEL_KEYS[stage])}</span>
          </li>
        );
      })}
    </ol>
  );
}
