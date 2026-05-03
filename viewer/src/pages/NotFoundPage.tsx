import { Link } from 'react-router-dom';
import AppShell from '../components/AppShell';
import { useTranslation } from '../i18n/useTranslation';

export default function NotFoundPage() {
  const { t } = useTranslation();

  return (
    <AppShell>
      <div className="error-boundary__fallback" role="alert">
        <h1>{t('Error.not_found')}</h1>
        <p>
          <Link to="/">{t('Error.back_to_dashboard')}</Link>
        </p>
      </div>
    </AppShell>
  );
}
