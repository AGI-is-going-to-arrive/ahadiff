import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react';
import { ApiError } from '../api/client';
import { deleteSnapshot, getSnapshot, listSnapshots, saveSnapshot } from '../api/snapshots';
import type { LearnFileInput, SnapshotListResponse, SnapshotSummary } from '../api/types';
import { useTranslation } from '../i18n/useTranslation';
import { getErrorMessage } from '../utils/error-codes';
import { buildFormatTexts, formatBytes } from '../utils/format';
import LearnFilePicker, { isPortableFileName } from './LearnFilePicker';

interface LearnSnapshotPickerProps {
  value: SnapshotSummary | null;
  disabled?: boolean;
  onChange: (value: SnapshotSummary | null) => void;
  onPendingChange: (pending: boolean) => void;
}

/** Snapshots are explicit, sanitized learning baselines. Never restore source files. */
export default function LearnSnapshotPicker({
  value, disabled, onChange, onPendingChange,
}: LearnSnapshotPickerProps): ReactElement {
  const { t, locale } = useTranslation();
  const [listing, setListing] = useState<SnapshotListResponse | null>(null);
  const [name, setName] = useState('');
  const [file, setFile] = useState<LearnFileInput | null>(null);
  const [reading, setReading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [saved, setSaved] = useState<SnapshotSummary | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const formatSize = (size: number): string => formatBytes(size, locale, buildFormatTexts(t));
  const usedBytes = listing?.snapshots.reduce((sum, snapshot) => sum + snapshot.stored_bytes, 0) ?? 0;
  const full = listing !== null
    && (listing.snapshots.length >= listing.max_count || usedBytes >= listing.max_bytes);
  const locked = Boolean(disabled) || busy;
  const nameInvalid = !isPortableFileName(name.trim()) || Array.from(name.trim()).length > 80;

  useEffect(() => { onPendingChange(busy || reading); }, [busy, reading, onPendingChange]);
  useEffect(() => () => requestRef.current?.abort(), []);

  const refresh = useCallback(async (): Promise<void> => {
    const controller = new AbortController();
    requestRef.current?.abort();
    requestRef.current = controller;
    setBusy(true);
    setFailed(false);
    setErrorCode(null);
    try {
      const result = await listSnapshots({ signal: controller.signal });
      if (!controller.signal.aborted) setListing(result);
    } catch (error: unknown) {
      if (controller.signal.aborted) return;
      setFailed(true);
      setErrorCode(error instanceof ApiError ? error.errorCode : null);
    } finally {
      if (requestRef.current === controller && !controller.signal.aborted) setBusy(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const mutate = async (operation: 'save' | 'delete' | 'select', snapshot?: SnapshotSummary): Promise<void> => {
    if (locked || reading || (operation === 'save' && (nameInvalid || !file || full))) return;
    const controller = new AbortController();
    requestRef.current?.abort();
    requestRef.current = controller;
    setBusy(true);
    setFailed(false);
    setErrorCode(null);
    setSaved(null);
    try {
      if (operation === 'save' && file) {
        const result = await saveSnapshot({ name: name.trim(), file }, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setSaved(result);
        setFile(null);
        setName('');
        if (result.status === 'ready') onChange(result);
      } else if (operation === 'select' && snapshot) {
        const record = await getSnapshot(snapshot.snapshot_id, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (record.content_hash !== snapshot.content_hash) throw new Error('Snapshot changed');
        onChange(snapshot);
      } else if (operation === 'delete' && snapshot?.record_hash) {
        await deleteSnapshot(snapshot.snapshot_id, snapshot.record_hash, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (value?.snapshot_id === snapshot.snapshot_id) onChange(null);
        setDeleteTarget(null);
      }
      if (operation !== 'select') {
        const result = await listSnapshots({ signal: controller.signal });
        if (!controller.signal.aborted) setListing(result);
      }
    } catch (error: unknown) {
      if (controller.signal.aborted) return;
      if (operation === 'select') onChange(null);
      setFailed(true);
      setErrorCode(error instanceof ApiError ? error.errorCode : null);
    } finally {
      if (requestRef.current === controller && !controller.signal.aborted) setBusy(false);
    }
  };

  return (
    <section className="learn-dialog__snapshots" aria-label={t('Snapshots.title')} aria-busy={busy}>
      <p className="learn-dialog__preview-hint">{t('Snapshots.privacy')}</p>
      <div className="learn-dialog__snapshot-save">
        <label htmlFor="learn-snapshot-name">{t('Snapshots.name')}</label>
        <input id="learn-snapshot-name" className="learn-dialog__input" value={name} maxLength={160}
          disabled={locked} onChange={(event) => setName(event.target.value)} />
        <LearnFilePicker side="snapshot" value={file} disabled={locked} onChange={setFile} onPendingChange={setReading} />
        <button type="button" className="learn-dialog__btn learn-dialog__btn--ghost" disabled={locked || reading || nameInvalid || !file || full || !listing}
          onClick={() => void mutate('save')}>{t('Snapshots.save')}</button>
      </div>
      {saved && <p role="status">{t(saved.sanitized ? 'Snapshots.saved_sanitized' : 'Snapshots.saved')}</p>}
      {listing && <p className="learn-dialog__file-hint">{t('Snapshots.capacity', {
        count: listing.snapshots.length, max: listing.max_count, used: formatSize(usedBytes), limit: formatSize(listing.max_bytes),
      })}</p>}
      {full && <p role="status" className="learn-dialog__error">{t('Snapshots.full')}</p>}
      {busy && <p role="status">{t('Serve.loading')}</p>}
      {failed && <p role="alert" className="learn-dialog__error">{getErrorMessage(t, errorCode, t('Snapshots.failed'))}</p>}
      <button type="button" className="learn-dialog__btn learn-dialog__btn--ghost" disabled={locked}
        onClick={() => void refresh()}>{t('Snapshots.refresh')}</button>
      {listing?.snapshots.length === 0 && <p role="status">{t('Snapshots.empty')}</p>}
      {listing && listing.snapshots.length > 0 && (
        <ul className="learn-dialog__snapshot-list">
          {listing.snapshots.map((snapshot) => (
            <li key={snapshot.snapshot_id} className="learn-dialog__snapshot-item">
              <div>
                <strong>{snapshot.name ?? snapshot.snapshot_id}</strong>
                <p className="learn-dialog__file-hint">{snapshot.file_name} · {formatSize(snapshot.size_bytes ?? snapshot.stored_bytes)}</p>
                {snapshot.created_at && <time dateTime={snapshot.created_at}>{new Date(snapshot.created_at).toLocaleString(locale)}</time>}
                <p>{t(`Snapshots.status_${snapshot.status}`)}</p>
                {snapshot.sanitized && <p className="learn-dialog__file-hint">{t('Snapshots.sanitized')}</p>}
              </div>
              <div className="learn-dialog__snapshot-actions">
                <button type="button" className="learn-dialog__btn learn-dialog__btn--ghost"
                  disabled={locked || snapshot.status !== 'ready' || !snapshot.content_hash}
                  aria-pressed={value?.snapshot_id === snapshot.snapshot_id}
                  onClick={() => void mutate('select', snapshot)}>{t(value?.snapshot_id === snapshot.snapshot_id ? 'Snapshots.selected' : 'Snapshots.select')}</button>
                <button type="button" className="learn-dialog__btn learn-dialog__btn--ghost" disabled={locked || !snapshot.record_hash}
                  onClick={() => setDeleteTarget(snapshot.snapshot_id)}>{t('Snapshots.delete')}</button>
              </div>
              {deleteTarget === snapshot.snapshot_id && (
                <div className="learn-dialog__snapshot-confirm" role="group" aria-label={t('Snapshots.delete')}>
                  <p>{t('Snapshots.delete_confirm', { name: snapshot.name ?? snapshot.snapshot_id })}</p>
                  <button type="button" className="learn-dialog__btn learn-dialog__btn--ghost" disabled={locked}
                    onClick={() => void mutate('delete', snapshot)}>{t('Snapshots.confirm_delete')}</button>
                  <button type="button" className="learn-dialog__btn learn-dialog__btn--ghost" disabled={locked}
                    onClick={() => setDeleteTarget(null)}>{t('LearnDialog.cancel')}</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
