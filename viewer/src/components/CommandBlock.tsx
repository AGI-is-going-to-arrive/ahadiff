import { useCallback, useEffect, useRef, useState } from 'react';
import './CommandBlock.css';

function fallbackCopy(text: string, onSuccess: () => void): void {
  let textarea: HTMLTextAreaElement | null = null;
  try {
    if (!document.body) return;
    textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.readOnly = true;
    textarea.tabIndex = -1;
    textarea.setAttribute('aria-hidden', 'true');
    textarea.className = 'command-block__clipboard-sink';
    document.body.appendChild(textarea);
    textarea.focus({ preventScroll: true });
    textarea.select();
    textarea.setSelectionRange(0, text.length);
    const ok = document.execCommand('copy');
    if (ok) onSuccess();
  } catch {
    // copy is a non-essential affordance — fail silently
  } finally {
    textarea?.parentNode?.removeChild(textarea);
  }
}

export interface CopyButtonProps {
  text: string;
  className?: string;
  copyLabel: string;
  copiedLabel: string;
}

export function CopyButton({
  text,
  className,
  copyLabel,
  copiedLabel,
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
        resetTimerRef.current = null;
      }
    };
  }, []);

  const flashCopied = useCallback(() => {
    if (!mountedRef.current) return;
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
    }
    setCopied(true);
    resetTimerRef.current = window.setTimeout(() => {
      setCopied(false);
      resetTimerRef.current = null;
    }, 1400);
  }, []);

  const handleCopy = useCallback(() => {
    const clipboard: Clipboard | undefined = navigator.clipboard;
    if (clipboard && typeof clipboard.writeText === 'function') {
      clipboard.writeText(text).then(flashCopied, () => fallbackCopy(text, flashCopied));
      return;
    }
    fallbackCopy(text, flashCopied);
  }, [text, flashCopied]);

  const baseClass = 'command-block__copy-btn';
  const stateClass = copied ? `${baseClass}--copied` : '';
  const extraClass = className ?? '';
  const fullClass = [baseClass, stateClass, extraClass].filter(Boolean).join(' ');

  return (
    <button
      type="button"
      className={fullClass}
      aria-label={copied ? copiedLabel : copyLabel}
      aria-live="polite"
      onClick={handleCopy}
    >
      {copied ? `✓ ${copiedLabel}` : copyLabel}
    </button>
  );
}

export interface CommandBlockProps {
  command: string;
  copyLabel: string;
  copiedLabel: string;
}

export function CommandBlock({ command, copyLabel, copiedLabel }: CommandBlockProps) {
  return (
    <div className="command-block">
      <pre className="command-block__code">{command}</pre>
      <CopyButton text={command} copyLabel={copyLabel} copiedLabel={copiedLabel} />
    </div>
  );
}
