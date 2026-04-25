import { HashRouter, Route, Routes } from 'react-router-dom';
import DashboardPage from './pages/DashboardPage';
import LessonPage from './pages/LessonPage';
import DiffViewerPage from './pages/DiffViewerPage';
import QuizPage from './pages/QuizPage';
import ConceptsPage from './pages/ConceptsPage';
import NotFoundPage from './pages/NotFoundPage';
import ErrorBoundary from './components/ErrorBoundary';

export default function App() {
  return (
    <ErrorBoundary>
      <HashRouter>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/concepts" element={<ConceptsPage />} />
          <Route path="/run/:runId/lesson" element={<LessonPage />} />
          <Route path="/run/:runId/diff" element={<DiffViewerPage />} />
          <Route path="/run/:runId/quiz" element={<QuizPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </HashRouter>
    </ErrorBoundary>
  );
}
