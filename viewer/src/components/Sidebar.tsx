import { NavLink, useMatch } from 'react-router-dom';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import { useRunsStore } from '../state/runs-store';

interface NavEntry {
  to: string;
  icon: string;
  labelKey: MessageKey;
  end?: boolean;
  disabled?: boolean;
}

export default function Sidebar() {
  const { t } = useTranslation();
  const runMatch = useMatch('/run/:runId/*');
  const activeRunId = runMatch?.params.runId;
  const firstRunId = useRunsStore((s) => s.runs[0]?.run_id);
  const runId = activeRunId ?? firstRunId;

  const navItems: NavEntry[] = [
    { to: '/', icon: '▤', labelKey: 'Nav.dashboard', end: true },
    {
      to: runId ? `/run/${runId}/lesson` : '/',
      icon: '❦',
      labelKey: 'Nav.lesson',
      disabled: !runId,
    },
    {
      to: runId ? `/run/${runId}/diff` : '/',
      icon: '⇌',
      labelKey: 'Nav.diff',
      disabled: !runId,
    },
    {
      to: runId ? `/run/${runId}/quiz` : '/',
      icon: '?',
      labelKey: 'Nav.quiz',
      disabled: !runId,
    },
    { to: '/concepts', icon: '◈', labelKey: 'Shell.concept_graph' },
    { to: '/review', icon: '♻', labelKey: 'Review.title' },
    { to: '/ratchet', icon: '⚡', labelKey: 'Ratchet.title' },
    { to: '/skills', icon: '⚙', labelKey: 'Skills.title' },
    { to: '/settings', icon: '☰', labelKey: 'Settings_page.title' },
    { to: '/welcome', icon: '★', labelKey: 'Nav.welcome' },
    { to: '/onboarding', icon: '▶', labelKey: 'Nav.onboarding' },
  ];

  return (
    <nav className="sidebar" aria-label={t('Shell.nav_label')}>
      <div className="sidebar__section">
        <div className="sidebar__label">{t('Shell.nav_label')}</div>
        {navItems.map((item) =>
          item.disabled ? (
            <span
              key={item.labelKey}
              className="sidebar__item sidebar__item--disabled"
              aria-disabled="true"
              tabIndex={-1}
              title={t('Nav.needs_run_hint')}
            >
              <span className="sidebar__icon" aria-hidden="true">{item.icon}</span>
              <span>{t(item.labelKey)}</span>
            </span>
          ) : (
            <NavLink
              key={item.labelKey}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `sidebar__item${isActive ? ' sidebar__item--active' : ''}`
              }
            >
              <span className="sidebar__icon" aria-hidden="true">{item.icon}</span>
              <span>{t(item.labelKey)}</span>
            </NavLink>
          ),
        )}
      </div>
    </nav>
  );
}
