import { useEffect, useRef, useState, type ReactElement } from 'react';
import type { LearnFileInput } from '../api/types';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import { buildFormatTexts, formatBytes } from '../utils/format';

export const MAX_LEARN_FILE_BYTES = 256 * 1024;

interface LearnFilePickerProps {
  side: 'before' | 'after' | 'document' | 'snapshot';
  value: LearnFileInput | null;
  disabled?: boolean;
  onChange: (value: LearnFileInput | null) => void;
  onPendingChange: (pending: boolean) => void;
}

export function isPortableFileName(name: string): boolean {
  return name.length > 0
    && Array.from(name).length <= 255
    && name === name.trim()
    && !['.', '..', '.git', '.ahadiff'].includes(name.toLowerCase())
    && !/[\\/:<>"|?*\u0000-\u001f\u007f]/.test(name)
    && !/[. ]$/.test(name)
    && !/^(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)/i.test(name)
    && !Array.from(name).some((character) =>
      character !== ' ' && /[\p{C}\p{Z}]/u.test(character));
}

/** FileReader can be aborted when a user replaces a selection or closes the dialog. */
export default function LearnFilePicker({
  side, value, disabled, onChange, onPendingChange,
}: LearnFilePickerProps): ReactElement {
  const { t, locale } = useTranslation();
  const [reading, setReading] = useState(false);
  const [errorKey, setErrorKey] = useState<MessageKey | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const readerRef = useRef<FileReader | null>(null);
  const generationRef = useRef(0);
  const id = `learn-file-${side}`;
  const sideLabel = t(side === 'before' ? 'LearnDialog.file_before'
    : side === 'after' ? 'LearnDialog.file_after'
      : side === 'document' ? 'LearnDialog.file_document' : 'Snapshots.file');
  const chooseLabel = t(value || reading ? 'LearnDialog.file_reselect' : 'LearnDialog.file_choose');

  useEffect(() => () => {
    generationRef.current += 1;
    readerRef.current?.abort();
  }, []);

  const cancelRead = (): void => {
    generationRef.current += 1;
    readerRef.current?.abort();
    readerRef.current = null;
    setReading(false);
    onPendingChange(false);
  };

  const rejectSelection = (key: MessageKey): void => {
    cancelRead();
    onChange(null);
    setErrorKey(key);
  };

  const selectFile = async (file: File): Promise<void> => {
    cancelRead();
    onChange(null);
    setErrorKey(null);
    if (!isPortableFileName(file.name)) {
      setErrorKey('LearnDialog.file_error_name');
      return;
    }
    if (side === 'document' && !/\.(md|markdown)$/i.test(file.name)) {
      setErrorKey('LearnDialog.document_error_format');
      return;
    }
    if (file.size > MAX_LEARN_FILE_BYTES) {
      setErrorKey('LearnDialog.file_error_size');
      return;
    }
    const generation = generationRef.current;
    setReading(true);
    onPendingChange(true);
    try {
      const data = await new Promise<ArrayBuffer>((resolve, reject) => {
        if (typeof FileReader === 'undefined') {
          if (typeof file.arrayBuffer === 'function') void file.arrayBuffer().then(resolve, reject);
          else reject(new Error('File reading unavailable'));
          return;
        }
        const reader = new FileReader();
        readerRef.current = reader;
        reader.onload = () => {
          if (reader.result instanceof ArrayBuffer) resolve(reader.result);
          else reject(new Error('Unexpected file content'));
        };
        reader.onerror = () => reject(new Error('File read failed'));
        reader.onabort = () => reject(new Error('File read cancelled'));
        reader.readAsArrayBuffer(file);
      });
      if (generation !== generationRef.current) return;
      // Recheck actual bytes; File.size is a preflight hint, not the content boundary.
      if (data.byteLength > MAX_LEARN_FILE_BYTES) {
        setErrorKey('LearnDialog.file_error_size');
        return;
      }
      if (new Uint8Array(data).includes(0)) {
        setErrorKey('LearnDialog.file_error_binary');
        return;
      }
      let content: string;
      if (typeof TextDecoder === 'undefined') {
        setErrorKey('LearnDialog.file_error_read');
        return;
      }
      try {
        content = new TextDecoder('utf-8', { fatal: true }).decode(data);
      } catch {
        setErrorKey('LearnDialog.file_error_utf8');
        return;
      }
      onChange({ name: file.name, content });
    } catch {
      if (generation === generationRef.current) setErrorKey('LearnDialog.file_error_read');
    } finally {
      if (generation === generationRef.current) {
        readerRef.current = null;
        setReading(false);
        onPendingChange(false);
      }
    }
  };

  return (
    <div
      className="learn-dialog__file-picker"
      aria-busy={reading}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = disabled ? 'none' : 'copy';
      }}
      onDrop={(event) => {
        event.preventDefault();
        if (disabled) return;
        const files = event.dataTransfer.files;
        if (files.length !== 1) rejectSelection('LearnDialog.file_error_count');
        else void selectFile(files[0]);
      }}
    >
      <label htmlFor={id} className="learn-dialog__file-label">
        {sideLabel}
      </label>
      <p id={`${id}-hint`} className="learn-dialog__file-hint">{t('LearnDialog.file_drop_hint')}</p>
      <input
        ref={inputRef}
        id={id}
        className="learn-dialog__file-input"
        type="file"
        accept={side === 'document' ? '.md,.markdown,text/markdown' : undefined}
        hidden
        disabled={disabled}
        aria-describedby={`${id}-hint${errorKey ? ` ${id}-error` : ''}`}
        aria-invalid={errorKey ? true : undefined}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (file) void selectFile(file);
        }}
      />
      <button
        type="button"
        className="learn-dialog__file-choose"
        disabled={disabled}
        aria-label={t('LearnDialog.file_action_aria', { action: chooseLabel, side: sideLabel })}
        aria-describedby={`${id}-hint ${id}-status`}
        onClick={() => inputRef.current?.click()}
      >
        {chooseLabel}
      </button>
      <div id={`${id}-status`} className="learn-dialog__file-status" role="status" aria-live="polite">
        {reading && <span>{t('LearnDialog.file_reading')}</span>}
        {value && (
          <>
            <strong>{value.name}</strong>
            <span>{formatBytes(new TextEncoder().encode(value.content).byteLength, locale, buildFormatTexts(t))}</span>
          </>
        )}
        {errorKey && <p id={`${id}-error`} className="learn-dialog__error">{t(errorKey)}</p>}
      </div>
      {(value || reading) && (
        <button
          type="button"
          className="learn-dialog__btn learn-dialog__btn--ghost"
          disabled={disabled}
          aria-label={t('LearnDialog.file_action_aria', { action: t('LearnDialog.file_remove'), side: sideLabel })}
          onClick={() => {
            cancelRead();
            onChange(null);
            setErrorKey(null);
          }}
        >
          {t('LearnDialog.file_remove')}
        </button>
      )}
    </div>
  );
}
