import { type Ref, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import Skeleton from '../components/Skeleton';
import {
  applyInstallTarget,
  getInstallTargets,
  previewInstallTarget,
  removeInstallTarget,
} from '../api/config';
import type { InstallManifestAction, InstallTarget } from '../api/config';
import { useTranslation } from '../i18n/useTranslation';
import '../components/Skills.css';

const AGENT_ICONS: Record<string, string> = {
  claude: '🤖', codex: '⌨', gemini: '✨', opencode: '📦',
  cursor: '🖱', windsurf: '🏄', copilot: '🤝', continue: '▶',
  aider: '🛠', cline: '📝', roo: '🦘', hooks: '🪝', 'github-action': '🔄',
};

type InstallActionKind = 'preview' | 'install' | 'uninstall';

interface InstallActionState {
  pending?: InstallActionKind;
  message?: string;
  error?: string;
}

export default function SkillsPage() {
  const { t } = useTranslation();
  type SkillFilter = 'all' | 'installed' | 'available' | 'unsupported';
  const [targets, setTargets] = useState<InstallTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<SkillFilter>('all');
  const [selected, setSelected] = useState<InstallTarget | null>(null);
  const [actionState, setActionState] = useState<Record<string, InstallActionState>>({});
  const abortRef = useRef<AbortController | null>(null);
  const selectedCardRef = useRef<HTMLButtonElement>(null);

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

  const upsertTarget = useCallback((target: InstallTarget) => {
    setTargets((current) => current.map((item) => (item.name === target.name ? target : item)));
    setSelected((current) => (current?.name === target.name ? target : current));
  }, []);

  const fetchTargets = useCallback(async (opts?: { silent?: boolean }) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    if (!opts?.silent) setLoading(true);
    setError(null);
    try {
      const res = await getInstallTargets({ signal: controller.signal });
      if (!controller.signal.aborted) {
        setTargets(res.targets);
        setSelected((current) => (
          current ? (res.targets.find((target) => target.name === current.name) ?? null) : null
        ));
      }
    } catch (e) {
      if (controller.signal.aborted) return;
      setError(e instanceof Error ? e.message : 'fetch_failed');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  const runAction = useCallback(async (target: InstallTarget, kind: InstallActionKind) => {
    setActionState((current) => ({
      ...current,
      [target.name]: { pending: kind },
    }));
    try {
      const preview = await previewInstallTarget(target.name);
      upsertTarget(preview.target);
      if (kind === 'preview') {
        setActionState((current) => ({
          ...current,
          [target.name]: { message: t('Skills.preview_success') },
        }));
        return;
      }
      const result = kind === 'install'
        ? await applyInstallTarget(target.name, preview.manifest_hash)
        : await removeInstallTarget(target.name, preview.manifest_hash);
      upsertTarget(result.target);
      setActionState((current) => ({
        ...current,
        [target.name]: {
          message: kind === 'install'
            ? t('Skills.install_success')
            : t('Skills.uninstall_success'),
        },
      }));
      await fetchTargets({ silent: true });
    } catch (e) {
      setActionState((current) => ({
        ...current,
        [target.name]: {
          error: e instanceof Error ? e.message : t('Skills.action_failed'),
        },
      }));
    }
  }, [fetchTargets, t, upsertTarget]);

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
              {selected.manifest_error && <p className="skill-preview__error">{selected.manifest_error}</p>}
              {selected.platform_supported && (
                <div className="skill-preview__install">
                  <div className="u-muted-sm">{t('Skills.install_cmd')}</div>
                  <code>{installCommand(selected)}</code>
                </div>
              )}
              {selected.platform_supported && (
                <div className="skill-preview__install">
                  <div className="u-muted-sm">{t('Skills.uninstall_cmd')}</div>
                  <code>{uninstallCommand(selected)}</code>
                </div>
              )}
              {selected.manifest && (
                <div className="skill-preview__install">
                  <div className="u-muted-sm">{t('Skills.manifest_preview')}</div>
                  <ManifestActions actions={selected.manifest.write} />
                </div>
              )}
              {selected.platform_supported && (
                <SkillPreviewActions
                  target={selected}
                  state={actionState[selected.name] ?? {}}
                  t={t}
                  onRun={(kind) => void runAction(selected, kind)}
                />
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
  cardRef?: Ref<HTMLButtonElement>;
}) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cmd = installCommand(target);

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
      className={`agent-card${selected ? ' agent-card--selected' : ''}`}
      onClick={onSelect}
      aria-current={selected || undefined}
    >
      <div className="agent-card__top">
        <div className={`agent-card__mark${target.status === 'installed' ? ' agent-card__mark--installed' : ''}`}>
          {AGENT_ICONS[target.name] ?? '📦'}
        </div>
        <span className={`agent-card__status agent-card__status--${statusClass}`}>
          {t(`Skills.status_${target.status}`)}
        </span>
      </div>
      <h2 className="agent-card__name">
        <button
          ref={cardRef}
          type="button"
          className="agent-card__name-btn"
          aria-current={selected || undefined}
        >
          {target.display_name || target.name}
        </button>
      </h2>
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

function installCommand(target: InstallTarget): string {
  return target.install_command ?? `ahadiff install ${target.name}`;
}

function uninstallCommand(target: InstallTarget): string {
  return target.uninstall_command ?? `ahadiff uninstall ${target.name}`;
}

function SkillPreviewActions({
  target,
  state,
  t,
  onRun,
}: {
  target: InstallTarget;
  state: InstallActionState;
  t: (key: string, params?: Record<string, string | number>) => string;
  onRun: (kind: InstallActionKind) => void;
}) {
  const isPending = state.pending != null;
  const primaryAction: InstallActionKind = target.status === 'installed' ? 'uninstall' : 'install';
  const primaryLabel = target.status === 'installed'
    ? t('Skills.uninstall_action')
    : t('Skills.install_action');
  return (
    <div className="skill-preview__actions">
      <button
        type="button"
        className="retry-btn"
        disabled={isPending || target.status === 'unsupported' || target.status === 'error'}
        onClick={() => onRun('preview')}
      >
        {state.pending === 'preview' ? t('Skills.previewing') : t('Skills.preview_action')}
      </button>
      <button
        type="button"
        className="btn-primary"
        disabled={isPending || target.status === 'unsupported' || target.status === 'error'}
        onClick={() => onRun(primaryAction)}
      >
        {state.pending === primaryAction
          ? (primaryAction === 'install' ? t('Skills.installing') : t('Skills.uninstalling'))
          : primaryLabel}
      </button>
      {state.message && (
        <div className="skill-preview__message" role="status">{state.message}</div>
      )}
      {state.error && (
        <div className="skill-preview__error" role="alert">{state.error}</div>
      )}
    </div>
  );
}

function ManifestActions({ actions }: { actions: InstallManifestAction[] }) {
  if (actions.length === 0) return <div className="u-muted-sm">-</div>;
  return (
    <ul className="u-muted-sm">
      {actions.map((action) => (
        <li key={`${action.action}:${action.path}`}>
          <code>{action.action}</code> {action.path}
        </li>
      ))}
    </ul>
  );
}
