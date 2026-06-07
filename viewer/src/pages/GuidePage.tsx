import { useCallback, useEffect, useMemo, useState, useRef } from 'react';
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
    { command: 'ahadiff install --detect', labelKey: 'Guide.setup_install_detect' },
    { command: 'ahadiff install codex --dry-run', labelKey: 'Guide.setup_install_preview' },
    { command: 'ahadiff uninstall codex --dry-run', labelKey: 'Guide.setup_uninstall_preview' },
  ];
}

const ADVANCED_COMMANDS: ReadonlyArray<CommandEntry> = [
  { command: 'ahadiff watch', labelKey: 'Guide.advanced_watch' },
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
    command: 'ahadiff improve-run RUN_ID --candidates 3',
    labelKey: 'Guide.commands_improve_run',
  },
  { command: 'ahadiff mcp-server', labelKey: 'Guide.commands_mcp_server' },
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

interface IntegrationTarget {
  name: string;
  posixOnly?: boolean;
}

const INTEGRATION_TARGETS: ReadonlyArray<IntegrationTarget> = [
  { name: 'aider' },
  { name: 'antigravity' },
  { name: 'antigravity-cli' },
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
  { id: 'agent-skills', labelKey: 'Guide.nav_agent_skills' },
  { id: 'advanced', labelKey: 'Guide.nav_advanced' },
  { id: 'maintenance', labelKey: 'Guide.nav_maintenance' },
  { id: 'integrations', labelKey: 'Guide.nav_integrations' },
];

const AGENT_MARKS: Record<string, string> = {
  aider: 'AI',
  antigravity: 'AG',
  'antigravity-cli': 'AC',
  claude: 'CC',
  cline: 'CL',
  codex: 'CD',
  continue: 'CN',
  copilot: 'CP',
  cursor: 'CX',
  gemini: 'GM',
  'github-action': 'GH',
  hooks: 'HK',
  opencode: 'OC',
  roo: 'RO',
  windsurf: 'WS',
};

const AGENT_DISPLAY_NAMES: Record<string, string> = {
  aider: 'Aider',
  antigravity: 'Antigravity IDE',
  'antigravity-cli': 'Antigravity CLI',
  claude: 'Claude Code',
  cline: 'Cline',
  codex: 'Codex CLI',
  continue: 'Continue',
  copilot: 'Copilot / VS Code',
  cursor: 'Cursor',
  gemini: 'Gemini CLI',
  'github-action': 'GitHub Action',
  hooks: 'Git hooks',
  opencode: 'OpenCode',
  roo: 'Roo',
  windsurf: 'Windsurf',
};

const AGENT_PATH_HINTS: Record<string, string> = {
  aider: 'CONVENTIONS.md',
  antigravity: '.agents/skills/ahadiff-antigravity/SKILL.md · .agents/rules/ahadiff.md',
  'antigravity-cli': '.agents/skills/ahadiff-antigravity-cli/SKILL.md · GEMINI.md',
  claude: '.claude/skills/ahadiff/SKILL.md',
  cline: '.clinerules/ahadiff.md',
  codex: '.agents/skills/ahadiff/SKILL.md',
  continue: '.continue/rules/ahadiff.md',
  copilot: '.github/instructions/ahadiff.instructions.md',
  cursor: '.cursor/rules/ahadiff.mdc',
  gemini: '.gemini/skills/ahadiff/SKILL.md',
  'github-action': '.github/workflows/ahadiff-verify.yml',
  hooks: '.git/hooks/post-commit',
  opencode: '.opencode/agents/ahadiff.md',
  roo: '.roo/rules/ahadiff.md',
  windsurf: '.windsurf/rules/ahadiff.md',
};

function targetMark(name: string): string {
  return AGENT_MARKS[name] ?? name.slice(0, 2).toUpperCase();
}

function fallbackInstallTargets(status: InstallTarget['status']): InstallTarget[] {
  return INTEGRATION_TARGETS.map((target) => ({
    name: target.name,
    display_name: AGENT_DISPLAY_NAMES[target.name] ?? target.name,
    detected: false,
    platform_supported: true,
    status,
    description: '',
    install_command: `ahadiff install ${target.name}`,
    uninstall_command: `ahadiff uninstall ${target.name}`,
  }));
}

const SKILL_PREVIEW = `---
name: ahadiff
description: Turn git diffs into verified learning lessons.
allowed-tools: Read, Grep, Bash
---

1. Read the diff or run artifact.
2. Ground every claim to file:line evidence.
3. Write lesson, claims, quiz, and score outputs.`;

const AGENTS_PREVIEW = `# AGENTS.md · AhaDiff

When a code change lands:
1. Run ahadiff learn on the relevant diff.
2. Keep claims evidence-bound.
3. Never upload secrets or local private files.
4. Mark ungrounded claims as not_proven.`;

