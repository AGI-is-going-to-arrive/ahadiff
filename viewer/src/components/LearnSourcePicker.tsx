import type { ReactElement } from 'react';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import './LearnSourcePicker.css';

export type LearnSource = 'git' | 'files' | 'patch' | 'snapshot' | 'document';

const SOURCES: ReadonlyArray<{
  source: LearnSource;
  title: MessageKey;
  description: MessageKey;
}> = [
  { source: 'git', title: 'LearnDialog.source_git', description: 'LearnDialog.source_git_hint' },
  { source: 'files', title: 'LearnDialog.source_files', description: 'LearnDialog.source_files_hint' },
  { source: 'patch', title: 'LearnDialog.source_patch', description: 'LearnDialog.source_patch_hint' },
  { source: 'snapshot', title: 'LearnDialog.source_snapshot', description: 'LearnDialog.source_snapshot_hint' },
  { source: 'document', title: 'LearnDialog.source_document', description: 'LearnDialog.source_document_hint' },
];

interface LearnSourcePickerProps {
  onSelect: (source: LearnSource) => void;
  selected?: LearnSource;
  disabled?: boolean;
}

export default function LearnSourcePicker({ onSelect, selected, disabled }: LearnSourcePickerProps): ReactElement {
  const { t } = useTranslation();
  return (
    <div className="learn-source-picker" role="group" aria-label={t('LearnDialog.subtitle')}>
      {SOURCES.map(({ source, title, description }) => (
        <button
          key={source}
          type="button"
          className="learn-source-picker__choice"
          data-learn-source={source}
          aria-pressed={selected === undefined ? undefined : selected === source}
          disabled={disabled}
          onClick={(event) => {
            // Safari does not focus buttons on pointer clicks by default.
            event.currentTarget.focus({ preventScroll: true });
            onSelect(source);
          }}
        >
          <span className="learn-source-picker__title">{t(title)}</span>
          <span className="learn-source-picker__description">{t(description)}</span>
        </button>
      ))}
    </div>
  );
}
