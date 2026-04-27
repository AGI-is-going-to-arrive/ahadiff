import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/tokens.css';
import './styles/base.css';
import './styles/print.css';
import './styles/forced-colors.css';
import './styles/reduced-transparency.css';
import './styles/utility.css';
import './i18n/bootstrap';
import App from './App';

const container = document.getElementById('root');
if (!container) {
  throw new Error('Root element #root missing from index.html');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
