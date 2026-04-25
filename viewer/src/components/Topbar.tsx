import { useTranslation } from '../i18n/useTranslation';
import LanguageSwitcher from './LanguageSwitcher';

export default function Topbar() {
  const { t } = useTranslation();

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <div className="topbar__brand-mark" aria-hidden="true">
          <span>{'Δ知'}</span>
        </div>
        <span className="topbar__brand-name">{t('Brand.name')}</span>
      </div>

      <div className="topbar__spacer" />

      <LanguageSwitcher />
    </header>
  );
}
