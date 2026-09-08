import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from '../i18n/useTranslation';
import { useLearnStore } from '../state/learn-store';
import { useLocaleStore } from '../state/locale-store';
import { estimateLearn } from '../api/tasks';
import { ApiError } from '../api/client';
import type { LearnEstimateResponse, LearnFileInput, LearnSubmitPayload, Locale, SnapshotSummary } from '../api/types';
import { getErrorMessage } from '../utils/error-codes';
import { buildFormatTexts, formatBytes } from '../utils/format';
import LearnSourcePicker, { type LearnSource } from './LearnSourcePicker';
import LearnFilePicker from './LearnFilePicker';
import LearnSnapshotPicker from './LearnSnapshotPicker';
import './LearnModeDialog.css';

type CaptureMode =
  | 'working'
  | 'unstaged'
  | 'staged'
  | 'last'
  | 'since'
  | 'revision'
  | 'patch_url'
  | 'compare'
  | 'compare_files'
  | 'snapshot'
  | 'document'
  | 'compare_dir'
  | 'patch';

type LangOption = 'auto' | Locale;
type PrivacyOption = '' | 'strict_local' | 'redacted_remote' | 'explicit_remote';

interface LearnModeDialogProps {
  open: boolean;
  onClose: () => void;
  initialSource?: LearnSource;
}

const QUICK_MODES: CaptureMode[] = ['working', 'unstaged', 'staged', 'last'];
const MAX_TEXT_INPUT_LENGTH = 4096;
const MAX_REVISION_LENGTH = 255;
const MAX_PATCH_TEXT_BYTES = 64 * 1024;
const MAX_REQUEST_BYTES = 1024 * 1024;
const MAX_CHANGED_PATHS = 500;
const MAX_PATH_SCOPE_TEXT_LENGTH = 64 * 1024;
const UTF8_ENCODER = new TextEncoder();
const CONTROL_CHAR_RE = /[\u0000-\u001f\u007f]/;
const WINDOWS_DRIVE_PATH_RE = /^[A-Za-z]:/;
const REVISION_INPUT_RE = /^[A-Za-z0-9._/@:+~^{}-]+$/;
const INTERNAL_PATH_ROOTS = new Set(['.git', '.ahadiff']);
const useSafeLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect;

type PathScopeError = 'invalid' | 'too_many' | null;

interface ChangedPathsParseResult {
  paths: string[];
  error: PathScopeError;
}

interface BuildPayloadArgs {
  mode: CaptureMode;
  since: string;
  author: string;
  revision: string;
  patchUrl: string;
  patchText: string;
  compareA: string;
  compareB: string;
  compareFiles: [LearnFileInput, LearnFileInput] | null;
  document: LearnFileInput | null;
  snapshot: SnapshotSummary | null;
  snapshotAfter: LearnFileInput | null;
  reviewContext: string;
  compareDirA: string;
  compareDirB: string;
  changedPaths: string[];
  forceLearn: boolean;
  activePractice: boolean;
  useGraphify: boolean;
  dryRun: boolean;
  lang: LangOption;
  privacyMode: PrivacyOption;
}

function buildPayload(args: BuildPayloadArgs): LearnSubmitPayload {
  const {
    mode,
    since,
    author,
    revision,
    patchUrl,
    patchText,
    compareA,
    compareB,
    compareFiles,
    document: documentInput,
    snapshot,
    snapshotAfter,
    reviewContext,
    compareDirA,
    compareDirB,
    changedPaths,
    forceLearn,
    activePractice,
    useGraphify,
    dryRun,
    lang,
    privacyMode,
  } = args;
  const base: LearnSubmitPayload = {};
  switch (mode) {
    case 'working':
      base.staged = true;
      base.unstaged = true;
      base.include_untracked = true;
      break;
    case 'unstaged':
      base.unstaged = true;
      base.include_untracked = true;
      break;
    case 'staged':
      base.staged = true;
      break;
    case 'last':
      base.last = true;
      break;
    case 'since':
      base.since = since.trim();
      if (author.trim().length > 0) base.author = author.trim();
      break;
    case 'revision':
      base.revision = revision.trim();
      break;
    case 'patch_url':
      base.patch_url = patchUrl.trim();
      break;
    case 'patch':
      base.patch = patchText;
      break;
    case 'compare':
      base.compare = [compareA.trim(), compareB.trim()];
      break;
    case 'compare_files':
      if (compareFiles) base.compare_files = compareFiles;
      break;
    case 'document':
      if (documentInput) base.document = documentInput;
      break;
    case 'snapshot':
      if (snapshot?.content_hash && snapshotAfter) {
        base.snapshot_id = snapshot.snapshot_id;
        base.snapshot_hash = snapshot.content_hash;
        base.snapshot_after = snapshotAfter;
      }
      break;
    case 'compare_dir':
      base.compare_dir = [compareDirA.trim(), compareDirB.trim()];
      break;
    default: {
      const exhaustive: never = mode;
      throw new Error(`Unhandled learn capture mode: ${String(exhaustive)}`);
    }
  }
  if (mode !== 'document' && reviewContext.trim()) base.review_context = reviewContext;
  if (forceLearn) base.force_learn = true;
  if (activePractice) base.active_practice = true;
  if (useGraphify) base.use_graphify = true;
  if (dryRun) base.dry_run = true;
  base.lang = lang;
  if (privacyMode !== '') base.privacy_mode = privacyMode;
  if (isPathScopeMode(mode) && changedPaths.length > 0) base.changed_paths = changedPaths;
  return base;
}

function isAdvancedMode(mode: CaptureMode): boolean {
  return (
    mode === 'since' ||
    mode === 'revision' ||
    mode === 'patch_url' ||
    mode === 'compare' ||
    mode === 'compare_dir'
  );
}

function isPathScopeMode(mode: CaptureMode): boolean {
  return mode === 'working' || mode === 'unstaged' || mode === 'staged';
}

function parseChangedPaths(value: string): ChangedPathsParseResult {
  const paths: string[] = [];
  for (const line of value.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed.length === 0) continue;
    if (CONTROL_CHAR_RE.test(trimmed)) return { paths, error: 'invalid' };

    let normalized = trimmed.replace(/\\/g, '/').replace(/\/+/g, '/');
    if (normalized.startsWith('/') || normalized.startsWith('//') || WINDOWS_DRIVE_PATH_RE.test(normalized)) {
      return { paths, error: 'invalid' };
    }
    while (normalized.startsWith('./')) normalized = normalized.slice(2);
    const parts = normalized.split('/');
    if (
      normalized.length === 0 ||
      normalized.startsWith(':') ||
      parts.some((part) => part === '' || part === '.' || part === '..') ||
      INTERNAL_PATH_ROOTS.has(parts[0] ?? '')
    ) {
      return { paths, error: 'invalid' };
    }
    paths.push(normalized);
  }
  const uniquePaths = Array.from(new Set(paths));
  return {
    paths: uniquePaths,
    error: uniquePaths.length > MAX_CHANGED_PATHS ? 'too_many' : null,
  };
}

