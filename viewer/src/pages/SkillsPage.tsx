import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import Skeleton from '../components/Skeleton';
import { getInstallTargets } from '../api/config';
import type { InstallTarget } from '../api/config';
import { useTranslation } from '../i18n/useTranslation';
import '../components/Skills.css';

const INSTALL_COMMANDS: Record<string, string> = {
  claude: 'ahadiff install claude',
  codex: 'ahadiff install codex',
  gemini: 'ahadiff install gemini',
  opencode: 'ahadiff install opencode',
  cursor: 'ahadiff install cursor',
  windsurf: 'ahadiff install windsurf',
  copilot: 'ahadiff install copilot',
  continue: 'ahadiff install continue',
  aider: 'ahadiff install aider',
  cline: 'ahadiff install cline',
  roo: 'ahadiff install roo',
  hooks: 'ahadiff install hooks',
  'github-action': 'ahadiff install github-action',
};

const AGENT_ICONS: Record<string, string> = {
  claude: '🤖', codex: '⌨', gemini: '✨', opencode: '📦',
  cursor: '🖱', windsurf: '🏄', copilot: '🤝', continue: '▶',
  aider: '🛠', cline: '📝', roo: '🦘', hooks: '🪝', 'github-action': '🔄',
};

export default function SkillsPage() {
  const { t } = useTranslation();
  type SkillFilter = 'all' | 'installed' | 'available' | 'unsupported';
  const [targets, setTargets] = useState<InstallTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<SkillFilter>('all');
  const [selected, setSelected] = useState<InstallTarget | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const selectedCardRef = useRef<HTMLDivElement>(null);

  const filterCounts = useMemo(() => {
    const counts = { all: targets.length, installed: 0, available: 0, unsupported: 0 };
    for (const t of targets) {
      if (t.status === 'installed') counts.installed++;
      else if (t.status === 'available') counts.available++;
      else counts.unsupported++;
    }
    return counts;
  }, [targets]);

  const filtered = filter === 'all' ? targets : targets.filter((tgt) =>
    filter === 'unsupported' ? (tgt.status === 'unsupported' || tgt.status === 'error') : tgt.status === filter
  );

  const fetchTargets = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const res = await getInstallTargets({ signal: controller.signal });
      if (!controller.signal.aborted) setTargets(res.targets);
    } catch (e) {
      if (controller.signal.aborted) return;
      setError(e instanceof Error ? e.message : 'fetch_failed');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchTargets();
    return () => abortRef.current?.abort();
  }, [fetchTargets]);

  if (loading) {
    return (
      <AppShell>
        <div className="skills" role="status" aria-label={t('A11y.loading')}>
          <div className="skills__head">
            <Skeleton variant="text" width="250px" height="2em" />
          </div>
          <div className="agent-grid">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} variant="card" height="160px" />
            ))}
          </div>
        </div>
      </AppShell>
    );
  }

  if (error) {
    return (
      <AppShell>
        <div className="skills">
          <div className="skills__head">
            <h1 className="skills__title">{t('Skills.title')}</h1>
          </div>
          <div role="alert" className="dashboard__error">
            {t('Error.fetch_failed', { resource: t('Skills.title') })}
            <button type="button" className="retry-btn" onClick={() => void fetchTargets()}>
              {t('Error.retry')}
            </button>
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="skills">
        <div className="skills__head">
          <div>
            <div className="review__eyebrow">§ {t('Skills.title')}</div>
            <h1 className="skills__title">{t('Skills.title')}</h1>
            <div className="ratchet-page__sub">{t('Skills.subtitle')}</div>
          </div>
        </div>

        <div className="skills__filters" role="group" aria-label={t('Skills.filter_label')}>
          {(['all', 'installed', 'available', 'unsupported'] as const).map((f) => (
            <button
              key={f}
              type="button"
              className={`skills__filter-chip${filter === f ? ' skills__filter-chip--active' : ''}`}
              onClick={() => { setFilter(f); setSelected(null); }}
              aria-pressed={filter === f}
            >
              {t(`Skills.filter_${f}`)} <span className="skills__filter-count">{filterCounts[f]}</span>
            </button>
          ))}
        </div>

        <div className={`skills__layout${selected ? '' : ' skills__layout--no-aside'}`}>
          <div className="agent-grid">
            {filtered.map((target) => (
              <AgentCard
                key={target.name}
                target={target}
                t={t}
                selected={selected?.name === target.name}
                onSelect={() => setSelected(target)}
                cardRef={selected?.name === target.name ? selectedCardRef : undefined}
              />
            ))}
            {filtered.length === 0 && (
              <p className="u-muted-sm">{t('Skills.filter_empty')}</p>
            )}
          </div>
          {selected && (
            <aside className="skill-preview" aria-label={t('Skills.preview_title')}>
              <div className="skill-preview__header">
                <h2>{selected.display_name || selected.name}</h2>
                <button
                  type="button"
                  className="skill-preview__close"
                  onClick={() => {
                    const returnTarget = selectedCardRef.current;
                    setSelected(null);
                    requestAnimationFrame(() => {
                      returnTarget?.focus();
                    });
                  }}
                  aria-label={t('Skills.preview_close')}
                >
                  ×
                </button>
              </div>
              <span className={`skill-preview__status skill-preview__status--${selected.status}`}>
                {t(`Skills.status_${selected.status}`)}
              </span>
              {selected.description && <p className="skill-preview__desc">{selected.description}</p>}
              {selected.error_message && <p className="skill-preview__error">{selected.error_message}</p>}
              {selected.platform_supported && INSTALL_COMMANDS[selected.name] && (
                <div className="skill-preview__install">
                  <code>{INSTALL_COMMANDS[selected.name]}</code>
                </div>
              )}
            </aside>
          )}
        </div>
      </div>
    </AppShell>
  );
}

function AgentCard({
  target,
  t,
  selected,
  onSelect,
  cardRef,
}: {
  target: InstallTarget;
  t: (key: string, params?: Record<string, string | number>) => string;
  selected: boolean;
  onSelect: () => void;
  cardRef?: React.Ref<HTMLDivElement>;
}) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cmd = INSTALL_COMMANDS[target.name] ?? `ahadiff install ${target.name}`;

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(cmd);
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        setCopied(false);
        timerRef.current = null;
      }, 1400);
    } catch {
      // clipboard API not available
    }
  }, [cmd]);

  const statusClass = target.status === 'error' ? 'unsupported' : target.status;

  return (
    <div
      ref={cardRef}
      className={`agent-card${selected ? ' agent-card--selected' : ''}`}
      onClick={onSelect}
      aria-current={selected || undefined}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.currentTarget !== e.target) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="agent-card__top">
        <div className={`agent-card__mark${target.status === 'installed' ? ' agent-card__mark--installed' : ''}`}>
          {AGENT_ICONS[target.name] ?? '📦'}
        </div>
        <span className={`agent-card__status agent-card__status--${statusClass}`}>
          {t(`Skills.status_${target.status}`)}
        </span>
      </div>
      <h2 className="agent-card__name">{target.display_name || target.name}</h2>
      <div className="agent-card__desc">{target.description}</div>
      {target.platform_supported && (
        <div className="agent-card__cmd">
          <span className="agent-card__cmd-text">{cmd}</span>
          <button
            type="button"
            className={`copy-btn${copied ? ' copy-btn--copied' : ''}`}
            onClick={(e) => { e.stopPropagation(); void handleCopy(); }}
          >
            {copied ? t('Skills.copied') : t('Skills.copy')}
          </button>
        </div>
      )}
    </div>
  );
}
