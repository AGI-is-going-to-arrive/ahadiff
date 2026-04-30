import type { Ref } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation, type TranslationKey } from '../i18n/useTranslation';
import LanguageSwitcher from './LanguageSwitcher';
import './Topbar.css';

interface TopbarProps {
  isMenuOpen: boolean;
  menuButtonRef?: Ref<HTMLButtonElement>;
  onMenuToggle: () => void;
  /** Phase 4B: opens the global Cmd/Ctrl+K search overlay. */
  onSearchOpen?: () => void;
}

const ROUTE_TO_KEY: Array<[RegExp, TranslationKey]> = [
  [/^\/$/, 'Nav.dashboard'],
  [/^\/run\/[^/]+\/lesson/, 'Nav.lesson'],
  [/^\/run\/[^/]+\/diff/, 'Nav.diff'],
  [/^\/run\/[^/]+\/quiz/, 'Nav.quiz'],
  [/^\/concepts/, 'Shell.concept_graph'],
  [/^\/review/, 'Review.title'],
  [/^\/ratchet/, 'Ratchet.title'],
  [/^\/skills/, 'Skills.title'],
  [/^\/settings/, 'Settings_page.title'],
  [/^\/welcome/, 'Nav.welcome'],
  [/^\/onboarding/, 'Nav.onboarding'],
];

function useCurrentPageKey(): TranslationKey {
  const { pathname } = useLocation();
  for (const [re, key] of ROUTE_TO_KEY) {
    if (re.test(pathname)) return key;
  }
  return 'Topbar.crumb_root';
}

export default function Topbar({
  isMenuOpen,
  menuButtonRef,
  onMenuToggle,
  onSearchOpen,
}: TopbarProps) {
  const { t } = useTranslation();
  const currentKey = useCurrentPageKey();

  return (
    <header className="topbar" data-glass>
      <button
        type="button"
        className="topbar__mobile-btn"
        ref={menuButtonRef}
        aria-label={
          isMenuOpen ? t('A11y.close_menu') : t('A11y.open_menu')
        }
        aria-controls="sidebar"
        aria-expanded={isMenuOpen}
        onClick={onMenuToggle}
      >
        ☰
      </button>

      <nav className="topbar__crumb" aria-label={t('A11y.breadcrumb')}>
        <ol>
          <li>
            <span className="topbar__crumb-root">{t('Topbar.crumb_root')}</span>
          </li>
          <li className="topbar__crumb-sep" aria-hidden="true">/</li>
          <li aria-current="page">{t(currentKey)}</li>
        </ol>
      </nav>

      {onSearchOpen ? (
        <button
          type="button"
          className="topbar__search"
          aria-label={t('Topbar.search_aria')}
          onClick={onSearchOpen}
        >
          <span className="topbar__search-icon" aria-hidden="true">⌕</span>
          <span className="topbar__search-placeholder">{t('Topbar.search_placeholder')}</span>
          <kbd className="topbar__search-kbd">{t('Topbar.search_kbd')}</kbd>
        </button>
      ) : (
        <div
          className="topbar__search topbar__search--inactive"
          role="note"
          aria-disabled="true"
          aria-label={t('Topbar.search_unavailable')}
          title={t('Topbar.search_unavailable')}
        >
          <span className="topbar__search-icon" aria-hidden="true">⌕</span>
          <span className="topbar__search-placeholder">{t('Topbar.search_placeholder')}</span>
          <kbd className="topbar__search-kbd">{t('Topbar.search_kbd')}</kbd>
        </div>
      )}

      <div className="topbar__actions">
        <a
          className="topbar__btn topbar__btn--ghost"
          href="https://github.com/agi-is-coming/ahadiff#readme"
          target="_blank"
          rel="noopener noreferrer"
          aria-label={t('Topbar.docs_aria')}
        >
          {t('Topbar.docs')}
        </a>
        <span
          className="topbar__btn topbar__btn--primary topbar__btn--inactive"
          aria-disabled="true"
          title={t('Topbar.new_run_unavailable')}
        >
          {t('Topbar.new_run')}
        </span>
        <LanguageSwitcher />
      </div>
    </header>
  );
}
