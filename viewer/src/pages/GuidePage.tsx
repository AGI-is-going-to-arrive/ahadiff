import { useCallback, useMemo } from 'react';
import {
  BookOpen,
  Brain,
  ChevronRight,
  Code,
  ExternalLink,
  GraduationCap,
  Hash,
  Puzzle,
  RotateCcw,
  Settings,
  Terminal,
  TrendingUp,
  Wrench,
} from 'lucide-react';
import AppShell from '../components/AppShell';
import { CommandBlock } from '../components/CommandBlock';
import { useTranslation, type MessageKey, type TranslateFn } from '../i18n/useTranslation';
import { detectPlatform, getEnvVarCommand, type Platform } from '../utils/platform';
import './GuidePage.css';

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
  { command: 'pip install ahadiff', labelKey: 'Guide.commands_install' },
  { command: 'ahadiff init', labelKey: 'Guide.commands_init' },
  { command: 'ahadiff learn HEAD~1..HEAD', labelKey: 'Guide.commands_learn' },
  { command: 'ahadiff learn --staged', labelKey: 'Guide.commands_learn_staged' },
  {
    command: 'ahadiff learn --unstaged --include-untracked',
    labelKey: 'Guide.commands_learn_unstaged',
  },
  {
    command: 'ahadiff learn --unstaged --changed-path src/example.py',
    labelKey: 'Guide.commands_learn_path',
  },
  { command: 'ahadiff serve', labelKey: 'Guide.commands_serve' },
  { command: 'ahadiff quiz RUN_ID', labelKey: 'Guide.commands_quiz' },
  { command: 'ahadiff review', labelKey: 'Guide.commands_review' },
  { command: 'ahadiff verify RUN_ID', labelKey: 'Guide.commands_verify' },
  { command: 'ahadiff improve --rounds 1', labelKey: 'Guide.commands_improve' },
];

const SETUP_COMMANDS: ReadonlyArray<CommandEntry> = [
  { command: 'ahadiff doctor', labelKey: 'Guide.setup_doctor' },
  { command: 'ahadiff config show --resolved', labelKey: 'Guide.setup_config' },
  { command: 'ahadiff provider test --name default', labelKey: 'Guide.setup_provider' },
  { command: 'ahadiff install --detect', labelKey: 'Guide.setup_install_detect' },
  { command: 'ahadiff install codex --dry-run', labelKey: 'Guide.setup_install_preview' },
  { command: 'ahadiff uninstall codex --dry-run', labelKey: 'Guide.setup_uninstall_preview' },
];

const ADVANCED_COMMANDS: ReadonlyArray<CommandEntry> = [
  { command: 'ahadiff watch', labelKey: 'Guide.advanced_watch' },
  { command: 'ahadiff graph status', labelKey: 'Guide.advanced_graph_status' },
  { command: 'ahadiff graph import', labelKey: 'Guide.advanced_graph_import' },
  { command: 'ahadiff graph refresh', labelKey: 'Guide.advanced_graph_refresh' },
  { command: 'ahadiff db check', labelKey: 'Guide.advanced_db_check' },
  { command: 'ahadiff concepts list', labelKey: 'Guide.advanced_concepts_list' },
  { command: 'ahadiff concepts verify', labelKey: 'Guide.advanced_concepts_verify' },
  { command: 'ahadiff benchmark', labelKey: 'Guide.advanced_benchmark' },
  { command: 'ahadiff claims RUN_ID', labelKey: 'Guide.advanced_claims' },
  { command: 'ahadiff score RUN_ID', labelKey: 'Guide.advanced_score' },
  { command: 'ahadiff export-results', labelKey: 'Guide.advanced_export' },
  {
    command: 'ahadiff regenerate RUN_ID --only quiz',
    labelKey: 'Guide.advanced_regenerate',
  },
];

