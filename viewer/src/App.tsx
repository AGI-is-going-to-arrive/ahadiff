import { lazy, Suspense } from 'react';
import { HashRouter, Route, Routes, Navigate } from 'react-router-dom';
import ErrorBoundary from './components/ErrorBoundary';
import { useTranslation } from './i18n/useTranslation';

// Phase 2G: every page is loaded lazily. Initial bundle only carries the
// shell (HashRouter + ErrorBoundary + Suspense fallback); page modules ship
// as async chunks. See plan §2G + risk R6 (bundle sizes are observed, not capped).
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
const GuidePage = lazy(() => import('./pages/GuidePage'));
const RunDetailPage = lazy(() => import('./pages/RunDetailPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));

// Token-backed splash so the lazy boundary doesn't flash a white frame on
// slower networks.
function RouteFallback() {
  const { t } = useTranslation();
  return (
    <div
      className="route-fallback"
      role="status"
      aria-live="polite"
    >
      {t('Serve.loading')}
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <HashRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<ErrorBoundary><DashboardPage /></ErrorBoundary>} />
            <Route path="/welcome" element={<ErrorBoundary><LandingPage /></ErrorBoundary>} />
            <Route path="/concepts" element={<ErrorBoundary><ConceptsPage /></ErrorBoundary>} />
            <Route path="/review" element={<ErrorBoundary><ReviewPage /></ErrorBoundary>} />
            <Route path="/ratchet" element={<ErrorBoundary><RatchetPage /></ErrorBoundary>} />
            <Route path="/settings" element={<ErrorBoundary><SettingsPage /></ErrorBoundary>} />
            <Route path="/onboarding" element={<ErrorBoundary><OnboardingPage /></ErrorBoundary>} />
            <Route path="/guide" element={<ErrorBoundary><GuidePage /></ErrorBoundary>} />
            <Route path="/skills" element={<Navigate to="/guide" replace />} />
            <Route path="/run/:runId" element={<ErrorBoundary><RunDetailPage /></ErrorBoundary>} />
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
