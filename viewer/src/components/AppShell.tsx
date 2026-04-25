import type { ReactNode } from 'react';
import Topbar from './Topbar';
import Sidebar from './Sidebar';
import { useTranslation } from '../i18n/useTranslation';
import './AppShell.css';

interface AppShellProps {
  children: ReactNode;
}

export default function AppShell({ children }: AppShellProps) {
  const { t } = useTranslation();
  return (
    <div className="app-shell">
      <a className="skip-to-content" href="#main-content">{t('A11y.skip_to_content')}</a>
      <Topbar />
      <div className="app-shell__body">
        <Sidebar />
        <main id="main-content" className="app-shell__content" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
