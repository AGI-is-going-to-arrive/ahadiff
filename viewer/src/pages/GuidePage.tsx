import { lazy, Suspense, useCallback, useEffect, useMemo, useState, useRef } from 'react';
import {
  BookOpen,
  Brain,
  ChevronRight,
  ChevronDown,
  Code,
  ExternalLink,
  GraduationCap,
  Puzzle,
  RotateCcw,
  Settings,
  Terminal,
  TrendingUp,
  Wrench,
} from 'lucide-react';
import AppShell from '../components/AppShell';
import { CommandBlock } from '../components/CommandBlock';
import { getInstallTargets, type InstallTarget } from '../api/config';
import { useTranslation, type MessageKey, type TranslateFn } from '../i18n/useTranslation';
import { detectPlatform, getEnvVarCommand, type Platform } from '../utils/platform';
import UsagePanel from '../components/UsagePanel';
import LearnSourcePicker, { type LearnSource } from '../components/LearnSourcePicker';
import './GuidePage.css';

const LearnModeDialog = lazy(() => import('../components/LearnModeDialog'));

type IconType = typeof BookOpen;

interface WorkflowStep {
  icon: IconType;
  titleKey: MessageKey;
  descKey: MessageKey;
}

const WORKFLOW_STEPS: ReadonlyArray<WorkflowStep> = [
  {
    icon: BookOpen,
    titleKey: 'Guide.workflow_learn',
    descKey: 'Guide.workflow_learn_desc',
  },
  {
    icon: GraduationCap,
    titleKey: 'Guide.workflow_lesson',
    descKey: 'Guide.workflow_lesson_desc',
  },
  {
    icon: RotateCcw,
    titleKey: 'Guide.workflow_review',
    descKey: 'Guide.workflow_review_desc',
  },
  {
    icon: TrendingUp,
    titleKey: 'Guide.workflow_verify',
    descKey: 'Guide.workflow_verify_desc',
  },
];

interface CommandEntry {
  command: string;
  labelKey: MessageKey;
}

const CORE_COMMANDS: ReadonlyArray<CommandEntry> = [
  { command: 'pipx install ahadiff', labelKey: 'Guide.commands_install' },
  { command: 'pipx upgrade ahadiff', labelKey: 'Guide.commands_upgrade' },
  { command: 'ahadiff init', labelKey: 'Guide.commands_init' },
  {
    command: 'ahadiff learn HEAD~1..HEAD',
    labelKey: 'Guide.commands_learn',
  },
  {
    command: 'ahadiff learn --staged --unstaged --include-untracked',
    labelKey: 'Guide.commands_learn_worktree',
  },
  {
    command: 'ahadiff learn --staged',
    labelKey: 'Guide.commands_learn_staged',
  },
  {
    command: 'ahadiff learn --unstaged --include-untracked',
    labelKey: 'Guide.commands_learn_unstaged',
  },
  { command: 'ahadiff learn --last', labelKey: 'Guide.commands_learn_last' },
  {
    command: 'ahadiff learn --since "2 hours ago"',
    labelKey: 'Guide.commands_learn_since',
  },
  {
    command: 'ahadiff learn --patch change.diff',
    labelKey: 'Guide.commands_learn_patch',
  },
  {
    command: 'ahadiff learn --compare old.py new.py',
    labelKey: 'Guide.commands_learn_compare',
  },
  {
    command: 'ahadiff learn --document notes.md --force-learn',
    labelKey: 'Guide.commands_learn_document',
  },
  {
    command: 'ahadiff snapshot save before.py --name before-refactor',
    labelKey: 'Guide.commands_snapshot_save',
  },
  { command: 'ahadiff snapshot list', labelKey: 'Guide.commands_snapshot_list' },
  {
    command: 'ahadiff learn --snapshot SNAPSHOT_ID --after after.py --force-learn',
    labelKey: 'Guide.commands_learn_snapshot',
  },
  {
    command: 'ahadiff learn --compare old.py new.py --force-learn --active-practice',
    labelKey: 'Guide.commands_active_practice',
  },
  {
    command: 'ahadiff learn --compare-dir old/ new/',
    labelKey: 'Guide.commands_learn_compare_dir',
  },
  {
    command: 'ahadiff learn --patch-url https://example.com/change.diff',
    labelKey: 'Guide.commands_learn_patch_url',
  },
  { command: 'ahadiff serve', labelKey: 'Guide.commands_serve' },
  { command: 'ahadiff quiz RUN_ID', labelKey: 'Guide.commands_quiz' },
  { command: 'ahadiff review', labelKey: 'Guide.commands_review' },
  { command: 'ahadiff verify RUN_ID', labelKey: 'Guide.commands_verify' },
  {
    command: 'ahadiff improve --rounds 1',
    labelKey: 'Guide.commands_improve',
  },
];

