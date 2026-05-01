import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/fonts.css';
import './styles/tokens.css';
import './styles/base.css';
import './styles/utility.css';
// Media-query overrides must load AFTER the base utility/component CSS so
// their @media rules (print / forced-colors / reduced-transparency) win at
// equal specificity in the cascade. Placing them earlier would let later-
// loaded rules (utility.css base, lazy component CSS) override them. F-01.
import './styles/print.css';
import './styles/forced-colors.css';
import './styles/reduced-transparency.css';
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