function utf8ByteLength(value: string): number {
  return UTF8_ENCODER.encode(value).length;
}

function patchUrlIsValid(value: string): boolean {
  try {
    const url = new URL(value);
    return (url.protocol === 'http:' || url.protocol === 'https:') && !url.username && !url.password;
  } catch {
    return false;
  }
}

function revisionIsValid(value: string): boolean {
  if (value.length > MAX_REVISION_LENGTH) return false;
  if (value.startsWith('-')) return false;
  if (CONTROL_CHAR_RE.test(value)) return false;
  return REVISION_INPUT_RE.test(value);
}

function gitFilterIsValid(value: string): boolean {
  if (value.length > MAX_TEXT_INPUT_LENGTH) return false;
  if (value.startsWith('-')) return false;
  return !CONTROL_CHAR_RE.test(value);
}

function sourceForMode(mode: CaptureMode): LearnSource {
  if (mode === 'snapshot' || mode === 'document') return mode;
  if (mode === 'compare' || mode === 'compare_dir' || mode === 'compare_files') return 'files';
  if (mode === 'patch' || mode === 'patch_url') return 'patch';
  return 'git';
}

function defaultMode(source: LearnSource): CaptureMode {
  if (source === 'snapshot' || source === 'document') return source;
  return source === 'files' ? 'compare_files' : source === 'patch' ? 'patch' : 'working';
}

