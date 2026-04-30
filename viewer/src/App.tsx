import { lazy, Suspense } from 'react';
import { HashRouter, Route, Routes } from 'react-router-dom';
import ErrorBoundary from './components/ErrorBoundary';
import { useTranslation } from './i18n/useTranslation';

// Phase 2G: every page is loaded lazily. Initial bundle only carries the
// shell (HashRouter + ErrorBoundary + Suspense fallback); page modules ship
// as async chunks. See plan §2G + risk R6 (bundle budget < 80KB gzip).
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const LessonPage = lazy(() => import('./pages/LessonPage'));
const DiffViewerPage = lazy(() => import('./pages/DiffViewerPage'));
const QuizPage = lazy(() => import('./pages/QuizPage'));
const ConceptsPage = lazy(() => import('./pages/ConceptsPage'));
const ReviewPage = lazy(() => import('./pages/ReviewPage'));
const RatchetPage = lazy(() => import('./pages/RatchetPage'));
const LandingPage = lazy(() => import('./pages/LandingPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const OnboardingPage = lazy(() => import('./pages/OnboardingPage'));
const SkillsPage = lazy(() => import('./pages/SkillsPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));

// Token-backed splash so the lazy boundary doesn't flash a white frame on
// slower networks. Uses inline styles to avoid a CSS import in the shell.
function RouteFallback() {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        minHeight: '60vh',
        display: 'grid',
        placeItems: 'center',
        color: 'var(--muted)',
        fontFamily: 'var(--font-sans)',
        fontSize: 14,
      }}
    >
      {t('Serve.loading')}
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <HashRouter>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<ErrorBoundary><DashboardPage /></ErrorBoundary>} />
            <Route path="/welcome" element={<ErrorBoundary><LandingPage /></ErrorBoundary>} />
            <Route path="/concepts" element={<ErrorBoundary><ConceptsPage /></ErrorBoundary>} />
            <Route path="/review" element={<ErrorBoundary><ReviewPage /></ErrorBoundary>} />
            <Route path="/ratchet" element={<ErrorBoundary><RatchetPage /></ErrorBoundary>} />
            <Route path="/settings" element={<ErrorBoundary><SettingsPage /></ErrorBoundary>} />
            <Route path="/onboarding" element={<ErrorBoundary><OnboardingPage /></ErrorBoundary>} />
            <Route path="/skills" element={<ErrorBoundary><SkillsPage /></ErrorBoundary>} />
            <Route path="/run/:runId/lesson" element={<ErrorBoundary><LessonPage /></ErrorBoundary>} />
            <Route path="/run/:runId/diff" element={<ErrorBoundary><DiffViewerPage /></ErrorBoundary>} />
            <Route path="/run/:runId/quiz" element={<ErrorBoundary><QuizPage /></ErrorBoundary>} />
            <Route path="*" element={<ErrorBoundary><NotFoundPage /></ErrorBoundary>} />
          </Routes>
        </Suspense>
      </HashRouter>
    </ErrorBoundary>
  );
}
