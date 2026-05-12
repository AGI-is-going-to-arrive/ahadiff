import { useCallback, useEffect, useRef, useState } from 'react';
import { copyToClipboard } from '../utils/clipboard';
import './CommandBlock.css';

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
    void copyToClipboard(text).then((ok) => {
      if (ok) flashCopied();
    });
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
