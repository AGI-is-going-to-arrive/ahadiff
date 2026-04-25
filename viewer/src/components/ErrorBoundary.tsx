import { Component, useEffect, useRef, type ErrorInfo, type ReactNode } from 'react';
import { useTranslation } from '../i18n/useTranslation';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(_error: Error): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] caught:', error, info.componentStack);
  }

  private handleRetry = () => {
    this.setState({ hasError: false });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return this.props.fallback ?? <DefaultErrorFallback onRetry={this.handleRetry} />;
    }
    return this.props.children;
  }
}

function DefaultErrorFallback({ onRetry }: { onRetry: () => void }): ReactNode {
  // Localized via Zustand-backed useTranslation (no React Context required), so it
  // remains safe to render even when the failed subtree included i18n consumers.
  const { t } = useTranslation();
  const retryRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    // Move focus to the retry button so screen readers announce the error region
    // and keyboard users land on the recoverable action.
    retryRef.current?.focus();
  }, []);
  return (
    <div role="alert" className="error-boundary__fallback">
      <h2>{t('Error.boundary_title')}</h2>
      <p>{t('Error.boundary_body')}</p>
      <button
        ref={retryRef}
        type="button"
        className="error-boundary__retry"
        onClick={onRetry}
      >
        {t('Error.retry')}
      </button>
    </div>
  );
}