function providerBaseUrlArg(platform: Platform): string {
  return platform === 'windows'
    ? '$env:AHADIFF_PROVIDER_BASE_URL'
    : '"$AHADIFF_PROVIDER_BASE_URL"';
}

function setupCommands(platform: Platform): ReadonlyArray<CommandEntry> {
  return [
    { command: 'ahadiff doctor', labelKey: 'Guide.setup_doctor' },
    { command: 'ahadiff config show --resolved', labelKey: 'Guide.setup_config' },
    {
      command:
        `ahadiff provider test --name gpt55 --provider-class openai_responses --base-url ${providerBaseUrlArg(platform)} --model gpt-5.5 --api-key-env AHADIFF_PROVIDER_API_KEY --privacy-mode explicit_remote`,
      labelKey: 'Guide.setup_provider',
    },
    {
      command:
        'ahadiff provider test --name deepseek --provider-class openai_compat --base-url https://api.deepseek.com --model deepseek-v4-flash --api-key-env AHADIFF_PROVIDER_API_KEY --privacy-mode explicit_remote',
      labelKey: 'Guide.setup_deepseek',
    },
    { command: 'ahadiff install --detect', labelKey: 'Guide.setup_install_detect' },
    { command: 'ahadiff install codex --dry-run', labelKey: 'Guide.setup_install_preview' },
    { command: 'ahadiff uninstall codex --dry-run', labelKey: 'Guide.setup_uninstall_preview' },
  ];
}

const ADVANCED_COMMANDS: ReadonlyArray<CommandEntry> = [
  { command: 'ahadiff watch', labelKey: 'Guide.advanced_watch' },
  {
    command: 'ahadiff install hooks --auto-learn',
    labelKey: 'Guide.commands_install_hooks_auto',
  },
  { command: 'ahadiff graph status', labelKey: 'Guide.advanced_graph_status' },
  { command: 'ahadiff graph import', labelKey: 'Guide.advanced_graph_import' },
  { command: 'ahadiff graph refresh', labelKey: 'Guide.advanced_graph_refresh' },
  { command: 'ahadiff db check', labelKey: 'Guide.advanced_db_check' },
  { command: 'ahadiff concepts list', labelKey: 'Guide.advanced_concepts_list' },
  { command: 'ahadiff concepts verify', labelKey: 'Guide.advanced_concepts_verify' },
  { command: 'ahadiff concepts lint', labelKey: 'Guide.commands_concepts_lint' },
  { command: 'ahadiff benchmark', labelKey: 'Guide.advanced_benchmark' },
  { command: 'ahadiff claims RUN_ID --force', labelKey: 'Guide.advanced_claims' },
  { command: 'ahadiff score RUN_ID', labelKey: 'Guide.advanced_score' },
  { command: 'ahadiff export-results', labelKey: 'Guide.advanced_export' },
  {
    command: 'ahadiff export preview RUN_ID --out ./preview',
    labelKey: 'Guide.commands_export_preview',
  },
  {
    command: 'ahadiff regenerate RUN_ID --only quiz',
    labelKey: 'Guide.advanced_regenerate',
  },
  {
    command: 'ahadiff regenerate RUN_ID --only quiz --active-practice',
    labelKey: 'Guide.advanced_regenerate_active',
  },
  {
    command: 'ahadiff improve-run RUN_ID --candidates 3',
    labelKey: 'Guide.commands_improve_run',
  },
  { command: 'ahadiff mcp-server', labelKey: 'Guide.commands_mcp_server' },
  {
    command: 'claude mcp add ahadiff -- ahadiff mcp-server --repo-root <path>',
    labelKey: 'Guide.commands_mcp_register_claude',
  },
  {
    command: 'codex mcp add ahadiff -- ahadiff mcp-server --repo-root <path>',
    labelKey: 'Guide.commands_mcp_register_codex',
  },
  {
    command: 'ahadiff challenge build RUN_ID',
    labelKey: 'Guide.commands_challenge_build',
  },
  {
    command: 'ahadiff challenge status',
    labelKey: 'Guide.commands_challenge_status',
  },
];

