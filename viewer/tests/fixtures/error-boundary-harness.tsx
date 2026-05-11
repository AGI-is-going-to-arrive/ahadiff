import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import ErrorBoundary from '../../src/components/ErrorBoundary';

function CrashingChild(): never {
  throw new Error(
    'api_key=sk-testsecret123456 Authorization: Bearer abcdef123456 /Users/alice/project/app.tsx',
  );
}

function ErrorBoundaryHarness() {
  const [mounted, setMounted] = useState(true);

  return (
    <div>
      <button type="button" onClick={() => setMounted(false)}>
        Unmount boundary
      </button>
      {mounted ? (
        <ErrorBoundary scope="harness">
          <CrashingChild />
        </ErrorBoundary>
      ) : (
        <h1>Unmounted</h1>
      )}
    </div>
  );
}

export function mountErrorBoundaryHarness(): void {
  document.body.innerHTML = '<div id="error-boundary-harness-root"></div>';
  const host = document.getElementById('error-boundary-harness-root');
  if (!host) throw new Error('missing_error_boundary_harness_root');
  createRoot(host).render(<ErrorBoundaryHarness />);
}
