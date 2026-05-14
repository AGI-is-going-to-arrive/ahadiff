import { Component, useCallback, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from 'react';
import { useTranslation } from '../i18n/useTranslation';
import './ErrorBoundary.css';

const MAX_RETRIES = 3;
const SENSITIVE_ASSIGNMENT_RE =
  /\b(api[_-]?key|token|secret|password|authorization|access[_-]?token|refresh[_-]?token)(?:=|:)\s*([^&\s]+)/gi;
const BEARER_RE = /\bBearer\s+[A-Za-z0-9._~+/=-]+/gi;
const SECRET_TOKEN_RE = /\b(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9_]{8,}|xox[baprs]-[A-Za-z0-9-]{8,})\b/g;
const LOCAL_PATH_RE = /(?:file:\/\/)?(?:\/Users\/[^)\s]+|[A-Za-z]:\\[^)\s]+)/g;

function redactDiagnostics(value: string): string {
  return value
    .replace(BEARER_RE, 'Bearer [redacted]')
    .replace(SENSITIVE_ASSIGNMENT_RE, (_match, key: string) => `${key}=[redacted]`)
    .replace(SECRET_TOKEN_RE, '[redacted-secret]')
    .replace(LOCAL_PATH_RE, '[local-path]');
}

function safeDiagnostic(value: string | null | undefined, fallback: string): string {
  const text = value && value.trim() ? value : fallback;
  return redactDiagnostics(text);
}

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      /* Fall back to the legacy selection path below. */
    }
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.inset = '0 auto auto -9999px';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try {
    if (!document.execCommand('copy')) throw new Error('clipboard_unavailable');
  } finally {
    textarea.remove();
  }
}

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  scope?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
  componentStack: string | null;
  retryCount: number;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null, componentStack: null, retryCount: 0 };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(_error: Error, info: ErrorInfo): void {
    this.setState({ componentStack: info.componentStack ?? null });
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] caught:', _error, info.componentStack);
  }

  private handleRetry = () => {
    this.setState((prev) => ({
      hasError: false,
      error: null,
      componentStack: null,
      retryCount: prev.retryCount + 1,
    }));
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <DefaultErrorFallback
          error={this.state.error}
          componentStack={this.state.componentStack}
          retryCount={this.state.retryCount}
          maxRetries={MAX_RETRIES}
          scope={this.props.scope ?? 'app'}
          onRetry={this.handleRetry}
        />
      );
    }
    return this.props.children;
  }
}

interface FallbackProps {
  error: Error | null;
  componentStack: string | null;
  retryCount: number;
  maxRetries: number;
  scope: string;
  onRetry: () => void;
}

function DefaultErrorFallback({ error, componentStack, retryCount, maxRetries, scope, onRetry }: FallbackProps): ReactNode {
  const { t } = useTranslation();
  const primaryRef = useRef<HTMLButtonElement>(null);
  const copiedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    primaryRef.current?.focus();
  }, []);

  useEffect(() => () => {
    if (copiedTimerRef.current !== null) clearTimeout(copiedTimerRef.current);
  }, []);

  const remaining = maxRetries - retryCount;
  const exhausted = remaining <= 0;
  const rawMessage = error?.message ?? '';
  const rawStack = error?.stack ?? '';
  const rawDiagnostic = rawStack.includes(rawMessage)
    ? rawStack
    : [rawMessage, rawStack].filter(Boolean).join('\n');
  const diagnosticStack = safeDiagnostic(rawDiagnostic, '(none)');
  const diagnosticComponentStack = componentStack ? redactDiagnostics(componentStack) : '';

  const buildPayload = useCallback(() => {
    const lines = [
      'AhaDiff error report',
      `scope: ${scope}`,
      `message: ${safeDiagnostic(error?.message, 'unknown')}`,
      `retry: ${retryCount}/${maxRetries}`,
      `ua: ${safeDiagnostic(navigator.userAgent, 'unknown')}`,
      `href: ${safeDiagnostic(window.location.hash, '#')}`,
      '',
      'stack:',
      diagnosticStack,
    ];
    if (diagnosticComponentStack) {
      lines.push('', 'componentStack:', diagnosticComponentStack);
    }
    return lines.join('\n');
  }, [diagnosticComponentStack, diagnosticStack, error, retryCount, maxRetries, scope]);

  const handleCopy = useCallback(async () => {
    try {
      await copyText(buildPayload());
      setCopied(true);
      if (copiedTimerRef.current !== null) clearTimeout(copiedTimerRef.current);
      copiedTimerRef.current = setTimeout(() => {
        copiedTimerRef.current = null;
        setCopied(false);
      }, 2000);
    } catch {
      setCopied(false);
    }
  }, [buildPayload]);

  return (
    <div role="alert" className="error-boundary__fallback">
      <div className="error-boundary__header">
        <h2 className="error-boundary__title">{t('Error.boundary_title')}</h2>
        <span className="error-boundary__meta">
          {scope} · {retryCount}/{maxRetries}
        </span>
      </div>
      <p className="error-boundary__body">{t('Error.boundary_body')}</p>
      {error && (
        <details className="error-boundary__details">
          <summary>{t('Error.boundary_details')}</summary>
          <pre className="error-boundary__stack">
            {diagnosticStack}
            {diagnosticComponentStack ? `\n\nComponent stack:${diagnosticComponentStack}` : ''}
          </pre>
        </details>
      )}
      {exhausted && (
        <p className="error-boundary__exhausted">{t('Error.boundary_exhausted')}</p>
      )}
      <div className="error-boundary__actions">
        <button
          ref={exhausted ? undefined : primaryRef}
          type="button"
          className="error-boundary__btn error-boundary__btn--primary"
          onClick={onRetry}
          disabled={exhausted}
        >
          {exhausted ? t('Error.retry') : t('Error.boundary_retry_n', { n: String(remaining) })}
        </button>
        <button
          ref={exhausted ? primaryRef : undefined}
          type="button"
          className={`error-boundary__btn ${copied ? 'error-boundary__btn--copied' : ''}`}
          onClick={handleCopy}
        >
          {copied ? t('Error.boundary_copied') : t('Error.boundary_copy')}
        </button>
        <button
          type="button"
          className="error-boundary__btn"
          onClick={() => window.location.reload()}
        >
          {t('Error.boundary_reload')}
        </button>
      </div>
    </div>
  );
}