const MAINTENANCE_COMMANDS: ReadonlyArray<CommandEntry> = [
  { command: 'ahadiff db upgrade', labelKey: 'Guide.maintenance_db_upgrade' },
  { command: 'ahadiff db backup', labelKey: 'Guide.maintenance_db_backup' },
  {
    command: 'ahadiff db restore PATH/TO/review.sqlite.bak',
    labelKey: 'Guide.maintenance_db_restore',
  },
  {
    command: 'ahadiff db import-results results.tsv --i-understand-this-is-lossy',
    labelKey: 'Guide.maintenance_db_import_results',
  },
  {
    command: 'ahadiff db finalize-targeted RUN_ID',
    labelKey: 'Guide.maintenance_db_finalize_targeted',
  },
  { command: 'ahadiff concepts export', labelKey: 'Guide.maintenance_concepts_export' },
  { command: 'ahadiff concepts sync', labelKey: 'Guide.maintenance_concepts_sync' },
  {
    command: 'ahadiff concepts rollback --dry-run',
    labelKey: 'Guide.maintenance_concepts_rollback',
  },
  {
    command: 'ahadiff maint clean-orphans --dry-run',
    labelKey: 'Guide.maintenance_clean_orphans',
  },
  { command: 'ahadiff unlock --force', labelKey: 'Guide.maintenance_unlock' },
  { command: 'ahadiff mark CLAIM_ID wrong', labelKey: 'Guide.maintenance_mark' },
];

interface NavTarget {
  id: string;
  labelKey: MessageKey;
}

const NAV_TARGETS: ReadonlyArray<NavTarget> = [
  { id: 'start-learning', labelKey: 'Guide.nav_sources' },
  { id: 'workflow', labelKey: 'Guide.nav_workflow' },
  { id: 'commands', labelKey: 'Guide.nav_commands' },
  { id: 'setup', labelKey: 'Guide.nav_setup' },
  { id: 'agent-skills', labelKey: 'Guide.nav_agent_skills' },
  { id: 'advanced', labelKey: 'Guide.nav_advanced' },
  { id: 'maintenance', labelKey: 'Guide.nav_maintenance' },
  { id: 'integrations', labelKey: 'Guide.nav_integrations' },
];

type CatalogueState = 'loading' | 'ready' | 'error';

function targetMark(name: string): string {
  return name.split('-').map(part => part[0]).join('').slice(0, 2).toUpperCase();
}

export default function GuidePage() {
  const { t, locale } = useTranslation();
  const [targets, setTargets] = useState<InstallTarget[]>([]);
  const [catalogueState, setCatalogueState] = useState<CatalogueState>('loading');
  const [retryCount, setRetryCount] = useState(0);
  const [learnSource, setLearnSource] = useState<LearnSource | null>(null);
  const retryCatalogue = useCallback(() => setRetryCount(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setCatalogueState('loading');
    setTargets([]);
    getInstallTargets({ signal: controller.signal }).then(payload => {
      if (controller.signal.aborted) return;
      setTargets(payload.targets);
      setCatalogueState('ready');
    }).catch(() => {
      if (controller.signal.aborted) return;
      setCatalogueState('error');
    });
    return () => controller.abort();
  }, [locale, retryCount]);

  const platform = useMemo<Platform>(() => detectPlatform(), []);

  const copyLabels = {
    copyLabel: t('Guide.command_copy'),
    copiedLabel: t('Guide.command_copied'),
  };

  return (
    <AppShell globalShortcutsDisabled={learnSource !== null}>
      <div className="page active guide" data-page="skills">
        <header className="guide__head">
          <p className="guide__eyebrow">§ {t('Guide.eyebrow')}</p>
          <h1 className="guide__title">{t('Guide.title')}</h1>
          <p className="guide__subtitle guide__subtitle--lead">{t('Guide.subtitle')}</p>
        </header>

        <SectionNav t={t} />

        <section id="start-learning" className="guide-section" aria-labelledby="guide-sources-title">
          <h2 id="guide-sources-title" className="guide-section__title">
            <BookOpen className="guide-section__icon" aria-hidden="true" size={20} />
            {t('Guide.sources_title')}
          </h2>
          <p className="guide__subtitle">{t('Guide.sources_hint')}</p>
          <LearnSourcePicker onSelect={setLearnSource} />
          <p className="guide__subtitle">{t('Guide.sources_steps')}</p>
        </section>

        <WorkflowSection t={t} />

        <CoreCommandsSection
          t={t}
          platform={platform}
          copyLabels={copyLabels}
        />

        <SetupSection
          t={t}
          platform={platform}
          copyLabels={copyLabels}
        />

        <AgentSkillsSection t={t} copyLabels={copyLabels} targets={targets} catalogueState={catalogueState} onRetry={retryCatalogue} />

        <AdvancedSection
          t={t}
          copyLabels={copyLabels}
          titleId="guide-advanced-title"
        />

        <MaintenanceSection
          t={t}
          copyLabels={copyLabels}
          titleId="guide-maintenance-title"
        />

        <IntegrationsSection t={t} titleId="guide-integrations-title" targets={targets} catalogueState={catalogueState} onRetry={retryCatalogue} />
      </div>
      {learnSource && (
        <Suspense fallback={null}>
          <LearnModeDialog open initialSource={learnSource} onClose={() => setLearnSource(null)} />
        </Suspense>
      )}
    </AppShell>
  );
}

