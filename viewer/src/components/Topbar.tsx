import type { Ref } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation, type TranslationKey } from '../i18n/useTranslation';
import { useLearnStore } from '../state/learn-store';
import { detectPlatform } from '../utils/platform';
import LanguageSwitcher from './LanguageSwitcher';
import './Topbar.css';

interface TopbarProps {
  isMenuOpen: boolean;
  menuButtonRef?: Ref<HTMLButtonElement>;
  onMenuToggle: () => void;
  /** Phase 4B: opens the global Cmd/Ctrl+K search overlay. */
  onSearchOpen?: () => void;
  onLearnDialogOpen?: () => void;
}

const ROUTE_TO_KEY: Array<[RegExp, TranslationKey]> = [
  [/^\/$/, 'Nav.dashboard'],
  [/^\/run\/[^/]+\/lesson/, 'Nav.lesson'],
  [/^\/run\/[^/]+\/diff/, 'Nav.diff'],
  [/^\/run\/[^/]+\/quiz/, 'Nav.quiz'],
  [/^\/concepts/, 'Shell.concept_graph'],
  [/^\/review/, 'Review.title'],
  [/^\/ratchet/, 'Ratchet.title'],
  [/^\/guide/, 'Nav.guide'],
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
  onLearnDialogOpen,
}: TopbarProps) {
  const { t } = useTranslation();
  const currentKey = useCurrentPageKey();
  const learnPhase = useLearnStore((s) => s.phase);
  const requestLearn = useLearnStore((s) => s.requestLearn);
  const isBusy = learnPhase === 'submitting' || learnPhase === 'running' || learnPhase === 'cancelling' || learnPhase === 'estimating' || learnPhase === 'confirming';
  const newRunLabel = isBusy ? t('Topbar.new_run_running') : t('Topbar.new_run');
  const newRunShort = isBusy ? t('Topbar.new_run_running') : t('Topbar.new_run_short');
  const newRunAriaLabel = isBusy ? t('Topbar.new_run_running') : t('Topbar.new_run_aria');
  const searchKbdKey: TranslationKey = detectPlatform() === 'macos' ? 'Topbar.search_kbd_mac' : 'Topbar.search_kbd_other';

  return (
    <header className="topbar" data-glass>
      <button
        type="button"
        className="mobile-nav-btn"
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

      <nav className="topbar-crumb" aria-label={t('A11y.breadcrumb')}>
        <ol>
          <li>
            <span>{t('Topbar.crumb_root')}</span>
          </li>
          <li className="topbar-crumb-sep" aria-hidden="true">/</li>
          <li aria-current="page">{t(currentKey)}</li>
        </ol>
      </nav>

      {onSearchOpen ? (
        <button
          type="button"
          className="search"
          aria-label={t('Topbar.search_aria')}
          onClick={(event) => {
            event.currentTarget.focus({ preventScroll: true });
            onSearchOpen();
          }}
        >
          <span aria-hidden="true">⌕</span>
          <span>{t('Topbar.search_placeholder')}</span>
          <kbd>{t(searchKbdKey)}</kbd>
        </button>
      ) : (
        <div
          className="search topbar__search--inactive"
          role="note"
          aria-disabled="true"
          aria-label={t('Topbar.search_unavailable')}
          title={t('Topbar.search_unavailable')}
        >
          <span aria-hidden="true">⌕</span>
          <span>{t('Topbar.search_placeholder')}</span>
          <kbd>{t(searchKbdKey)}</kbd>
        </div>
      )}

      <div className="topbar__actions">
        <a
          className="btn ghost"
          href="https://github.com/agi-is-coming/ahadiff#readme"
          target="_blank"
          rel="noopener noreferrer"
          aria-label={t('Topbar.docs_aria')}
        >
          {t('Topbar.docs')}
        </a>
        <button
          type="button"
          className={`btn btn-inkstone${isBusy ? ' topbar__btn--busy' : ''}`}
          disabled={isBusy}
          aria-label={newRunAriaLabel}
          onClick={onLearnDialogOpen ?? (() => void requestLearn())}
        >
          <span className="topbar__btn-full">{newRunLabel}</span>
          <span className="topbar__btn-short">{newRunShort}</span>
        </button>
        <LanguageSwitcher />
      </div>
    </header>
  );
}
