import { lazy, Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import Topbar from './Topbar';
import Sidebar from './Sidebar';
import { useTranslation } from '../i18n/useTranslation';
import './AppShell.css';

/**
 * Phase 4B: SearchOverlay loads lazily on first ⌘K so its zod schema +
 * api/search dependency stays out of the < 80KB initial gzip budget.
 */
const SearchOverlay = lazy(() => import('./SearchOverlay'));

interface AppShellProps {
  children: ReactNode;
}

/* V6 (`AhaDiff Warm v6.html:361`) collapses the sidebar into a drawer at
 * `max-width: 1024px`, not 768px. Honor that so 768px-1024px tablets get the
 * paradigm-switching mobile drawer + hamburger trigger instead of a desktop
 * sidebar that would dominate the viewport. */
const MOBILE_NAV_QUERY = '(max-width: 1024px)';

export default function AppShell({ children }: AppShellProps) {
  const { t } = useTranslation();
  const location = useLocation();
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [isMobileNav, setIsMobileNav] = useState(() =>
    typeof window === 'undefined' ? false : window.matchMedia(MOBILE_NAV_QUERY).matches,
  );

  useEffect(() => {
    const media = window.matchMedia(MOBILE_NAV_QUERY);
    const sync = () => setIsMobileNav(media.matches);
    sync();
    media.addEventListener('change', sync);
    return () => media.removeEventListener('change', sync);
  }, []);

  useEffect(() => {
    setIsSidebarOpen(false);
  }, [location.pathname]);

  const closeSidebar = useCallback((options?: { restoreFocus?: boolean }) => {
    setIsSidebarOpen(false);
    if (options?.restoreFocus) {
      window.requestAnimationFrame(() => menuButtonRef.current?.focus());
    }
  }, []);

  useEffect(() => {
    if (!isSidebarOpen) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeSidebar({ restoreFocus: true });
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [closeSidebar, isSidebarOpen]);

  /**
   * Phase 4B: ⌘K (Mac) / Ctrl+K (others) toggles the global search overlay.
   * Skip when the user is already typing inside an editable surface so we
   * don't fight with native shortcuts (input, textarea, contenteditable).
   */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'k' && event.key !== 'K') return;
      if (!(event.metaKey || event.ctrlKey)) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        /* Allow typing literal Ctrl+K text inside fields. */
        return;
      }
      event.preventDefault();
      setIsSearchOpen((open) => !open);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  /* Close search on route change so it doesn't bleed across pages. */
  useEffect(() => {
    setIsSearchOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!isMobileNav && isSidebarOpen) setIsSidebarOpen(false);
  }, [isMobileNav, isSidebarOpen]);

  return (
    <div className={`app-shell${isSidebarOpen ? ' app-shell--sidebar-open' : ''}`}>
      <a className="skip-to-content" href="#main-content">{t('A11y.skip_to_content')}</a>
      <Topbar
        isMenuOpen={isSidebarOpen}
        menuButtonRef={menuButtonRef}
        onMenuToggle={() => setIsSidebarOpen((open) => !open)}
        onSearchOpen={() => setIsSearchOpen(true)}
      />
      <div className="app-shell__body">
        <Sidebar
          isOpen={isSidebarOpen}
          isMobileNav={isMobileNav}
          onNavigate={closeSidebar}
        />
        <button
          type="button"
          className="app-shell__backdrop"
          aria-label={t('A11y.close_menu')}
          hidden={!isMobileNav || !isSidebarOpen}
          onClick={() => closeSidebar({ restoreFocus: true })}
        />
        <main id="main-content" className="app-shell__content" tabIndex={-1}>
          {children}
        </main>
      </div>
      {isSearchOpen ? (
        <Suspense fallback={null}>
          <SearchOverlay open={isSearchOpen} onClose={() => setIsSearchOpen(false)} />
        </Suspense>
      ) : null}
    </div>
  );
}