/* ------------------------------- Sections ------------------------------- */

function SectionNav({ t }: { t: TranslateFn }) {
  const handleJump = useCallback((sectionId: string) => {
    const target = document.getElementById(sectionId);
    if (!target) return;
    const prefersReduced = typeof window !== 'undefined'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    target.scrollIntoView({
      behavior: prefersReduced ? 'auto' : 'smooth',
      block: 'start',
    });
  }, []);

  return (
    <nav
      className="guide-nav"
      aria-label={t('Guide.nav_label')}
    >
      <ul className="guide-nav__list" role="list">
        {NAV_TARGETS.map((target, index) => (
          <li className="guide-nav__item" key={target.id}>
            <button
              type="button"
              className="guide-nav__chip"
              data-section={target.id}
              onClick={() => handleJump(target.id)}
            >
              <span className="guide-nav__chip-index" aria-hidden="true">
                0{index + 1}.
              </span>
              {t(target.labelKey)}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function WorkflowSection({ t }: { t: TranslateFn }) {
  return (
    <section
      id="workflow"
      className="guide-section guide-workflow"
      aria-labelledby="guide-workflow-title"
    >
      <h2 id="guide-workflow-title" className="guide-section__title">
        <BookOpen className="guide-section__icon" aria-hidden="true" size={20} />
        {t('Guide.workflow_title')}
      </h2>
      <ol className="guide-workflow__steps" role="list">
        {WORKFLOW_STEPS.map((step, index) => {
          const Icon = step.icon;
          const isLast = index === WORKFLOW_STEPS.length - 1;
          const stepNumber = index + 1;
          const stepAria = t('Guide.workflow_step_aria', { n: stepNumber });
          return (
            <li className="guide-workflow__step-item" key={step.titleKey}>
              <div className="guide-workflow__step" role="group" aria-label={stepAria}>
                <div className="guide-workflow__step-icon" aria-hidden="true">
                  <Icon size={22} />
                  <span className="guide-workflow__step-number">{stepNumber}</span>
                </div>
                <div className="guide-workflow__step-body">
                  <div className="guide-workflow__step-title">{t(step.titleKey)}</div>
                  <p className="guide-workflow__step-desc">{t(step.descKey)}</p>
                </div>
              </div>
              {!isLast && (
                <ChevronRight
                  className="guide-workflow__arrow"
                  aria-hidden="true"
                  size={20}
                />
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function CoreCommandsSection({
  t,
  platform,
  copyLabels,
}: {
  t: TranslateFn;
  platform: Platform;
  copyLabels: { copyLabel: string; copiedLabel: string };
}) {
  const psCmd = [
    getEnvVarCommand('windows', 'AHADIFF_PROVIDER_API_KEY', '<your-key>'),
    getEnvVarCommand('windows', 'AHADIFF_PROVIDER_BASE_URL', 'https://api.openai.com/v1'),
  ].join('\n');
  const shCmd = [
    getEnvVarCommand('macos', 'AHADIFF_PROVIDER_API_KEY', '<your-key>'),
    getEnvVarCommand('macos', 'AHADIFF_PROVIDER_BASE_URL', 'https://api.openai.com/v1'),
  ].join('\n');

  return (
    <section
      id="commands"
      className="guide-section"
      aria-labelledby="guide-commands-title"
    >
      <h2 id="guide-commands-title" className="guide-section__title">
        <Terminal className="guide-section__icon" aria-hidden="true" size={20} />
        {t('Guide.commands_title')}
      </h2>

      <div className="guide-install-model" aria-label={t('Guide.install_model_label')}>
        <div className="guide-install-model__item">
          <span>{t('Guide.install_model_cli_title')}</span>
          <p>{t('Guide.install_model_cli_desc')}</p>
        </div>
        <div className="guide-install-model__item">
          <span>{t('Guide.install_model_agent_title')}</span>
          <p>{t('Guide.install_model_agent_desc')}</p>
        </div>
      </div>

      <div className="guide-grid">
        {CORE_COMMANDS.map((entry) => (
          <CommandCard key={entry.command} entry={entry} t={t} {...copyLabels} />
        ))}
      </div>

      <ul className="guide-notes" role="list">
        <li className="guide-notes__item">{t('Guide.platform_note_path')}</li>
        <li className="guide-notes__item">{t('Guide.platform_note_space')}</li>
        <li className="guide-notes__item">{t('Guide.platform_note_staged')}</li>
      </ul>

      <div className="guide-env">
        <div id="guide-env-label" className="guide-env__label">
          $ENV
        </div>
        <div className="guide-env__panes" role="group" aria-labelledby="guide-env-label">
          <div
            className={`guide-env__pane ${
              platform === 'windows' ? 'guide-env__pane--active' : ''
            }`}
          >
            <div className="guide-env__pane-label">{t('Guide.platform_powershell')}</div>
            <CommandBlock command={psCmd} {...copyLabels} />
          </div>
          <div
            className={`guide-env__pane ${
              platform !== 'windows' ? 'guide-env__pane--active' : ''
            }`}
          >
            <div className="guide-env__pane-label">{t('Guide.platform_terminal')}</div>
            <CommandBlock command={shCmd} {...copyLabels} />
          </div>
        </div>
      </div>
    </section>
  );
}

function SetupSection({
  t,
  platform,
  copyLabels,
}: {
  t: TranslateFn;
  platform: Platform;
  copyLabels: { copyLabel: string; copiedLabel: string };
}) {
  const commands = useMemo(() => setupCommands(platform), [platform]);
  return (
    <section
      id="setup"
      className="guide-section"
      aria-labelledby="guide-setup-title"
    >
      <h2 id="guide-setup-title" className="guide-section__title">
        <Settings className="guide-section__icon" aria-hidden="true" size={20} />
        {t('Guide.setup_title')}
      </h2>
      <div className="guide-grid">
        {commands.map((entry) => (
          <CommandCard key={entry.command} entry={entry} t={t} {...copyLabels} />
        ))}
      </div>
    </section>
  );
}

function CatalogueStatus({ state, empty, t, onRetry }: {
  state: CatalogueState;
  empty: boolean;
  t: TranslateFn;
  onRetry: () => void;
}) {
  if (state === 'ready' && !empty) return null;
  return (
    <div className="guide-agent-skills__empty" role={state === 'error' ? 'alert' : 'status'}>
      <p>{t(state === 'loading' ? 'Guide.agent_loading' : state === 'error' ? 'Guide.agent_load_failed' : 'Guide.agent_empty')}</p>
      {state === 'error' && (
        <button type="button" className="guide-agent-skills__tab-chip" onClick={onRetry}>
          {t('Guide.agent_retry')}
        </button>
      )}
    </div>
  );
}

function AgentSkillsSection({
  t,
  copyLabels,
  targets,
  catalogueState,
  onRetry,
}: {
  t: TranslateFn;
  copyLabels: { copyLabel: string; copiedLabel: string };
  targets: InstallTarget[];
  catalogueState: CatalogueState;
  onRetry: () => void;
}) {
  const [expandedCard, setExpandedCard] = useState<string | null>(null);
  const [printExpanded, setPrintExpanded] = useState(false);
  const [activeCategory, setActiveCategory] = useState<'all' | 'cli' | 'ide' | 'ci'>('all');
  const buttonRefs = useRef<HTMLButtonElement[]>([]);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const printQuery = window.matchMedia('print');
    const syncPrintState = () => setPrintExpanded(printQuery.matches);
    const handleBeforePrint = () => setPrintExpanded(true);
    const handleAfterPrint = () => setPrintExpanded(false);
    const handlePrintChange = (event: MediaQueryListEvent) => setPrintExpanded(event.matches);

    syncPrintState();
    printQuery.addEventListener('change', handlePrintChange);
    window.addEventListener('beforeprint', handleBeforePrint);
    window.addEventListener('afterprint', handleAfterPrint);

    return () => {
      printQuery.removeEventListener('change', handlePrintChange);
      window.removeEventListener('beforeprint', handleBeforePrint);
      window.removeEventListener('afterprint', handleAfterPrint);
    };
  }, []);

  const { allCount, cliCount, ideCount, ciCount } = useMemo(() => {
    let cli = 0, ide = 0, ci = 0;
    targets.forEach(t => {
      const cat = t.usage_hint?.tool_category;
      if (cat === 'cli') cli++;
      else if (cat === 'ide') ide++;
      else if (cat === 'ci') ci++;
    });
    return {
      allCount: targets.length,
      cliCount: cli,
      ideCount: ide,
      ciCount: ci,
    };
  }, [targets]);

  const categories = [
    { id: 'all', labelKey: 'Guide.agent_category_all' as const, count: allCount },
    { id: 'cli', labelKey: 'Guide.agent_category_cli' as const, count: cliCount },
    { id: 'ide', labelKey: 'Guide.agent_category_ide' as const, count: ideCount },
    { id: 'ci', labelKey: 'Guide.agent_category_ci' as const, count: ciCount },
  ];

  const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
    let nextIndex = currentIndex;
    if (e.key === 'ArrowRight') {
      nextIndex = (currentIndex + 1) % categories.length;
    } else if (e.key === 'ArrowLeft') {
      nextIndex = (currentIndex - 1 + categories.length) % categories.length;
    } else if (e.key === 'Home') {
      nextIndex = 0;
    } else if (e.key === 'End') {
      nextIndex = categories.length - 1;
    } else {
      return;
    }
    e.preventDefault();
    const targetButton = buttonRefs.current[nextIndex];
    if (targetButton) {
      targetButton.focus();
      setActiveCategory(categories[nextIndex].id as 'all' | 'cli' | 'ide' | 'ci');
    }
  };

  const filteredTargets = useMemo(() => {
    if (activeCategory === 'all') return targets;
    return targets.filter(t => {
      const cat = t.usage_hint?.tool_category;
      return cat === activeCategory;
    });
  }, [targets, activeCategory]);

  return (
    <section
      id="agent-skills"
      className="guide-section guide-agent-skills"
      aria-labelledby="guide-agent-skills-title"
    >
      <div className="guide-agent-skills__head">
        <div>
          <h2 id="guide-agent-skills-title" className="guide-section__title">
            <Puzzle className="guide-section__icon" aria-hidden="true" size={20} />
            {t('Guide.agent_skills_title')}
          </h2>
          <p className="guide-agent-skills__subtitle">
            {t('Guide.agent_skills_subtitle')}
          </p>
        </div>
        <div
          className="guide-agent-skills__tabs"
          role="tablist"
          aria-label={t('Guide.agent_skills_filter_label')}
        >
          {categories.map((cat, idx) => (
            <button
              key={cat.id}
              ref={(el) => {
                if (el) buttonRefs.current[idx] = el;
              }}
              type="button"
              role="tab"
              aria-selected={activeCategory === cat.id}
              tabIndex={activeCategory === cat.id ? 0 : -1}
              aria-controls="agent-skills-grid"
              className={`guide-agent-skills__tab-chip ${
                activeCategory === cat.id ? 'guide-agent-skills__tab-chip--active' : ''
              }`}
              onClick={() => setActiveCategory(cat.id as 'all' | 'cli' | 'ide' | 'ci')}
              onKeyDown={(e) => handleKeyDown(e, idx)}
            >
              {t(cat.labelKey)} <span className="guide-agent-skills__tab-count">({cat.count})</span>
            </button>
          ))}
        </div>
      </div>

      <div
        id="agent-skills-grid"
        className="guide-agent-skills__grid"
        role="tabpanel"
        aria-label={t('Guide.agent_skills_title')}
      >
        <CatalogueStatus state={catalogueState} empty={filteredTargets.length === 0} t={t} onRetry={onRetry} />
        {filteredTargets.map((target) => {
          const name = target.name;
          const status = target.status;
          const displayName = target.display_name || name;
          const command = target.install_command ?? `ahadiff install ${name}`;
          const writes = target?.manifest?.write ?? [];
          const pathHint = writes.find((action) => action.file_strategy === 'generated')?.path
            ?? writes[0]?.path
            ?? '';
          const isExpanded = expandedCard === name;
          const renderPanelContent = isExpanded || printExpanded;
          return (
            <article className={`guide-agent-card ${isExpanded ? 'is-expanded' : ''}`} key={name}>
              <h3 className="guide-agent-card__heading">
                <button
                  className="guide-agent-card__header"
                  type="button"
                  aria-expanded={isExpanded}
                  aria-controls={`agent-content-${name}`}
                  onClick={() => setExpandedCard(current => (current === name ? null : name))}
                >
                  <span className="guide-agent-card__header-content">
                    <span className="guide-agent-card__topline">
                      <span className="guide-agent-card__mark">{targetMark(name)}</span>
                      <span className={`guide-agent-card__status guide-agent-card__status--${status}`}>
                        {t(`Guide.agent_status_${status}` as MessageKey)}
                      </span>
                      {target.lifecycle === 'preview' && (
                        <span className="guide-agent-card__platform-badge">{t('Guide.agent_lifecycle_preview')}</span>
                      )}
                    </span>
                    <span className="guide-agent-card__name">{displayName}</span>
                    {pathHint && <span className="guide-agent-card__path">{pathHint}</span>}
                  </span>
                  <ChevronDown className="guide-agent-card__chevron" size={18} aria-hidden="true" />
                </button>
              </h3>

              <div
                id={`agent-content-${name}`}
                className="guide-agent-card__collapsible"
                hidden={!renderPanelContent}
              >
                {renderPanelContent && (
                  <div className="guide-agent-card__content-inner">
                    <p>{target.description}</p>
                    {target.lifecycle_note && <p>{target.lifecycle_note}</p>}
                    {target.documentation_url?.startsWith('https://') && (
                      <a href={target.documentation_url} target="_blank" rel="noreferrer">{t('Guide.agent_native_docs')}</a>
                    )}
                    <div className="guide-agent-card__install">
                      <CommandBlock command={command} {...copyLabels} />
                    </div>

                    {target.usage_hint && (
                      <div className="guide-agent-card__usage-panel-wrapper">
                        <UsagePanel hint={target.usage_hint} t={t} />
                      </div>
                    )}

                    {target.manifest && target.manifest.write && target.manifest.write.length > 0 && (
                      <div className="guide-agent-card__manifest-preview">
                        <h4 className="guide-agent-card__manifest-preview-title">
                          {t('Guide.agent_preview_manifest_title')}
                        </h4>
                        <ul className="guide-agent-card__manifest-preview-list" role="list">
                          {target.manifest.write.map((action, idx) => (
                            <li
                              key={idx}
                              className={`guide-agent-card__manifest-preview-item guide-agent-card__manifest-preview-item--${action.file_strategy}`}
                            >
                              <span className="guide-agent-card__manifest-preview-path">
                                <code>{action.path}</code>
                              </span>
                              <span
                                className={`guide-agent-card__manifest-preview-strategy-badge guide-agent-card__manifest-preview-strategy-badge--${action.file_strategy}`}
                              >
                                {action.file_strategy === 'generated'
                                  ? t('Guide.agent_preview_generated')
                                  : t('Guide.agent_preview_user_managed')}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>

      <div className="guide-workflows-section">
        <h3 className="guide-workflows-section__title">
          <BookOpen className="guide-section__icon" aria-hidden="true" size={20} />
          {t('Guide.agent_workflow_title')}
        </h3>
        <div className="guide-workflows-grid">
          <div className="guide-workflow-card">
            <h4 className="guide-workflow-card__title">{t('Guide.agent_workflow_daily_title')}</h4>
            <p className="guide-workflow-card__desc">{t('Guide.agent_workflow_daily_desc')}</p>
            <CommandBlock command="ahadiff learn HEAD~1..HEAD" {...copyLabels} />
          </div>
          <div className="guide-workflow-card">
            <h4 className="guide-workflow-card__title">{t('Guide.agent_workflow_review_title')}</h4>
            <p className="guide-workflow-card__desc">{t('Guide.agent_workflow_review_desc')}</p>
            <CommandBlock command="ahadiff verify <run_id>\nahadiff review" {...copyLabels} />
          </div>
          <div className="guide-workflow-card">
            <h4 className="guide-workflow-card__title">{t('Guide.agent_workflow_improve_title')}</h4>
            <p className="guide-workflow-card__desc">{t('Guide.agent_workflow_improve_desc')}</p>
            <CommandBlock command="ahadiff improve --rounds 1" {...copyLabels} />
          </div>
        </div>
      </div>


    </section>
  );
}

function AdvancedSection({
  t,
  copyLabels,
  titleId,
}: {
  t: TranslateFn;
  copyLabels: { copyLabel: string; copiedLabel: string };
  titleId: string;
}) {
  return (
    <section
      id="advanced"
      className="guide-section"
      aria-labelledby={titleId}
    >
      <h2 id={titleId} className="guide-section__title">
        <Wrench className="guide-section__icon" aria-hidden="true" size={20} />
        {t('Guide.advanced_title')}
      </h2>
      <details className="guide-accordion">
        <summary className="guide-accordion__summary">
          <Wrench className="guide-section__icon" aria-hidden="true" size={18} />
          <span className="guide-accordion__summary-text">
            {t('Guide.advanced_toggle')}
          </span>
          <ChevronRight
            className="guide-accordion__chevron"
            aria-hidden="true"
            size={18}
          />
        </summary>
        <div className="guide-accordion__body">
          <div className="guide-grid">
            {ADVANCED_COMMANDS.map((entry) => (
              <CommandCard
                key={entry.command}
                entry={entry}
                t={t}
                {...copyLabels}
              />
            ))}
          </div>
        </div>
      </details>
    </section>
  );
}

function MaintenanceSection({
  t,
  copyLabels,
  titleId,
}: {
  t: TranslateFn;
  copyLabels: { copyLabel: string; copiedLabel: string };
  titleId: string;
}) {
  return (
    <section
      id="maintenance"
      className="guide-section"
      aria-labelledby={titleId}
    >
      <h2 id={titleId} className="guide-section__title">
        <Code className="guide-section__icon" aria-hidden="true" size={20} />
        {t('Guide.maintenance_title')}
      </h2>
      <details className="guide-accordion">
        <summary className="guide-accordion__summary">
          <Code className="guide-section__icon" aria-hidden="true" size={18} />
          <span className="guide-accordion__summary-text">
            {t('Guide.maintenance_toggle')}
          </span>
          <ChevronRight
            className="guide-accordion__chevron"
            aria-hidden="true"
            size={18}
          />
        </summary>
        <div className="guide-accordion__body">
          <div className="guide-grid">
            {MAINTENANCE_COMMANDS.map((entry) => (
              <CommandCard
                key={entry.command}
                entry={entry}
                t={t}
                {...copyLabels}
              />
            ))}
          </div>
        </div>
      </details>
    </section>
  );
}

function IntegrationsSection({ t, titleId, targets, catalogueState, onRetry }: {
  t: TranslateFn;
  titleId: string;
  targets: InstallTarget[];
  catalogueState: CatalogueState;
  onRetry: () => void;
}) {
  return (
    <section
      id="integrations"
      className="guide-section"
      aria-labelledby={titleId}
    >
      <h2 id={titleId} className="guide-section__title">
        <Puzzle className="guide-section__icon" aria-hidden="true" size={20} />
        {t('Guide.integrations_title')}
      </h2>
      <details className="guide-accordion">
        <summary className="guide-accordion__summary">
          <Puzzle className="guide-section__icon" aria-hidden="true" size={18} />
          <span className="guide-accordion__summary-text">
            {t('Guide.integrations_toggle')}
          </span>
          <ChevronRight
            className="guide-accordion__chevron"
            aria-hidden="true"
            size={18}
          />
        </summary>
        <div className="guide-accordion__body">
          <p className="guide-integrations__desc">{t('Guide.integrations_desc')}</p>
          <p className="guide-integrations__scope">{t('Guide.integrations_scope_note')}</p>
          <p className="guide-integrations__scope">{t('Guide.integrations_migration_note')}</p>
          <CatalogueStatus state={catalogueState} empty={targets.length === 0} t={t} onRetry={onRetry} />
          <ul className="guide-integrations__list" role="list">
            {targets.map((target) => (
              <li className="guide-integrations__item" key={target.name}>
                <span className="guide-integrations__name">{target.display_name}</span>

              </li>
            ))}
          </ul>
          <a
            href="#/settings?tab=integrations"
            className="guide-integrations__hint"
          >
            <Brain className="guide-integrations__hint-icon" aria-hidden="true" size={16} />
            <span className="guide-integrations__hint-text">
              {t('Guide.integrations_manage_hint')}
            </span>
            <span className="guide-integrations__hint-cta">
              {t('Guide.integrations_manage_link')}
              <ExternalLink aria-hidden="true" size={14} />
            </span>
          </a>
        </div>
      </details>
    </section>
  );
}

/* ------------------------------- Pieces ------------------------------- */

function CommandCard({
  entry,
  t,
  copyLabel,
  copiedLabel,
}: {
  entry: CommandEntry;
  t: TranslateFn;
  copyLabel: string;
  copiedLabel: string;
}) {
  return (
    <div className="guide-card">
      <div className="guide-card__label">
        <span>{t(entry.labelKey)}</span>
      </div>
      <CommandBlock
        command={entry.command}
        copyLabel={copyLabel}
        copiedLabel={copiedLabel}
      />
    </div>
  );
}
