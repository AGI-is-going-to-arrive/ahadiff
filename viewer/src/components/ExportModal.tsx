import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from '../i18n/useTranslation';
import {
  ApiError,
  exportApkg,
  exportPreview,
  exportResults,
  type ExportPreviewManifest,
} from '../api/client';
import '../styles/export-modal.css';

interface ExportModalProps {
  open: boolean;
  onClose: () => void;
  runId?: string;
}

type ExportKey = 'preview' | 'tsv' | 'json' | 'apkg';

interface DownloadState {
  busyKey: ExportKey | null;
  error: string | null;
  previewManifest: ExportPreviewManifest | null;
}

const INITIAL_STATE: DownloadState = { busyKey: null, error: null, previewManifest: null };

function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  try {
    a.click();
  } finally {
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

function getApiErrorCode(err: unknown): string | null {
  if (err instanceof ApiError) return err.errorCode;
  return null;
}

function getApiErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

export default function ExportModal({ open, onClose, runId }: ExportModalProps) {
  const { t } = useTranslation();
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFocusRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const [state, setState] = useState<DownloadState>(INITIAL_STATE);

  const resetTransient = useCallback(() => setState(INITIAL_STATE), []);

  // Preserve inert state of body siblings while the dialog portal is open.
  useEffect(() => {
    if (!open) return undefined;
    const overlay = overlayRef.current;
    if (!overlay) return undefined;
    const siblings = Array.from(document.body.children).filter(
      (el): el is HTMLElement => el instanceof HTMLElement && el !== overlay,
    );
    const previous = siblings.map((el) => ({
      el,
      hadInert: el.hasAttribute('inert'),
      inertValue: el.getAttribute('inert'),
    }));
    for (const { el } of previous) el.setAttribute('inert', '');
    return () => {
      for (const { el, hadInert, inertValue } of previous) {
        if (hadInert) el.setAttribute('inert', inertValue ?? '');
        else el.removeAttribute('inert');
      }
    };
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    resetTransient();
    const raf = requestAnimationFrame(() => {
      // Prefer the first enabled action button. If it's disabled (e.g. preview
      // requires runId), fall back to any other enabled action, then finally to
      // the dialog container itself so focus never escapes into the (now inert)
      // background and Tab still cycles inside the modal.
      const target = firstFocusRef.current;
      if (target && !target.disabled) {
        target.focus();
        return;
      }
      const dialog = dialogRef.current;
      const fallback = dialog?.querySelector<HTMLButtonElement>('button:not([disabled])');
      if (fallback) {
        fallback.focus();
        return;
      }
      dialog?.focus();
    });
    return () => {
      cancelAnimationFrame(raf);
      restoreFocusRef.current?.focus({ preventScroll: true });
      restoreFocusRef.current = null;
    };
  }, [open, resetTransient]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // Focus trap (Tab/Shift+Tab cycles within the dialog).
  useEffect(() => {
    if (!open || !dialogRef.current) return undefined;
    const dialog = dialogRef.current;
    const onFocusTrap = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const focusable = dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    dialog.addEventListener('keydown', onFocusTrap);
    return () => dialog.removeEventListener('keydown', onFocusTrap);
  }, [open]);

  const handleDownload = useCallback(
    async (key: ExportKey) => {
      setState({ busyKey: key, error: null, previewManifest: null });
      try {
        if (key === 'preview') {
          if (!runId) {
            setState({
              busyKey: null,
              error: t('Export.error', { message: t('Export.preview_requires_run') }),
              previewManifest: null,
            });
            return;
          }
          const manifest = await exportPreview(runId);
          setState({ busyKey: null, error: null, previewManifest: manifest });
        } else if (key === 'tsv' || key === 'json') {
          const blob = await exportResults(key);
          triggerBlobDownload(blob, `results.${key}`);
          setState(INITIAL_STATE);
        } else {
          const blob = await exportApkg();
          triggerBlobDownload(blob, 'ahadiff_review.apkg');
          setState(INITIAL_STATE);
        }
      } catch (err) {
        const code = getApiErrorCode(err);
        const message = code ?? getApiErrorMessage(err);
        setState({
          busyKey: null,
          error: t('Export.error', { message }),
          previewManifest: null,
        });
      }
    },
    [runId, t],
  );

  if (!open) return null;

  const items: Array<{
    key: ExportKey;
    title: string;
    desc: string;
    disabled?: boolean;
  }> = [
    {
      key: 'preview',
      title: t('Export.preview_title'),
      desc: t('Export.preview_desc'),
      disabled: !runId,
    },
    { key: 'tsv', title: t('Export.tsv_title'), desc: t('Export.tsv_desc') },
    { key: 'json', title: t('Export.json_title'), desc: t('Export.json_desc') },
    { key: 'apkg', title: t('Export.apkg_title'), desc: t('Export.apkg_desc') },
  ];

  return createPortal(
    <div ref={overlayRef} className="export-modal__overlay" role="presentation" onClick={onClose}>
      <div
        ref={dialogRef}
        className="export-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="export-modal-title"
        aria-describedby="export-modal-subtitle"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="export-modal__header">
          <h2 id="export-modal-title" className="export-modal__title">
            {t('Export.title')}
          </h2>
          <p id="export-modal-subtitle" className="export-modal__subtitle">
            {t('Export.description')}
          </p>
          <kbd className="export-modal__esc">Esc</kbd>
        </header>

        <div className="export-modal__body">
          <ul className="export-modal__list">
            {items.map((item, idx) => {
              const isBusy = state.busyKey === item.key;
              const itemDisabled = item.disabled === true;
              return (
                <li
                  key={item.key}
                  className={`export-modal__item${itemDisabled ? ' export-modal__item--disabled' : ''}`}
                >
                  <div className="export-modal__item-copy">
                    <span className="export-modal__item-title">{item.title}</span>
                    <span className="export-modal__item-desc">{item.desc}</span>
                  </div>
                  <button
                    ref={idx === 0 ? firstFocusRef : undefined}
                    type="button"
                    className="export-modal__btn export-modal__btn--primary"
                    disabled={itemDisabled || isBusy || state.busyKey !== null}
                    aria-busy={isBusy || undefined}
                    onClick={() => void handleDownload(item.key)}
                  >
                    {isBusy ? (
                      <span className="export-modal__btn-busy">
                        <span className="export-modal__spinner" aria-hidden="true" />
                        <span>{t('Export.downloading')}</span>
                      </span>
                    ) : (
                      t('Export.download')
                    )}
                  </button>
                </li>
              );
            })}
          </ul>

          {state.previewManifest && (
            <p className="export-modal__success" role="status">
              {t('Export.preview_written', {
                path: state.previewManifest.path,
                files: state.previewManifest.file_count,
              })}
            </p>
          )}

          {state.error && (
            <p className="export-modal__error" role="alert">
              {state.error}
            </p>
          )}
        </div>

        <footer className="export-modal__footer">
          <button
            type="button"
            className="export-modal__btn export-modal__btn--ghost"
            onClick={onClose}
          >
            {t('Export.close')}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