export default function GuidePage() {
  const { t } = useTranslation();
  const platform = useMemo<Platform>(() => detectPlatform(), []);

  const copyLabels = {
    copyLabel: t('Guide.command_copy'),
    copiedLabel: t('Guide.command_copied'),
  };

  return (
    <AppShell>
      <div className="page active guide" data-page="skills">
        <header className="guide__head">
          <p className="guide__eyebrow">§ {t('Guide.eyebrow')}</p>
          <h1 className="guide__title">{t('Guide.title')}</h1>
          <p className="guide__subtitle guide__subtitle--lead">{t('Guide.subtitle')}</p>
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
          platform={platform}
          copyLabels={copyLabels}
        />

        <AgentSkillsSection t={t} copyLabels={copyLabels} />

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

function getTargetCategory(targetName: string, hintCategory?: string): 'cli' | 'ide' | 'ci' {
  if (hintCategory === 'cli' || hintCategory === 'ide' || hintCategory === 'ci') {
    return hintCategory;
  }
  const cliTargets = ['claude', 'codex', 'antigravity-cli', 'gemini', 'aider', 'opencode'];
  const ideTargets = ['antigravity', 'cursor', 'cline', 'continue', 'copilot', 'windsurf', 'roo'];
  if (cliTargets.includes(targetName)) return 'cli';
  if (ideTargets.includes(targetName)) return 'ide';
  return 'ci';
}

function AgentSkillsSection({
  t,
  copyLabels,
}: {
  t: TranslateFn;
  copyLabels: { copyLabel: string; copiedLabel: string };
}) {
  const { locale } = useTranslation();
  const [expandedCard, setExpandedCard] = useState<string | null>(null);
  const [printExpanded, setPrintExpanded] = useState(false);
  const [targets, setTargets] = useState<InstallTarget[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
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

  useEffect(() => {
    const controller = new AbortController();
    getInstallTargets({ signal: controller.signal }).then((payload) => {
      if (!controller.signal.aborted) {
        setTargets(payload.targets);
        setLoaded(true);
        setFailed(false);
      }
    }).catch((err: unknown) => {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (!controller.signal.aborted) {
        setTargets([]);
        setLoaded(true);
        setFailed(true);
      }
    });
    return () => controller.abort();
  }, [locale]);

  const displayTargets = useMemo(
    () =>
      targets.length > 0
        ? targets
        : failed
          ? fallbackInstallTargets('error')
          : loaded
            ? []
            : fallbackInstallTargets('available'),
    [failed, loaded, targets],
  );

  const integrationMeta = useMemo(() => {
    const map = new Map<string, IntegrationTarget>();
    for (const target of INTEGRATION_TARGETS) {
      map.set(target.name, target);
    }
    return map;
  }, []);

  const { allCount, cliCount, ideCount, ciCount } = useMemo(() => {
    let cli = 0, ide = 0, ci = 0;
    displayTargets.forEach(t => {
      const cat = getTargetCategory(t.name, t.usage_hint?.tool_category);
      if (cat === 'cli') cli++;
      else if (cat === 'ide') ide++;
      else if (cat === 'ci') ci++;
    });
    return {
      allCount: displayTargets.length,
      cliCount: cli,
      ideCount: ide,
      ciCount: ci,
    };
  }, [displayTargets]);

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
    if (activeCategory === 'all') return displayTargets;
    return displayTargets.filter(t => {
      const cat = getTargetCategory(t.name, t.usage_hint?.tool_category);
      return cat === activeCategory;
    });
  }, [displayTargets, activeCategory]);

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
        {filteredTargets.length === 0 && (
          <p className="guide-agent-skills__empty">{t('Guide.agent_empty')}</p>
        )}
        {filteredTargets.map((target) => {
          const name = target.name;
          const status = loaded && failed ? 'error' : target.status;
          const displayName = target.display_name || name;
          const command = target.install_command ?? `ahadiff install ${name}`;
          const writes = target?.manifest?.write ?? [];
          const pathHint = writes.find((action) => action.file_strategy === 'generated')?.path
            ?? writes[0]?.path
            ?? AGENT_PATH_HINTS[name]
            ?? '';
          const meta = integrationMeta.get(name);
          const isExpanded = expandedCard === name;
          const renderPanelContent = isExpanded || printExpanded;
          return (
            <article className={`guide-agent-card ${isExpanded ? 'is-expanded' : ''}`} key={name}>
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
                    {meta?.posixOnly && (
                      <span className="guide-agent-card__platform-badge">
                        {t('Guide.integrations_posix_only')}
                      </span>
                    )}
                  </span>
                  <span className="guide-agent-card__name">{displayName}</span>
                  {pathHint && <span className="guide-agent-card__path">{pathHint}</span>}
                </span>
                <ChevronDown className="guide-agent-card__chevron" size={18} aria-hidden="true" />
              </button>

              <div
                id={`agent-content-${name}`}
                className="guide-agent-card__collapsible"
                hidden={!renderPanelContent}
              >
                {renderPanelContent && (
                  <div className="guide-agent-card__content-inner">
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

      {(failed || targets.length === 0) && (
        <div className="guide-agent-previews">
          <article className="guide-agent-preview">
            <div className="guide-agent-preview__title">SKILL.md</div>
            <pre className="guide-agent-preview__code">{SKILL_PREVIEW}</pre>
          </article>
          <article className="guide-agent-preview">
            <div className="guide-agent-preview__title">{t('Guide.agent_preview_agents_title')}</div>
            <pre className="guide-agent-preview__code">{AGENTS_PREVIEW}</pre>
          </article>
        </div>
      )}
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
