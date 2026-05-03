import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from '../i18n/useTranslation';
import './InfoHint.css';

interface InfoHintProps {
  label: string;
  children?: React.ReactNode;
  position?: 'top' | 'bottom';
}

export default function InfoHint({ label, children, position = 'bottom' }: InfoHintProps) {
  const { t } = useTranslation();
  const id = useId();
  const [open, setOpen] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  function show() {
    clearTimeout(timeoutRef.current);
    timeoutRef.current = undefined;
    setOpen(true);
  }
  function hide() {
    clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      setOpen(false);
      timeoutRef.current = undefined;
    }, 120);
  }

  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape' && open) {
      e.stopPropagation();
      setOpen(false);
    }
  }, [open]);

  useEffect(() => {
    return () => clearTimeout(timeoutRef.current);
  }, []);

  return (
    <span
      className="info-hint"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onKeyDown={onKeyDown}
    >
      <button
        type="button"
        className="info-hint__trigger"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-describedby={open ? id : undefined}
        aria-label={t('A11y.more_info')}
      >
        {children ?? <span className="info-hint__icon" aria-hidden="true">&#9432;</span>}
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className={`info-hint__bubble info-hint__bubble--${position}`}
        >
          {label}
        </span>
      )}
    </span>
  );
}
