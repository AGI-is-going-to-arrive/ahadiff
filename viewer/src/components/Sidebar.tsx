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
  ariaLabel: string;
  items: NavEntry[];
}

interface SidebarProps {
  isOpen: boolean;
  isMobileNav: boolean;
  onNavigate?: () => void;
}

const VIEWER_VERSION = 'v1.1.0-alpha.0';

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

export default function Sidebar({ isOpen, isMobileNav, onNavigate }: SidebarProps) {
  const { t, locale } = useTranslation();
  const runMatch = useMatch('/run/:runId/*');
  const activeRunId = runMatch?.params.runId;
  const runs = useRunsStore((s) => s.runs);
  const firstRunId = runs[0]?.run_id;
  const runId = activeRunId ?? firstRunId;

  const sections: NavSection[] = [
    {
      sectionKey: 'Sidebar.section.workspace',
      ariaLabel: 'Workspace',
      items: [
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
      ariaLabel: 'Practice',
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
      ariaLabel: 'System',
      items: [
        { to: '/welcome', Icon: Star, labelKey: 'Nav.welcome', labelEn: 'Welcome' },
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
      <div className="sidebar__brand">
        <div className="sidebar__brand-mark" aria-hidden="true"><span>&#916;&#30693;</span></div>
        <div className="sidebar__brand-text">
          <div className="sidebar__brand-name">{t('Brand.name')}</div>
          <div className="sidebar__brand-en">{t('Sidebar.tagline_short')}</div>
        </div>
      </div>

      {sections.map((section) => (
        <section
          key={section.sectionKey}
          className="sidebar__section"
          aria-labelledby={`sidebar-section-${section.ariaLabel.toLowerCase()}`}
        >
          <div
            id={`sidebar-section-${section.ariaLabel.toLowerCase()}`}
            className="sidebar__label"
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
                className="sidebar__item sidebar__item--disabled"
                role="link"
                aria-disabled="true"
                tabIndex={-1}
                title={`${label} — ${disabledHint}`}
                aria-label={`${label} (${disabledHint})`}
              >
                <span className="sidebar__icon" aria-hidden="true">
                  <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
                </span>
                <span className="sidebar__label-main">{label}</span>
                <span className="sidebar__label-en" aria-hidden="true">{item.labelEn}</span>
              </span>
            ) : (
              <NavLink
                key={item.labelKey}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `sidebar__item${isActive ? ' sidebar__item--active' : ''}`
                }
                onClick={onNavigate}
                title={label}
                aria-label={label}
              >
                <span className="sidebar__icon" aria-hidden="true">
                  <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
                </span>
                <span className="sidebar__label-main">{label}</span>
                <span className="sidebar__label-en" aria-hidden="true">{item.labelEn}</span>
              </NavLink>
            );
          })}
        </section>
      ))}

      <div
        className="sidebar__status"
        aria-label={t('Sidebar.status.aria_label')}
        aria-live="polite"
      >
        <span className="sidebar__status-dot" aria-hidden="true" />
        <span className="sidebar__status-copy">
          <span className="sidebar__status-mode">{t('Sidebar.status.mode')}</span>
          <span className="sidebar__status-run">{latestRunText}</span>
        </span>
        <span className="sidebar__status-version">{VIEWER_VERSION}</span>
      </div>
    </nav>
  );
}
