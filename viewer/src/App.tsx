import { HashRouter, Route, Routes } from 'react-router-dom';
import DashboardPage from './pages/DashboardPage';
import LessonPage from './pages/LessonPage';
import DiffViewerPage from './pages/DiffViewerPage';
import QuizPage from './pages/QuizPage';
import ConceptsPage from './pages/ConceptsPage';
import ReviewPage from './pages/ReviewPage';
import RatchetPage from './pages/RatchetPage';
import LandingPage from './pages/LandingPage';
import SettingsPage from './pages/SettingsPage';
import OnboardingPage from './pages/OnboardingPage';
import SkillsPage from './pages/SkillsPage';
import NotFoundPage from './pages/NotFoundPage';
import ErrorBoundary from './components/ErrorBoundary';

export default function App() {
  return (
    <ErrorBoundary>
      <HashRouter>
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
      </HashRouter>
    </ErrorBoundary>
  );
}