export default function LearnModeDialog({ open, onClose, initialSource = 'git' }: LearnModeDialogProps) {
  const { t, locale } = useTranslation();
  const requestLearn = useLearnStore((s) => s.requestLearn);
  const learnPhase = useLearnStore((s) => s.phase);
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFocusRef = useRef<HTMLInputElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const estimateAbortRef = useRef<AbortController | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);

  const [mode, setMode] = useState<CaptureMode>('working');
  const [since, setSince] = useState('');
  const [author, setAuthor] = useState('');
  const [revision, setRevision] = useState('');
  const [patchUrl, setPatchUrl] = useState('');
  const [patchText, setPatchText] = useState('');
  const [compareA, setCompareA] = useState('');
  const [compareB, setCompareB] = useState('');
  const [beforeFile, setBeforeFile] = useState<LearnFileInput | null>(null);
  const [afterFile, setAfterFile] = useState<LearnFileInput | null>(null);
  const [documentFile, setDocumentFile] = useState<LearnFileInput | null>(null);
  const [snapshot, setSnapshot] = useState<SnapshotSummary | null>(null);
  const [snapshotPending, setSnapshotPending] = useState(false);
  const [reviewContext, setReviewContext] = useState('');
  const [readingBefore, setReadingBefore] = useState(false);
  const [readingAfter, setReadingAfter] = useState(false);
  const [compareDirA, setCompareDirA] = useState('');
  const [compareDirB, setCompareDirB] = useState('');
  const [pathScope, setPathScope] = useState('');
  const [forceLearn, setForceLearn] = useState(false);
  const [activePractice, setActivePractice] = useState(false);
  const [useGraphify, setUseGraphify] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const viewerLocale = useLocaleStore((s) => s.locale);
  const viewerLocaleRef = useRef(viewerLocale);
  viewerLocaleRef.current = viewerLocale;
  const [lang, setLang] = useState<LangOption>(viewerLocale);
  const [privacyMode, setPrivacyMode] = useState<PrivacyOption>('');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [preview, setPreview] = useState<LearnEstimateResponse | null>(null);
  const [previewKey, setPreviewKey] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewErrorCode, setPreviewErrorCode] = useState<string | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);
  const source = sourceForMode(mode);

  const isTaskBusy = learnPhase === 'submitting' || learnPhase === 'running' || learnPhase === 'cancelling' || learnPhase === 'estimating' || learnPhase === 'confirming';
  const isBusy = isTaskBusy || previewLoading || readingBefore || readingAfter || snapshotPending;
  const reviewContextInvalid = source !== 'document' && (utf8ByteLength(reviewContext) > 8192 || reviewContext.includes('\0'));
  const patchTextBytes = useMemo(() => utf8ByteLength(patchText), [patchText]);
  const patchTooLarge = patchTextBytes > MAX_PATCH_TEXT_BYTES;
  const patchUsesStdinSentinel = patchText.trim() === '-';
  const patchBlocksSubmit = mode === 'patch' && (patchTooLarge || patchUsesStdinSentinel);
  const patchErrorId = patchBlocksSubmit ? 'learn-mode-patch-error' : undefined;
  const patchValidationMessage = patchTooLarge
    ? t('LearnDialog.error_patch_too_large', { max: MAX_PATCH_TEXT_BYTES })
    : patchUsesStdinSentinel
      ? t('LearnDialog.error_patch_stdin_unsupported')
    : null;
  const pathScopeDisabled = !isPathScopeMode(mode);
  const pathScopeResult = useMemo(() => parseChangedPaths(pathScope), [pathScope]);
  const activePathScopeError = pathScopeDisabled ? null : pathScopeResult.error;
  const pathScopeInvalid = activePathScopeError !== null;
  const pathScopeErrorId = pathScopeInvalid ? 'learn-mode-path-scope-error' : undefined;
  const pathScopeDescriptionId = 'learn-mode-path-scope-hint';
  const pathScopeDescribedBy = pathScopeErrorId
    ? `${pathScopeDescriptionId} ${pathScopeErrorId}`
    : pathScopeDescriptionId;
  const pathScopeValidationMessage =
    activePathScopeError === 'too_many'
      ? t('LearnDialog.error_path_scope_too_many', { max: MAX_CHANGED_PATHS })
      : activePathScopeError === 'invalid'
        ? t('LearnDialog.error_path_scope_invalid')
        : null;
  const trimmedRevision = revision.trim();
  const revisionInvalid = mode === 'revision' && trimmedRevision.length > 0 && !revisionIsValid(trimmedRevision);
  const revisionErrorId = revisionInvalid ? 'learn-mode-revision-error' : undefined;
  const revisionValidationMessage = revisionInvalid ? t('LearnDialog.error_revision_invalid') : null;
  const trimmedSince = since.trim();
  const sinceInvalid = mode === 'since' && trimmedSince.length > 0 && !gitFilterIsValid(trimmedSince);
  const sinceErrorId = sinceInvalid ? 'learn-mode-since-error' : undefined;
  const sinceValidationMessage = sinceInvalid ? t('LearnDialog.error_since_invalid') : null;
  const trimmedAuthor = author.trim();
  const authorInvalid = mode === 'since' && trimmedAuthor.length > 0 && !gitFilterIsValid(trimmedAuthor);
  const authorErrorId = authorInvalid ? 'learn-mode-author-error' : undefined;
  const authorValidationMessage = authorInvalid ? t('LearnDialog.error_author_invalid') : null;
  const trimmedPatchUrl = patchUrl.trim();
  const patchUrlInvalid = mode === 'patch_url' && trimmedPatchUrl.length > 0 && !patchUrlIsValid(trimmedPatchUrl);
  const patchUrlErrorId = patchUrlInvalid ? 'learn-mode-patch-url-error' : undefined;
  const patchUrlValidationMessage = patchUrlInvalid ? t('LearnDialog.error_patch_url_invalid') : null;

  const abortEstimate = useCallback(() => {
    estimateAbortRef.current?.abort();
    estimateAbortRef.current = null;
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
  }, []);

  const clearSensitiveFields = useCallback(() => {
    setPatchText('');
    setPatchUrl('');
    setBeforeFile(null);
    setAfterFile(null);
    setDocumentFile(null);
    setSnapshot(null);
    setReviewContext('');
    setSnapshotPending(false);
    setActivePractice(false);
  }, []);

  const handleClose = useCallback(() => {
    abortEstimate();
    clearSensitiveFields();
    onClose();
  }, [abortEstimate, clearSensitiveFields, onClose]);

  let needsValidInput = false;
  switch (mode) {
    case 'since':
      needsValidInput = trimmedSince.length > 0 && !sinceInvalid && !authorInvalid;
      break;
    case 'revision':
      needsValidInput = trimmedRevision.length > 0 && !revisionInvalid;
      break;
    case 'patch_url':
      needsValidInput = trimmedPatchUrl.length > 0 && !patchUrlInvalid;
      break;
    case 'patch':
      needsValidInput = patchText.trim().length > 0 && !patchBlocksSubmit;
      break;
    case 'compare':
      needsValidInput = compareA.trim().length > 0 && compareB.trim().length > 0;
      break;
    case 'document':
      needsValidInput = documentFile !== null && documentFile.content.trim().length > 0;
      break;
    case 'snapshot':
      needsValidInput = snapshot?.status === 'ready' && Boolean(snapshot.content_hash) && afterFile !== null;
      break;
    case 'compare_files':
      needsValidInput = beforeFile !== null && afterFile !== null;
      break;
    case 'compare_dir':
      needsValidInput = compareDirA.trim().length > 0 && compareDirB.trim().length > 0;
      break;
    default:
      needsValidInput = true;
      break;
  }
  const payload = useMemo(() => buildPayload({
    mode, since, author, revision, patchUrl, patchText, compareA, compareB,
    compareFiles: beforeFile && afterFile ? [beforeFile, afterFile] : null,
    document: documentFile, snapshot, snapshotAfter: afterFile, reviewContext,
    compareDirA, compareDirB, changedPaths: pathScopeResult.paths,
    forceLearn, activePractice, useGraphify, dryRun, lang, privacyMode,
  }), [mode, since, author, revision, patchUrl, patchText, compareA, compareB,
    beforeFile, afterFile, documentFile, snapshot, reviewContext, compareDirA, compareDirB, pathScopeResult.paths,
    forceLearn, activePractice, useGraphify, dryRun, lang, privacyMode]);
  const payloadKey = JSON.stringify(payload);
  const requestTooLarge = utf8ByteLength(payloadKey) > MAX_REQUEST_BYTES;
  const canPreview = !isBusy && needsValidInput && !pathScopeInvalid && !reviewContextInvalid && !requestTooLarge;
  const hasCurrentPreview = preview !== null && previewKey === payloadKey;
  const canSubmit = canPreview && hasCurrentPreview && preview.file_count > 0 && Boolean((source === 'document' ? preview.preview_document : preview.preview_patch)?.trim());

  useEffect(() => {
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
    setPreview(null);
    setPreviewKey('');
    setPreviewLoading(false);
    setPreviewFailed(false);
    setPreviewErrorCode(null);
  }, [payloadKey]);

  useSafeLayoutEffect(() => {
    if (!open || typeof document === 'undefined') return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  // Preserve any pre-existing inert state while this portal dialog is open.
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
    for (const { el } of previous) {
      el.setAttribute('inert', '');
    }
    return () => {
      for (const { el, hadInert, inertValue } of previous) {
        if (hadInert) el.setAttribute('inert', inertValue ?? '');
        else el.removeAttribute('inert');
      }
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      abortEstimate();
      clearSensitiveFields();
      setPreview(null);
      setPreviewKey('');
      setPreviewLoading(false);
      setPreviewFailed(false);
      setPreviewErrorCode(null);
    }
    return undefined;
  }, [abortEstimate, clearSensitiveFields, open]);

  useEffect(() => () => abortEstimate(), [abortEstimate]);

  useEffect(() => {
    if (open) {
      restoreFocusRef.current = document.activeElement as HTMLElement | null;
      setMode(defaultMode(initialSource));
      setSince('');
      setAuthor('');
      setRevision('');
      setPatchUrl('');
      setPatchText('');
      setCompareA('');
      setCompareB('');
      setBeforeFile(null);
      setAfterFile(null);
      setDocumentFile(null);
      setSnapshot(null);
      setReviewContext('');
      setSnapshotPending(false);
      setReadingBefore(false);
      setReadingAfter(false);
      setCompareDirA('');
      setCompareDirB('');
      setPathScope('');
      setForceLearn(initialSource !== 'git');
      setActivePractice(false);
      setUseGraphify(false);
      setDryRun(false);
      setLang(viewerLocaleRef.current);
      setPrivacyMode('');
      setAdvancedOpen(false);
      const raf = requestAnimationFrame(() => {
        const sourceButton = dialogRef.current?.querySelector<HTMLButtonElement>(
          '[data-learn-source][aria-pressed="true"]',
        );
        (sourceButton ?? firstFocusRef.current)?.focus();
      });
      return () => {
        cancelAnimationFrame(raf);
        restoreFocusRef.current?.focus({ preventScroll: true });
        restoreFocusRef.current = null;
      };
    }
    return undefined;
  }, [open, initialSource]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        handleClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handleClose, open]);

  // Focus trap
  useEffect(() => {
    if (!open || !dialogRef.current) return undefined;
    const dialog = dialogRef.current;
    const onFocusTrap = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const focusable = dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
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

  const handleModeSelect = useCallback((m: CaptureMode) => {
    setMode(m);
    if (m !== 'compare_files') {
      setReadingBefore(false);
      setReadingAfter(false);
    }
    if (isAdvancedMode(m) && !advancedOpen) setAdvancedOpen(true);
  }, [advancedOpen]);

  const handleSourceSelect = (next: LearnSource): void => {
    if (next !== source) {
      abortEstimate();
      setActivePractice(false);
      setDocumentFile(null);
      setSnapshot(null);
      setReviewContext('');
      setSnapshotPending(false);
      setBeforeFile(null);
      setAfterFile(null);
      setPatchText('');
      setPatchUrl('');
      setReadingBefore(false);
      setReadingAfter(false);
    }
    setMode(defaultMode(next));
    setForceLearn(next !== 'git');
    setAdvancedOpen(false);
  };

  const handlePreview = async (): Promise<void> => {
    if (!canPreview) return;
    const controller = new AbortController();
    previewAbortRef.current?.abort();
    previewAbortRef.current = controller;
    setPreviewLoading(true);
    setPreview(null);
    setPreviewFailed(false);
    setPreviewErrorCode(null);
    try {
      const result = await estimateLearn(payload, { signal: controller.signal });
      if (controller.signal.aborted || previewAbortRef.current !== controller) return;
      if ((source === 'document') !== (result.source_kind === 'document')) throw new Error('Preview source mismatch');
      if (typeof (source === 'document' ? result.preview_document : result.preview_patch) !== 'string') throw new Error('Preview unavailable');
      setPreview(result);
      setPreviewKey(payloadKey);
    } catch (error: unknown) {
      if (controller.signal.aborted || previewAbortRef.current !== controller) return;
      setPreviewFailed(true);
      setPreviewErrorCode(error instanceof ApiError ? error.errorCode ?? null : null);
    } finally {
      if (previewAbortRef.current === controller) {
        previewAbortRef.current = null;
        setPreviewLoading(false);
      }
    }
  };

  const handleSubmit = useCallback(() => {
    if (!canSubmit) return;
    const controller = new AbortController();
    estimateAbortRef.current?.abort();
    estimateAbortRef.current = controller;
    void requestLearn(payload, { signal: controller.signal }).finally(() => {
      if (estimateAbortRef.current === controller) estimateAbortRef.current = null;
      if (controller.signal.aborted) return;
      clearSensitiveFields();
      onClose();
    });
  }, [
    canSubmit,
    payload,
    requestLearn,
    clearSensitiveFields,
    onClose,
  ]);

  if (!open) return null;

  return createPortal(
    <div ref={overlayRef} className="learn-dialog__overlay" onClick={handleClose}>
      <div
        ref={dialogRef}
        className="learn-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="learn-dialog-title"
        aria-describedby="learn-dialog-subtitle"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="learn-dialog__header">
          <h2 id="learn-dialog-title" className="learn-dialog__title">
            {t('LearnDialog.title')}
          </h2>
          <p id="learn-dialog-subtitle" className="learn-dialog__subtitle">{t('LearnDialog.subtitle')}</p>
          <kbd className="learn-dialog__esc">{t('LearnDialog.kbd_esc_close')}</kbd>
        </header>

        <div className="learn-dialog__body">
          <LearnSourcePicker selected={source} onSelect={handleSourceSelect} disabled={isTaskBusy} />
          <fieldset className="learn-dialog__fieldset" disabled={isTaskBusy}>
            <legend className="learn-dialog__sr-only">{t('LearnDialog.subtitle')}</legend>
            {source === 'git' && (
            <div className="learn-dialog__tiles">
              {QUICK_MODES.map((m) => (
                <label
                  key={m}
                  className={`learn-dialog__tile${mode === m ? ' learn-dialog__tile--selected' : ''}`}
                >
                  <input
                    ref={m === 'working' ? firstFocusRef : undefined}
                    type="radio"
                    name="capture-mode"
                    checked={mode === m}
                    onChange={() => handleModeSelect(m)}
                    className="learn-dialog__tile-radio"
                  />
                  <span className="learn-dialog__tile-label">
                    {t(`LearnDialog.mode_${m}` as `LearnDialog.mode_working`)}
                  </span>
                  <span className="learn-dialog__tile-cmd" aria-hidden="true">
                    {t(`LearnDialog.mode_${m}_cmd` as `LearnDialog.mode_working_cmd`)}
                  </span>
                  <span className="learn-dialog__tile-desc">
                    {t(`LearnDialog.mode_${m}_desc` as `LearnDialog.mode_working_desc`)}
                  </span>
                </label>
              ))}
            </div>

            )}
            {mode === 'document' && (
              <>
                <p className="learn-dialog__preview-hint">{t('LearnDialog.document_scope')}</p>
                <LearnFilePicker side="document" value={documentFile} disabled={isTaskBusy} onChange={setDocumentFile} onPendingChange={setReadingBefore} />
              </>
            )}
            {mode === 'snapshot' && (
              <>
                <LearnSnapshotPicker value={snapshot} disabled={isTaskBusy} onChange={setSnapshot} onPendingChange={setSnapshotPending} />
                <LearnFilePicker side="after" value={afterFile} disabled={isTaskBusy} onChange={setAfterFile} onPendingChange={setReadingAfter} />
              </>
            )}
            {mode === 'compare_files' && (
              <div className="learn-dialog__file-pair">
                <LearnFilePicker side="before" value={beforeFile} disabled={isTaskBusy} onChange={setBeforeFile} onPendingChange={setReadingBefore} />
                <LearnFilePicker side="after" value={afterFile} disabled={isTaskBusy} onChange={setAfterFile} onPendingChange={setReadingAfter} />
              </div>
            )}
                {/* Inline inputs for Patch (paste) */}
                {mode === 'patch' && (
                  <div className="learn-dialog__input-area">
                    <div className="learn-dialog__radio-row learn-dialog__radio-row--block">
                      <label
                        id="learn-mode-patch-label"
                        htmlFor="learn-mode-patch-text"
                        className="learn-dialog__radio-label"
                      >
                        <span className="learn-dialog__radio-label-main">{t('LearnDialog.mode_patch')}</span>
                        <span className="learn-dialog__radio-hint">{t('LearnDialog.mode_patch_hint')}</span>
                      </label>
                      <textarea
                        id="learn-mode-patch-text"
                        className="learn-dialog__textarea"
                        aria-labelledby="learn-mode-patch-label"
                        aria-describedby={patchErrorId}
                        aria-invalid={patchTooLarge || undefined}
                        placeholder={t('LearnDialog.mode_patch_ph')}
                        value={patchText}
                        maxLength={MAX_PATCH_TEXT_BYTES * 4}
                        onFocus={() => handleModeSelect('patch')}
                        onChange={(e) => {
                          handleModeSelect('patch');
                          setPatchText(e.target.value);
                        }}
                        rows={6}
                      />
                      {patchValidationMessage && (
                        <p
                          id="learn-mode-patch-error"
                          className="learn-dialog__error"
                          role="status"
                          aria-live="polite"
                        >
                          {patchValidationMessage}
                        </p>
                      )}
                    </div>
                  </div>
                )}
            {source !== 'document' && (
              <div className="learn-dialog__review-context">
                <label htmlFor="learn-review-context">{t('LearnDialog.review_context')}</label>
                <p id="learn-review-context-hint" className="learn-dialog__file-hint">{t('LearnDialog.review_context_hint')}</p>
                <textarea id="learn-review-context" className="learn-dialog__textarea" value={reviewContext}
                  onChange={(event) => setReviewContext(event.target.value)} rows={3} maxLength={8192}
                  aria-describedby="learn-review-context-hint" aria-invalid={reviewContextInvalid || undefined} />
                {reviewContextInvalid && <p className="learn-dialog__error" role="status">{t('LearnDialog.review_context_error')}</p>}
              </div>
            )}
            {source !== 'git' && (
              <div className="learn-dialog__explicit-learn">
                <label className="learn-dialog__checkbox">
                  <input
                    type="checkbox"
                    checked={forceLearn}
                    onChange={(e) => setForceLearn(e.target.checked)}
                  />
                  <span className="learn-dialog__checkbox-copy">
                    <span className="learn-dialog__checkbox-label">{t('LearnDialog.opt_force')}</span>
                    <span className="learn-dialog__checkbox-hint">
                      {t('LearnDialog.opt_force_hint')}
                    </span>
                  </span>
                </label>

              </div>
            )}
            <button
              type="button"
              className="learn-dialog__advanced-toggle"
              aria-expanded={advancedOpen}
              aria-controls="learn-dialog-advanced"
              onClick={() => setAdvancedOpen((value) => !value)}
            >
              <span className="learn-dialog__advanced-arrow" aria-hidden="true">{advancedOpen ? '▾' : '▸'}</span>
              {advancedOpen ? t('LearnDialog.advanced_toggle_open') : t('LearnDialog.advanced_toggle_closed')}
            </button>
            {advancedOpen && (
              <div id="learn-dialog-advanced" className="learn-dialog__advanced">
                {source === 'git' && (<>
              <div className="learn-dialog__path-scope-row">
                <div className="learn-dialog__path-scope-copy">
                  <label htmlFor="learn-mode-path-scope" className="learn-dialog__path-scope-label">
                    {t('LearnDialog.path_scope')}
                  </label>
                  <p id={pathScopeDescriptionId} className="learn-dialog__path-scope-hint">
                    {t('LearnDialog.path_scope_hint')}
                  </p>
                </div>
                <textarea
                  id="learn-mode-path-scope"
                  className="learn-dialog__path-scope-input"
                  aria-describedby={pathScopeDescribedBy}
                  aria-invalid={pathScopeInvalid || undefined}
                  placeholder={t('LearnDialog.path_scope_ph')}
                  disabled={pathScopeDisabled}
                  value={pathScope}
                  onChange={(e) => setPathScope(e.target.value)}
                  maxLength={MAX_PATH_SCOPE_TEXT_LENGTH}
                  rows={3}
                />
                {pathScopeValidationMessage && (
                  <p
                    id="learn-mode-path-scope-error"
                    className="learn-dialog__error"
                    role="status"
                    aria-live="polite"
                  >
                    {pathScopeValidationMessage}
                  </p>
                )}
              </div>

              {/* ============== Git Advanced group ============== */}
              <div className="learn-dialog__adv-group" role="group" aria-labelledby="learn-adv-group-git">
                <div id="learn-adv-group-git" className="learn-dialog__adv-group-title">
                  <span>{t('LearnDialog.adv_group_git')}</span>
                  <span className="learn-dialog__adv-group-meta">{t('LearnDialog.adv_group_git_meta')}</span>
                </div>
                <div className="learn-dialog__adv-grid">
                  {/* Since card */}
                  <label
                    className={`learn-dialog__adv-card${mode === 'since' ? ' learn-dialog__adv-card--selected' : ''}`}
                  >
                    <input
                      id="learn-mode-since"
                      type="radio"
                      name="capture-mode"
                      checked={mode === 'since'}
                      onChange={() => handleModeSelect('since')}
                      className="learn-dialog__tile-radio"
                    />
                    <div className="learn-dialog__adv-card-head">
                      <span className="learn-dialog__adv-card-title">{t('LearnDialog.mode_since')}</span>
                      <span className="learn-dialog__adv-card-badge learn-dialog__adv-card-badge--window">
                        {t('LearnDialog.badge_window')}
                      </span>
                    </div>
                    <div className="learn-dialog__adv-example" aria-hidden="true">
                      <span className="learn-dialog__cmd-prefix" aria-hidden="true">$</span>
                      {' ahadiff learn '}
                      <span className="learn-dialog__cmd-flag">--since</span>
                      {' '}
                      <span className="learn-dialog__cmd-arg">&quot;2h ago&quot;</span>
                    </div>
                    <div className="learn-dialog__adv-desc">{t('LearnDialog.adv_since_desc')}</div>
                  </label>

                  {/* Revision card */}
                  <label
                    className={`learn-dialog__adv-card${mode === 'revision' ? ' learn-dialog__adv-card--selected' : ''}`}
                  >
                    <input
                      id="learn-mode-revision"
                      type="radio"
                      name="capture-mode"
                      checked={mode === 'revision'}
                      onChange={() => handleModeSelect('revision')}
                      className="learn-dialog__tile-radio"
                    />
                    <div className="learn-dialog__adv-card-head">
                      <span className="learn-dialog__adv-card-title">{t('LearnDialog.mode_revision')}</span>
                    </div>
                    <div className="learn-dialog__adv-example" aria-hidden="true">
                      <span className="learn-dialog__cmd-prefix" aria-hidden="true">$</span>
                      {' ahadiff learn '}
                      <span className="learn-dialog__cmd-arg">HEAD~5..HEAD</span>
                    </div>
                    <div className="learn-dialog__adv-desc">{t('LearnDialog.adv_revision_desc')}</div>
                  </label>
                </div>

                {/* Inline inputs for Since */}
                {mode === 'since' && (
                  <div className="learn-dialog__input-area">
                    <div className="learn-dialog__radio-row">
                      <label
                        id="learn-mode-since-label"
                        htmlFor="learn-mode-since-value"
                        className="learn-dialog__radio-label"
                      >
                        <span className="learn-dialog__radio-label-main">{t('LearnDialog.mode_since')}</span>
                        <span className="learn-dialog__radio-hint">{t('LearnDialog.mode_since_hint')}</span>
                      </label>
                      <input
                        id="learn-mode-since-value"
                        type="text"
                        className="learn-dialog__input"
                        aria-labelledby="learn-mode-since-label"
                        aria-describedby={sinceErrorId}
                        aria-invalid={sinceInvalid || undefined}
                        placeholder={t('LearnDialog.mode_since_ph')}
                        maxLength={MAX_TEXT_INPUT_LENGTH}
                        value={since}
                        onFocus={() => handleModeSelect('since')}
                        onChange={(e) => {
                          handleModeSelect('since');
                          setSince(e.target.value);
                        }}
                      />
                      {sinceValidationMessage && (
                        <p
                          id="learn-mode-since-error"
                          className="learn-dialog__error"
                          role="status"
                          aria-live="polite"
                        >
                          {sinceValidationMessage}
                        </p>
                      )}
                    </div>
                    <div className="learn-dialog__author-row">
                      <label htmlFor="learn-mode-author" className="learn-dialog__author-label">
                        {t('LearnDialog.author_filter')}
                      </label>
                      <input
                        id="learn-mode-author"
                        type="text"
                        className="learn-dialog__input"
                        placeholder={t('LearnDialog.author_filter_ph')}
                        aria-describedby={authorErrorId}
                        aria-invalid={authorInvalid || undefined}
                        maxLength={MAX_TEXT_INPUT_LENGTH}
                        value={author}
                        onFocus={() => handleModeSelect('since')}
                        onChange={(e) => {
                          handleModeSelect('since');
                          setAuthor(e.target.value);
                        }}
                      />
                      {authorValidationMessage && (
                        <p
                          id="learn-mode-author-error"
                          className="learn-dialog__error"
                          role="status"
                          aria-live="polite"
                        >
                          {authorValidationMessage}
                        </p>
                      )}
                    </div>
                  </div>
                )}

                {/* Inline inputs for Revision */}
                {mode === 'revision' && (
                  <div className="learn-dialog__input-area">
                    <div className="learn-dialog__radio-row">
                      <label
                        id="learn-mode-revision-label"
                        htmlFor="learn-mode-revision-value"
                        className="learn-dialog__radio-label"
                      >
                        <span className="learn-dialog__radio-label-main">{t('LearnDialog.mode_revision')}</span>
                        <span className="learn-dialog__radio-hint">{t('LearnDialog.mode_revision_hint')}</span>
                      </label>
                      <input
                        id="learn-mode-revision-value"
                        type="text"
                        className="learn-dialog__input"
                        aria-labelledby="learn-mode-revision-label"
                        aria-describedby={revisionErrorId}
                        aria-invalid={revisionInvalid || undefined}
                        placeholder={t('LearnDialog.mode_revision_ph')}
                        maxLength={MAX_REVISION_LENGTH}
                        value={revision}
                        onFocus={() => handleModeSelect('revision')}
                        onChange={(e) => {
                          handleModeSelect('revision');
                          setRevision(e.target.value);
                        }}
                      />
                      {revisionValidationMessage && (
                        <p
                          id="learn-mode-revision-error"
                          className="learn-dialog__error"
                          role="status"
                          aria-live="polite"
                        >
                          {revisionValidationMessage}
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>


                </>)}
                {source === 'patch' && (<>
              {/* ============== Patch group ============== */}
              <div className="learn-dialog__adv-group" role="group" aria-labelledby="learn-adv-group-patch">
                <div id="learn-adv-group-patch" className="learn-dialog__adv-group-title">
                  <span>{t('LearnDialog.adv_group_patch')}</span>
                  <span className="learn-dialog__adv-group-meta">{t('LearnDialog.adv_group_patch_meta')}</span>
                </div>
                <div className="learn-dialog__adv-grid">
                  {/* Patch URL card */}
                  <label
                    className={`learn-dialog__adv-card${mode === 'patch_url' ? ' learn-dialog__adv-card--selected' : ''}`}
                  >
                    <input
                      id="learn-mode-patch-url"
                      type="radio"
                      name="capture-mode"
                      checked={mode === 'patch_url'}
                      onChange={() => handleModeSelect('patch_url')}
                      className="learn-dialog__tile-radio"
                    />
                    <div className="learn-dialog__adv-card-head">
                      <span className="learn-dialog__adv-card-title">{t('LearnDialog.mode_patch_url')}</span>
                    </div>
                    <div className="learn-dialog__adv-example" aria-hidden="true">
                      <span className="learn-dialog__cmd-prefix" aria-hidden="true">$</span>
                      {' ahadiff learn '}
                      <span className="learn-dialog__cmd-flag">--patch-url</span>
                      {' '}
                      <span className="learn-dialog__cmd-arg">https://...</span>
                    </div>
                    <div className="learn-dialog__adv-desc">{t('LearnDialog.adv_patch_url_desc')}</div>
                  </label>

                  {/* Patch (paste) card */}
                  <label
                    className={`learn-dialog__adv-card${mode === 'patch' ? ' learn-dialog__adv-card--selected' : ''}`}
                  >
                    <input
                      id="learn-mode-patch"
                      type="radio"
                      name="capture-mode"
                      checked={mode === 'patch'}
                      onChange={() => handleModeSelect('patch')}
                      className="learn-dialog__tile-radio"
                    />
                    <div className="learn-dialog__adv-card-head">
                      <span className="learn-dialog__adv-card-title">{t('LearnDialog.mode_patch')}</span>
                    </div>
                    <div className="learn-dialog__adv-example" aria-hidden="true">
                      <span className="learn-dialog__cmd-prefix" aria-hidden="true">$</span>
                      {' ahadiff learn '}
                      <span className="learn-dialog__cmd-flag">--patch</span>
                      {' '}
                      <span className="learn-dialog__cmd-arg">-</span>
                    </div>
                    <div className="learn-dialog__adv-desc">{t('LearnDialog.adv_patch_desc')}</div>
                  </label>
                </div>

                {/* Inline inputs for Patch URL */}
                {mode === 'patch_url' && (
                  <div className="learn-dialog__input-area">
                    <div className="learn-dialog__radio-row">
                      <label
                        id="learn-mode-patch-url-label"
                        htmlFor="learn-mode-patch-url-value"
                        className="learn-dialog__radio-label"
                      >
                        <span className="learn-dialog__radio-label-main">{t('LearnDialog.mode_patch_url')}</span>
                        <span className="learn-dialog__radio-hint">{t('LearnDialog.mode_patch_url_hint')}</span>
                      </label>
                      <input
                        id="learn-mode-patch-url-value"
                        type="text"
                        className="learn-dialog__input"
                        aria-labelledby="learn-mode-patch-url-label"
                        aria-describedby={patchUrlErrorId}
                        aria-invalid={patchUrlInvalid || undefined}
                        placeholder={t('LearnDialog.mode_patch_url_ph')}
                        maxLength={MAX_TEXT_INPUT_LENGTH}
                        value={patchUrl}
                        onFocus={() => handleModeSelect('patch_url')}
                        onChange={(e) => {
                          handleModeSelect('patch_url');
                          setPatchUrl(e.target.value);
                        }}
                      />
                      {patchUrlValidationMessage && (
                        <p
                          id="learn-mode-patch-url-error"
                          className="learn-dialog__error"
                          role="status"
                          aria-live="polite"
                        >
                          {patchUrlValidationMessage}
                        </p>
                      )}
                    </div>
                  </div>
                )}


              </div>


                </>)}
                {source === 'files' && (<>
              {/* ============== Compare group ============== */}
              <div className="learn-dialog__adv-group" role="group" aria-labelledby="learn-adv-group-compare">
                <div id="learn-adv-group-compare" className="learn-dialog__adv-group-title">
                  <span>{t('LearnDialog.adv_group_compare')}</span>
                  <span className="learn-dialog__adv-group-meta">{t('LearnDialog.adv_group_compare_meta')}</span>
                </div>
                <div className="learn-dialog__adv-grid">
                  <label className={`learn-dialog__adv-card${mode === 'compare_files' ? ' learn-dialog__adv-card--selected' : ''}`}>
                    <input type="radio" name="capture-mode" checked={mode === 'compare_files'} onChange={() => handleModeSelect('compare_files')} className="learn-dialog__tile-radio" />
                    <span className="learn-dialog__adv-card-title">{t('LearnDialog.source_files')}</span>
                    <span className="learn-dialog__adv-desc">{t('LearnDialog.source_files_hint')}</span>
                  </label>
                  {/* Compare files card */}
                  <label
                    className={`learn-dialog__adv-card${mode === 'compare' ? ' learn-dialog__adv-card--selected' : ''}`}
                  >
                    <input
                      id="learn-mode-compare"
                      type="radio"
                      name="capture-mode"
                      checked={mode === 'compare'}
                      onChange={() => handleModeSelect('compare')}
                      className="learn-dialog__tile-radio"
                    />
                    <div className="learn-dialog__adv-card-head">
                      <span className="learn-dialog__adv-card-title">{t('LearnDialog.mode_compare')}</span>
                    </div>
                    <div className="learn-dialog__adv-example" aria-hidden="true">
                      <span className="learn-dialog__cmd-prefix" aria-hidden="true">$</span>
                      {' ahadiff learn '}
                      <span className="learn-dialog__cmd-flag">--compare</span>
                      {' '}
                      <span className="learn-dialog__cmd-arg">old.py new.py</span>
                    </div>
                    <div className="learn-dialog__adv-desc">{t('LearnDialog.adv_compare_desc')}</div>
                  </label>

                  {/* Compare dirs card */}
                  <label
                    className={`learn-dialog__adv-card${mode === 'compare_dir' ? ' learn-dialog__adv-card--selected' : ''}`}
                  >
                    <input
                      id="learn-mode-compare-dir"
                      type="radio"
                      name="capture-mode"
                      checked={mode === 'compare_dir'}
                      onChange={() => handleModeSelect('compare_dir')}
                      className="learn-dialog__tile-radio"
                    />
                    <div className="learn-dialog__adv-card-head">
                      <span className="learn-dialog__adv-card-title">{t('LearnDialog.mode_compare_dir')}</span>
                    </div>
                    <div className="learn-dialog__adv-example" aria-hidden="true">
                      <span className="learn-dialog__cmd-prefix" aria-hidden="true">$</span>
                      {' ahadiff learn '}
                      <span className="learn-dialog__cmd-flag">--compare-dir</span>
                      {' '}
                      <span className="learn-dialog__cmd-arg">old/ new/</span>
                    </div>
                    <div className="learn-dialog__adv-desc">{t('LearnDialog.adv_compare_dir_desc')}</div>
                  </label>
                </div>

                {/* Inline inputs for Compare files */}
                {mode === 'compare' && (
                  <div className="learn-dialog__input-area">
                    <div className="learn-dialog__radio-row">
                      <label htmlFor="learn-mode-compare-a" className="learn-dialog__radio-label">
                        <span className="learn-dialog__radio-label-main">{t('LearnDialog.mode_compare')}</span>
                        <span className="learn-dialog__radio-hint">{t('LearnDialog.mode_compare_hint')}</span>
                      </label>
                      <div className="learn-dialog__dual-input">
                        <input
                          id="learn-mode-compare-a"
                          type="text"
                          className="learn-dialog__input"
                          aria-label={t('LearnDialog.mode_compare_a_aria')}
                          placeholder={t('LearnDialog.mode_compare_a_ph')}
                          maxLength={MAX_TEXT_INPUT_LENGTH}
                          value={compareA}
                          onFocus={() => handleModeSelect('compare')}
                          onChange={(e) => {
                            handleModeSelect('compare');
                            setCompareA(e.target.value);
                          }}
                        />
                        <input
                          id="learn-mode-compare-b"
                          type="text"
                          className="learn-dialog__input"
                          aria-label={t('LearnDialog.mode_compare_b_aria')}
                          placeholder={t('LearnDialog.mode_compare_b_ph')}
                          maxLength={MAX_TEXT_INPUT_LENGTH}
                          value={compareB}
                          onFocus={() => handleModeSelect('compare')}
                          onChange={(e) => {
                            handleModeSelect('compare');
                            setCompareB(e.target.value);
                          }}
                        />
                      </div>
                    </div>
                  </div>
                )}

                {/* Inline inputs for Compare dirs */}
                {mode === 'compare_dir' && (
                  <div className="learn-dialog__input-area">
                    <div className="learn-dialog__radio-row">
                      <label htmlFor="learn-mode-compare-dir-a" className="learn-dialog__radio-label">
                        <span className="learn-dialog__radio-label-main">{t('LearnDialog.mode_compare_dir')}</span>
                        <span className="learn-dialog__radio-hint">{t('LearnDialog.mode_compare_dir_hint')}</span>
                      </label>
                      <div className="learn-dialog__dual-input">
                        <input
                          id="learn-mode-compare-dir-a"
                          type="text"
                          className="learn-dialog__input"
                          aria-label={t('LearnDialog.mode_compare_dir_a_aria')}
                          placeholder={t('LearnDialog.mode_compare_dir_a_ph')}
                          maxLength={MAX_TEXT_INPUT_LENGTH}
                          value={compareDirA}
                          onFocus={() => handleModeSelect('compare_dir')}
                          onChange={(e) => {
                            handleModeSelect('compare_dir');
                            setCompareDirA(e.target.value);
                          }}
                        />
                        <input
                          id="learn-mode-compare-dir-b"
                          type="text"
                          className="learn-dialog__input"
                          aria-label={t('LearnDialog.mode_compare_dir_b_aria')}
                          placeholder={t('LearnDialog.mode_compare_dir_b_ph')}
                          maxLength={MAX_TEXT_INPUT_LENGTH}
                          value={compareDirB}
                          onFocus={() => handleModeSelect('compare_dir')}
                          onChange={(e) => {
                            handleModeSelect('compare_dir');
                            setCompareDirB(e.target.value);
                          }}
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>


                </>)}
              {/* Options */}
              <div className="learn-dialog__options">
                <div className="learn-dialog__options-title">{t('LearnDialog.options_title')}</div>
{source === 'git' && (
                <label className="learn-dialog__checkbox">
                  <input
                    type="checkbox"
                    checked={forceLearn}
                    onChange={(e) => setForceLearn(e.target.checked)}
                  />
                  <span className="learn-dialog__checkbox-copy">
                    <span className="learn-dialog__checkbox-label">{t('LearnDialog.opt_force')}</span>
                    <span className="learn-dialog__checkbox-hint">
                      {t('LearnDialog.opt_force_hint')}
                    </span>
                  </span>
                </label>
)}
                <label className="learn-dialog__checkbox">
                  <input
                    type="checkbox"
                    checked={useGraphify}
                    onChange={(e) => setUseGraphify(e.target.checked)}
                  />
                  <span className="learn-dialog__checkbox-copy">
                    <span className="learn-dialog__checkbox-label">
                      {t('LearnDialog.opt_graphify')}
                    </span>
                    <span className="learn-dialog__checkbox-hint">
                      {t('LearnDialog.opt_graphify_hint')}
                    </span>
                  </span>
                </label>
                <label className="learn-dialog__checkbox">
                  <input
                    type="checkbox"
                    checked={dryRun}
                    onChange={(e) => setDryRun(e.target.checked)}
                  />
                  <span className="learn-dialog__checkbox-copy">
                    <span className="learn-dialog__checkbox-label">
                      {t('LearnDialog.opt_dry_run')}
                    </span>
                    <span className="learn-dialog__checkbox-hint">
                      {t('LearnDialog.opt_dry_run_hint')}
                    </span>
                  </span>
                </label>
                <label className="learn-dialog__checkbox">
                  <input
                    id="learn-opt-active-practice"
                    type="checkbox"
                    checked={activePractice}
                    aria-label={t('LearnDialog.opt_active_practice')}
                    aria-describedby="learn-opt-active-practice-hint"
                    onChange={(event) => setActivePractice(event.target.checked)}
                  />
                  <span className="learn-dialog__checkbox-copy">
                    <span className="learn-dialog__checkbox-label">{t('LearnDialog.opt_active_practice')}</span>
                    <span id="learn-opt-active-practice-hint" className="learn-dialog__checkbox-hint">
                      {t('LearnDialog.opt_active_practice_hint')}
                    </span>
                  </span>
                </label>
                <div className="learn-dialog__select-row">
                  <label htmlFor="learn-opt-lang" className="learn-dialog__select-label">
                    {t('LearnDialog.opt_lang')}
                  </label>
                  <select
                    id="learn-opt-lang"
                    className="learn-dialog__select"
                    value={lang}
                    onChange={(e) => setLang(e.target.value as LangOption)}
                  >
                    <option value="auto">{t('LearnDialog.opt_lang_auto')}</option>
                    <option value="en">{t('LearnDialog.opt_lang_en')}</option>
                    <option value="zh-CN">{t('LearnDialog.opt_lang_zh_cn')}</option>
                  </select>
                </div>
                <div className="learn-dialog__select-row">
                  <label htmlFor="learn-opt-privacy" className="learn-dialog__select-label">
                    {t('LearnDialog.opt_privacy')}
                  </label>
                  <select
                    id="learn-opt-privacy"
                    className="learn-dialog__select"
                    value={privacyMode}
                    onChange={(e) => setPrivacyMode(e.target.value as PrivacyOption)}
                  >
                    <option value="">{t('LearnDialog.opt_privacy_default')}</option>
                    <option value="strict_local">{t('LearnDialog.opt_privacy_strict_local')}</option>
                    <option value="redacted_remote">{t('LearnDialog.opt_privacy_redacted_remote')}</option>
                    <option value="explicit_remote">{t('LearnDialog.opt_privacy_explicit_remote')}</option>
                  </select>
                </div>
              </div>
              </div>
            )}
          </fieldset>
          <p className="learn-dialog__preview-hint">{t('LearnDialog.preview_hint')}</p>
          {requestTooLarge && <p className="learn-dialog__error" role="alert">{t('LearnDialog.error_request_too_large')}</p>}
          {previewFailed && (
            <p className="learn-dialog__error" role="alert">
              {getErrorMessage(t, previewErrorCode, t('LearnDialog.preview_failed'))}
              {' '}{t('LearnDialog.preview_retry_hint')}
            </p>
          )}
          {previewLoading && <p role="status" aria-live="polite">{t('LearnDialog.preview_loading')}</p>}
          {hasCurrentPreview && preview && (
            <section className="learn-dialog__preview" aria-labelledby="learn-preview-title">
              <h3 id="learn-preview-title">{t(source === 'document' ? 'LearnDialog.document_preview' : 'LearnDialog.preview_title')}</h3>
              <p className="learn-dialog__preview-stats" role="status">
                {t('Learn.preflight_files', { count: preview.file_count })}
                {' · '}{formatBytes(preview.source_bytes ?? preview.patch_bytes, locale, buildFormatTexts(t))}
              </p>
              {preview.preview_truncated && <p>{t('LearnDialog.preview_truncated')}</p>}
              {(preview.diff_clipped || (preview.omitted_files_count ?? 0) > 0) && <p className="learn-dialog__error">{t('LearnDialog.preview_capture_clipped')}</p>}
              {preview.risk_level !== 'ok' && <p>{t('LearnDialog.preview_risk')}</p>}
              {preview.warnings.length > 0 && <ul className="learn-dialog__preview-warnings">
                {preview.warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}
              </ul>}
              {preview.review_context_used && <p role="note">{t('LearnDialog.review_context_used')}</p>}
              {(source === 'document' ? preview.preview_document : preview.preview_patch)?.trim()
                ? <pre className="learn-dialog__preview-diff" tabIndex={0} aria-label={t(source === 'document' ? 'LearnDialog.document_preview' : 'LearnDialog.preview_title')}>{source === 'document' ? preview.preview_document : preview.preview_patch}</pre>
                : <p>{t('LearnDialog.preview_empty')}</p>}
            </section>
          )}
        </div>

        <footer className="learn-dialog__footer">
          <button
            type="button"
            className="learn-dialog__btn learn-dialog__btn--ghost"
            onClick={handleClose}
          >
            {t('LearnDialog.cancel')}
          </button>
          <p className="learn-dialog__sr-only" role="status" aria-live="polite">
            {isBusy ? t('LearnDialog.status_busy') : canSubmit ? t('LearnDialog.status_ready') : t('LearnDialog.subtitle')}
          </p>
          <button
            type="button"
            className="learn-dialog__btn learn-dialog__btn--ghost learn-dialog__preview-button"
            disabled={!canPreview}
            aria-busy={previewLoading}
            onClick={() => void handlePreview()}
          >
            {t(hasCurrentPreview ? 'LearnDialog.preview_again' : 'LearnDialog.preview_action')}
          </button>
          <button
            type="button"
            className="learn-dialog__btn learn-dialog__btn--primary"
            disabled={!canSubmit}
            aria-busy={isBusy}
            aria-label={t('LearnDialog.start_aria')}
            onClick={handleSubmit}
          >
            {t('LearnDialog.start')}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