const MAINTENANCE_COMMANDS: ReadonlyArray<CommandEntry> = [
  { command: 'ahadiff db upgrade', labelKey: 'Guide.maintenance_db_upgrade' },
  { command: 'ahadiff db backup', labelKey: 'Guide.maintenance_db_backup' },
  { command: 'ahadiff db restore', labelKey: 'Guide.maintenance_db_restore' },
  { command: 'ahadiff db import-results', labelKey: 'Guide.maintenance_db_import_results' },
  { command: 'ahadiff db finalize-targeted', labelKey: 'Guide.maintenance_db_finalize_targeted' },
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
  { command: 'ahadiff unlock', labelKey: 'Guide.maintenance_unlock' },
  { command: 'ahadiff mark', labelKey: 'Guide.maintenance_mark' },
];

interface IntegrationTarget {
  name: string;
  posixOnly?: boolean;
}

const INTEGRATION_TARGETS: ReadonlyArray<IntegrationTarget> = [
  { name: 'aider' },
  { name: 'claude' },
  { name: 'cline' },
  { name: 'codex' },
  { name: 'continue' },
  { name: 'copilot' },
  { name: 'cursor' },
  { name: 'gemini' },
  { name: 'github-action' },
  { name: 'hooks', posixOnly: true },
  { name: 'opencode' },
  { name: 'roo' },
  { name: 'windsurf' },
];

interface NavTarget {
  id: string;
  labelKey: MessageKey;
}

const NAV_TARGETS: ReadonlyArray<NavTarget> = [
  { id: 'workflow', labelKey: 'Guide.nav_workflow' },
  { id: 'commands', labelKey: 'Guide.nav_commands' },
  { id: 'setup', labelKey: 'Guide.nav_setup' },
  { id: 'advanced', labelKey: 'Guide.nav_advanced' },
  { id: 'maintenance', labelKey: 'Guide.nav_maintenance' },
  { id: 'integrations', labelKey: 'Guide.nav_integrations' },
];

export default function GuidePage() {
  const { t } = useTranslation();
  const platform = useMemo<Platform>(() => detectPlatform(), []);

  const copyLabels = {
    copyLabel: t('Guide.command_copy'),
    copiedLabel: t('Guide.command_copied'),
  };

  return (
    <AppShell>
      <div className="guide">
        <header className="guide__head">
          <p className="guide__eyebrow">§ {t('Guide.eyebrow')}</p>
          <h1 className="guide__title">{t('Guide.title')}</h1>
          <p className="guide__subtitle">{t('Guide.subtitle')}</p>
        </header>

        <SectionNav t={t} />

        <WorkflowSection t={t} />

        <CoreCommandsSection
          t={t}
          platform={platform}
          copyLabels={copyLabels}
        />

        <SetupSection
          t={t}
          copyLabels={copyLabels}
        />

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

        <IntegrationsSection t={t} titleId="guide-integrations-title" />
      </div>
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
        {NAV_TARGETS.map((target) => (
          <li className="guide-nav__item" key={target.id}>
            <button
              type="button"
              className="guide-nav__chip"
              data-section={target.id}
              onClick={() => handleJump(target.id)}
            >
              <Hash className="guide-nav__chip-icon" aria-hidden="true" size={12} />
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
              <div className="guide-workflow__step" aria-label={stepAria}>
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
  const psCmd = getEnvVarCommand('windows', 'OPENAI_API_KEY', '<your-key>');
  const shCmd = getEnvVarCommand('macos', 'OPENAI_API_KEY', '<your-key>');

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
  copyLabels,
}: {
  t: TranslateFn;
  copyLabels: { copyLabel: string; copiedLabel: string };
}) {
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
        {SETUP_COMMANDS.map((entry) => (
          <CommandCard key={entry.command} entry={entry} t={t} {...copyLabels} />
        ))}
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

function IntegrationsSection({ t, titleId }: { t: TranslateFn; titleId: string }) {
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
          <ul className="guide-integrations__list" role="list">
            {INTEGRATION_TARGETS.map((target) => (
              <li className="guide-integrations__item" key={target.name}>
                <span className="guide-integrations__name">{target.name}</span>
                {target.posixOnly && (
                  <span className="guide-integrations__badge">
                    {t('Guide.integrations_posix_only')}
                  </span>
                )}
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
