import { useCallback, useEffect, useRef, useState } from 'react';
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
  const [targets, setTargets] = useState<InstallTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

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

        <div className="agent-grid">
          {targets.map((target) => (
            <AgentCard key={target.name} target={target} t={t} />
          ))}
        </div>
      </div>
    </AppShell>
  );
}

function AgentCard({
  target,
  t,
}: {
  target: InstallTarget;
  t: (key: string, params?: Record<string, string | number>) => string;
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

  const statusClass = target.detected
    ? 'installed'
    : target.platform_supported
      ? 'available'
      : 'unsupported';

  return (
    <div className="agent-card">
      <div className="agent-card__top">
        <div className={`agent-card__mark${target.detected ? ' agent-card__mark--installed' : ''}`}>
          {AGENT_ICONS[target.name] ?? '📦'}
        </div>
        <span className={`agent-card__status agent-card__status--${statusClass}`}>
          {t(`Skills.${statusClass}`)}
        </span>
      </div>
      <div className="agent-card__name">{target.name}</div>
      <div className="agent-card__desc">{target.description}</div>
      {target.platform_supported && (
        <div className="agent-card__cmd">
          <span className="agent-card__cmd-text">{cmd}</span>
          <button
            type="button"
            className={`copy-btn${copied ? ' copy-btn--copied' : ''}`}
            onClick={() => { void handleCopy(); }}
          >
            {copied ? t('Skills.copied') : t('Skills.copy')}
          </button>
        </div>
      )}
    </div>
  );
}
