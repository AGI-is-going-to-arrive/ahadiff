import { lazy, Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import Topbar from './Topbar';
import Sidebar from './Sidebar';
import LearnTaskBanner from './LearnTaskBanner';
import { OPEN_SEARCH_EVENT, type OpenSearchEventDetail } from './open-search-event';
import { useTranslation } from '../i18n/useTranslation';
import './AppShell.css';

/**
 * Phase 4B: SearchOverlay loads lazily on first ⌘K so its zod schema +
 * api/search dependency stays out of the < 80KB initial gzip budget.
 */
const SearchOverlay = lazy(() => import('./SearchOverlay'));
const LearnModeDialog = lazy(() => import('./LearnModeDialog'));

interface AppShellProps {
  children: ReactNode;
  globalShortcutsDisabled?: boolean;
}

/* Three-state sidebar paradigm:
 *   - >1024px: full sidebar (248px)
 *   - 769-1024px: icon-only rail (56px) — purely CSS, sidebar always visible
 *   - <=768px: drawer overlay with hamburger trigger
 * The `isMobileNav` JS state only flips to `true` for the drawer mode (<=768px).
 * Icon-rail is handled in CSS via media query so no JS state is needed. */
const DRAWER_QUERY = '(max-width: 768px)';

export default function AppShell({ children, globalShortcutsDisabled = false }: AppShellProps) {
  const { t } = useTranslation();
  const location = useLocation();
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [searchInitialQuery, setSearchInitialQuery] = useState<string>('');
  const [isLearnDialogOpen, setIsLearnDialogOpen] = useState(false);
  const [isMobileNav, setIsMobileNav] = useState(() =>
    typeof window === 'undefined' ? false : window.matchMedia(DRAWER_QUERY).matches,
  );

  useEffect(() => {
    const media = window.matchMedia(DRAWER_QUERY);
    const sync = () => setIsMobileNav(media.matches);
    sync();
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', sync);
      return () => media.removeEventListener('change', sync);
    }
    media.addListener(sync);
    return () => media.removeListener(sync);
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
      if (isLearnDialogOpen || globalShortcutsDisabled) return;
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
      setIsSearchOpen((open) => {
        if (open) return false;
        /* Fresh keyboard-driven open should not reuse a stale concept seed. */
        setSearchInitialQuery('');
        return true;
      });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [globalShortcutsDisabled, isLearnDialogOpen]);

  /* Close search on route change so it doesn't bleed across pages. */
  useEffect(() => {
    setIsSearchOpen(false);
  }, [location.pathname]);

  /**
   * Listen for `OPEN_SEARCH_EVENT` dispatched by ConceptGraph's detail panel
   * "Search this concept" link. Opens the global overlay and seeds the input
   * with the concept name. We coerce the detail to string to defend against
   * arbitrary dispatchers.
   */
  useEffect(() => {
    const onOpenSearch = (event: Event) => {
      const detail = (event as CustomEvent<OpenSearchEventDetail>).detail;
      const query = typeof detail?.query === 'string' ? detail.query : '';
      setSearchInitialQuery(query);
      setIsSearchOpen(true);
    };
    window.addEventListener(OPEN_SEARCH_EVENT, onOpenSearch);
    return () => window.removeEventListener(OPEN_SEARCH_EVENT, onOpenSearch);
  }, []);

  useEffect(() => {
    if (!isMobileNav && isSidebarOpen) setIsSidebarOpen(false);
  }, [isMobileNav, isSidebarOpen]);

  return (
    <div className={`app-shell${isSidebarOpen ? ' app-shell--sidebar-open' : ''}`}>
      <a
        className="skip-to-content"
        href="#main-content"
        onClick={(ev) => {
          ev.preventDefault();
          const el = document.getElementById('main-content');
          if (el) {
            const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            el.focus({ preventScroll: true });
            el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' });
          }
        }}
      >{t('A11y.skip_to_content')}</a>
      <Topbar
        isMenuOpen={isSidebarOpen}
        menuButtonRef={menuButtonRef}
        onMenuToggle={() => setIsSidebarOpen((open) => !open)}
        onSearchOpen={() => {
          setSearchInitialQuery('');
          setIsSearchOpen(true);
        }}
        onLearnDialogOpen={() => setIsLearnDialogOpen(true)}
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
        <main
          id="main-content"
          className="app-shell__content"
          tabIndex={-1}
          inert={isMobileNav && isSidebarOpen ? true : undefined}
        >
          <LearnTaskBanner />
          {children}
        </main>
      </div>
      {isSearchOpen ? (
        <Suspense fallback={null}>
          <SearchOverlay
            open={isSearchOpen}
            initialQuery={searchInitialQuery}
            onClose={() => {
              setIsSearchOpen(false);
              setSearchInitialQuery('');
            }}
          />
        </Suspense>
      ) : null}
      {isLearnDialogOpen ? (
        <Suspense fallback={null}>
          <LearnModeDialog open={isLearnDialogOpen} onClose={() => setIsLearnDialogOpen(false)} />
        </Suspense>
      ) : null}
    </div>
  );
}
