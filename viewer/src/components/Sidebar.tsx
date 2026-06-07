import { useEffect, useState } from 'react';
import { NavLink, useMatch } from 'react-router-dom';
import {
  BookOpen,
  CircleHelp,
  GitCompareArrows,
  LayoutDashboard,
  Network,
  Play,
  RefreshCw,
  Settings as SettingsIcon,
  Star,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import { useRunsStore } from '../state/runs-store';
import { getConfig } from '../api/config';
import './Sidebar.css';

interface NavEntry {
  to: string;
  Icon: LucideIcon;
  labelKey: MessageKey;
  labelEn: string;
  end?: boolean;
  disabled?: boolean;
}

interface NavSection {
  sectionKey: MessageKey;
  sectionId: string;
  items: NavEntry[];
}

interface SidebarProps {
  isOpen: boolean;
  isMobileNav: boolean;
  onNavigate?: () => void;
}

const VIEWER_VERSION = 'v1.3.0';
const PRIVACY_MODE_LABEL_KEYS: Record<string, MessageKey> = {
  strict_local: 'Settings_page.privacy_mode_strict_local',
  redacted_remote: 'Settings_page.privacy_mode_redacted_remote',
  explicit_remote: 'Settings_page.privacy_mode_explicit_remote',
};

export type ProviderStatus =
  | { state: 'loading' }
  | { state: 'empty' }
  | { state: 'error' }
  | { state: 'ready'; privacyMode: string | null; provider: string | null };

function formatRelativeTime(isoDate: string, locale: string): string {
  const date = new Date(isoDate);
  if (isNaN(date.getTime())) return isoDate;
  const diffMs = Date.now() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
  if (diffDay > 0) return rtf.format(-diffDay, 'day');
  if (diffHr > 0) return rtf.format(-diffHr, 'hour');
  if (diffMin > 0) return rtf.format(-diffMin, 'minute');
  return rtf.format(-diffSec, 'second');
}

function useProviderStatus() {
  const [status, setStatus] = useState<ProviderStatus>({ state: 'loading' });
  useEffect(() => {
    const controller = new AbortController();
    getConfig({ signal: controller.signal })
      .then((cfg) => {
        if (controller.signal.aborted) return;
        if (!cfg.privacy_mode && !cfg.generate_provider) {
          setStatus({ state: 'empty' });
          return;
        }
        setStatus({
          state: 'ready',
          privacyMode: cfg.privacy_mode,
          provider: cfg.generate_provider,
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus({ state: 'error' });
      });
    return () => controller.abort();
  }, []);
  return status;
}

export function formatProviderStatus(
  status: ProviderStatus,
  t: (key: MessageKey) => string,
): string {
  if (status.state === 'loading') return t('Sidebar.status.loading_config');
  if (status.state === 'error') return t('Sidebar.status.config_unavailable');
  if (status.state === 'empty') return t('Sidebar.status.no_provider');
  const parts: string[] = [];
  if (status.privacyMode) {
    parts.push(t(PRIVACY_MODE_LABEL_KEYS[status.privacyMode] ?? 'Sidebar.status.unknown_privacy'));
  }
  if (status.provider) parts.push(status.provider);
  return parts.length > 0 ? parts.join(' · ') : t('Sidebar.status.no_provider');
}

export default function Sidebar({ isOpen, isMobileNav, onNavigate }: SidebarProps) {
  const { t, locale } = useTranslation();
  const runMatch = useMatch('/run/:runId/*');
  const activeRunId = runMatch?.params.runId;
  const runs = useRunsStore((s) => s.runs);
  const firstRunId = runs[0]?.run_id;
  const runId = activeRunId ?? firstRunId;
  const providerStatus = useProviderStatus();
  const providerStatusText = formatProviderStatus(providerStatus, t);

  const sections: NavSection[] = [
    {
      sectionKey: 'Sidebar.section.workspace',
      sectionId: 'workspace',
      items: [
        { to: '/welcome', Icon: Star, labelKey: 'Nav.welcome', labelEn: 'Welcome' },
        { to: '/', Icon: LayoutDashboard, labelKey: 'Nav.dashboard', labelEn: 'Dashboard', end: true },
        {
          to: runId ? `/run/${runId}/lesson` : '/',
          Icon: BookOpen,
          labelKey: 'Nav.lesson',
          labelEn: 'Lesson',
          disabled: !runId,
        },
        {
          to: runId ? `/run/${runId}/diff` : '/',
          Icon: GitCompareArrows,
          labelKey: 'Nav.diff',
          labelEn: 'Diff',
          disabled: !runId,
        },
        { to: '/ratchet', Icon: TrendingUp, labelKey: 'Ratchet.title', labelEn: 'Ratchet' },
      ],
    },
    {
      sectionKey: 'Sidebar.section.practice',
      sectionId: 'practice',
      items: [
        {
          to: runId ? `/run/${runId}/quiz` : '/',
          Icon: CircleHelp,
          labelKey: 'Nav.quiz',
          labelEn: 'Quiz',
          disabled: !runId,
        },
        { to: '/review', Icon: RefreshCw, labelKey: 'Review.title', labelEn: 'Review' },
        { to: '/concepts', Icon: Network, labelKey: 'Shell.concept_graph', labelEn: 'Concepts' },
      ],
    },
    {
      sectionKey: 'Sidebar.section.system',
      sectionId: 'system',
      items: [
        { to: '/onboarding', Icon: Play, labelKey: 'Nav.onboarding', labelEn: 'Get Started' },
        { to: '/guide', Icon: BookOpen, labelKey: 'Nav.guide', labelEn: 'Guide' },
        { to: '/settings', Icon: SettingsIcon, labelKey: 'Settings_page.title', labelEn: 'Settings' },
      ],
    },
  ];

  const latestRun = runs[0];
  let statusText: string;
  if (!latestRun) {
    statusText = t('Sidebar.status.no_runs');
  } else if (latestRun.created_at) {
    statusText = formatRelativeTime(latestRun.created_at, locale);
  } else {
    statusText = t('Sidebar.status.healthy');
  }

  const latestRunText = latestRun
    ? t('Sidebar.status.latest_run', {
        run: latestRun.source_ref || latestRun.run_id.slice(0, 8),
        time: statusText,
      })
    : t('Sidebar.status.no_runs');
  const mobileHidden = isMobileNav && !isOpen;

  return (
    <nav
      id="sidebar"
      className={`sidebar${isOpen ? ' sidebar--open' : ''}`}
      aria-label={t('Shell.nav_label')}
      aria-hidden={mobileHidden ? true : undefined}
      inert={mobileHidden ? true : undefined}
    >
      <div className="brand">
        <div className="brand-mark" aria-hidden="true"><span>&#916;&#30693;</span></div>
        <div className="sidebar__brand-text">
          <div className="brand-name">{t('Brand.name')}</div>
          <div className="brand-en">{t('Sidebar.tagline_short')}</div>
        </div>
      </div>

      {sections.map((section) => (
        <section
          key={section.sectionKey}
          className="nav-section sidebar__section"
          aria-labelledby={`sidebar-section-${section.sectionId}`}
        >
          <div
            id={`sidebar-section-${section.sectionId}`}
            className="nav-label"
          >
            {t(section.sectionKey)}
          </div>
          {section.items.map((item) => {
            const label = t(item.labelKey);
            const Icon = item.Icon;
            const disabledHint = t('Nav.needs_run_hint');
            return item.disabled ? (
              <span
                key={item.labelKey}
                className="nav-item sidebar__item nav-item--disabled sidebar__item--disabled"
                role="link"
                aria-disabled="true"
                tabIndex={0}
                title={`${label} — ${disabledHint}`}
                aria-label={`${label} (${disabledHint})`}
              >
                <span className="ic sidebar__icon" aria-hidden="true">
                  <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
                </span>
                <span className="sidebar__label-main">{label}</span>
                <span className="en sidebar__label-en" aria-hidden="true">{item.labelEn}</span>
              </span>
            ) : (
              <NavLink
                key={item.labelKey}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `nav-item sidebar__item${isActive ? ' active' : ''}`
                }
                onClick={onNavigate}
                title={label}
                aria-label={label}
              >
                <span className="ic sidebar__icon" aria-hidden="true">
                  <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
                </span>
                <span className="sidebar__label-main">{label}</span>
                <span className="en sidebar__label-en" aria-hidden="true">{item.labelEn}</span>
              </NavLink>
            );
          })}
        </section>
      ))}

      <div
        className="side-foot"
        aria-label={t('Sidebar.status.aria_label')}
        aria-live="polite"
      >
        <span className="dot" aria-hidden="true" />
        <div className="status-text">
          <span>{providerStatusText}</span>
          <span>{latestRunText}</span>
        </div>
        <a
          className="side-foot__github"
          href="https://github.com/AGI-is-going-to-arrive/ahadiff"
          target="_blank"
          rel="noopener noreferrer"
          aria-label={t('Sidebar.github_aria')}
        >
          <svg
            className="side-foot__github-icon"
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="currentColor"
            aria-hidden="true"
            focusable="false"
          >
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
          </svg>
          <span>{t('Sidebar.github_link')}</span>
        </a>
        <span className="side-foot__version mono">{VIEWER_VERSION}</span>
      </div>
    </nav>
  );
}
