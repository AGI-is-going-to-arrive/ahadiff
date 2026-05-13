import { useCallback, useRef } from 'react';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';

export type ScaffoldLevel = 'full' | 'hint' | 'compact';

interface ScaffoldingTabsProps {
  level: ScaffoldLevel;
  onChange: (level: ScaffoldLevel) => void;
  idBase?: string;
  panelId?: string;
}

const LEVELS: ScaffoldLevel[] = ['compact', 'hint', 'full'];

const levelKeyMap: Record<ScaffoldLevel, MessageKey> = {
  full: 'Lesson.level_full',
  hint: 'Lesson.level_hint',
  compact: 'Lesson.level_compact',
};

const hintKeyMap: Record<ScaffoldLevel, MessageKey> = {
  full: 'Lesson.level_full_hint',
  hint: 'Lesson.level_hint_hint',
  compact: 'Lesson.level_compact_hint',
};

export default function ScaffoldingTabs({
  level,
  onChange,
  idBase = 'scaffolding-tab',
  panelId,
}: ScaffoldingTabsProps) {
  const { t } = useTranslation();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLButtonElement>) => {
      const idx = LEVELS.indexOf(level);
      let newIndex = -1;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        newIndex = (idx + 1) % LEVELS.length;
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        newIndex = (idx - 1 + LEVELS.length) % LEVELS.length;
      } else if (e.key === 'Home') {
        e.preventDefault();
        newIndex = 0;
      } else if (e.key === 'End') {
        e.preventDefault();
        newIndex = LEVELS.length - 1;
      } else if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        const target = e.currentTarget;
        const focused = tabRefs.current.indexOf(target);
        if (focused >= 0) onChange(LEVELS[focused]);
        return;
      }
      if (newIndex >= 0) {
        onChange(LEVELS[newIndex]);
        tabRefs.current[newIndex]?.focus();
      }
    },
    [level, onChange],
  );

  return (
    <div className="scaffolding-tabs-wrapper">
      <div className="scaffolding-tabs" role="tablist" aria-label={t('Lesson.title')}>
        {LEVELS.map((lvl, i) => {
          const selected = lvl === level;
          return (
            <button
              key={lvl}
              id={`${idBase}-${lvl}`}
              ref={(el) => { tabRefs.current[i] = el; }}
              role="tab"
              aria-selected={selected}
              aria-controls={panelId}
              aria-describedby={selected ? 'scaffolding-hint' : undefined}
              tabIndex={selected ? 0 : -1}
              title={t(hintKeyMap[lvl])}
              className={`scaffolding-tab${selected ? ' scaffolding-tab--active' : ''}`}
              onClick={() => onChange(lvl)}
              onKeyDown={handleKeyDown}
            >
              {t(levelKeyMap[lvl])}
            </button>
          );
        })}
      </div>
      <p className="scaffolding-hint" id="scaffolding-hint" aria-live="polite">
        {t(hintKeyMap[level])}
      </p>
    </div>
  );
}
