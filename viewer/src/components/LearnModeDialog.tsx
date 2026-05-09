import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from '../i18n/useTranslation';
import { useLearnStore } from '../state/learn-store';
import type { LearnSubmitPayload, Locale } from '../api/types';
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
  | 'compare_dir'
  | 'patch';

type LangOption = 'auto' | Locale;
type PrivacyOption = '' | 'strict_local' | 'redacted_remote' | 'explicit_remote';

interface LearnModeDialogProps {
  open: boolean;
  onClose: () => void;
}

const QUICK_MODES: CaptureMode[] = ['working', 'unstaged', 'staged', 'last'];
const MAX_TEXT_INPUT_LENGTH = 4096;
const MAX_PATCH_TEXT_BYTES = 4096;
const MAX_CHANGED_PATHS = 500;
const MAX_PATH_SCOPE_TEXT_LENGTH = 64 * 1024;

interface BuildPayloadArgs {
  mode: CaptureMode;
  since: string;
  author: string;
  revision: string;
  patchUrl: string;
  patchText: string;
  compareA: string;
  compareB: string;
  compareDirA: string;
  compareDirB: string;
  pathScope: string;
  forceLearn: boolean;
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
    compareDirA,
    compareDirB,
    pathScope,
    forceLearn,
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
    case 'compare_dir':
      base.compare_dir = [compareDirA.trim(), compareDirB.trim()];
      break;
    default: {
      const exhaustive: never = mode;
      return exhaustive;
    }
  }
  if (forceLearn) base.force_learn = true;
  if (useGraphify) base.use_graphify = true;
  if (dryRun) base.dry_run = true;
  if (lang !== 'auto') base.lang = lang;
  if (privacyMode !== '') base.privacy_mode = privacyMode;
  if (isPathScopeMode(mode)) {
    const changedPaths = parseChangedPaths(pathScope);
    if (changedPaths.length > 0) base.changed_paths = changedPaths;
  }
  return base;
}

function isAdvancedMode(mode: CaptureMode): boolean {
  return (
    mode === 'since' ||
    mode === 'revision' ||
    mode === 'patch_url' ||
    mode === 'compare' ||
    mode === 'compare_dir' ||
    mode === 'patch'
  );
}

function isPathScopeMode(mode: CaptureMode): boolean {
  return mode === 'working' || mode === 'unstaged' || mode === 'staged';
}

function parseChangedPaths(value: string): string[] {
  const paths = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  return Array.from(new Set(paths));
}

function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).length;
}

export default function LearnModeDialog({ open, onClose }: LearnModeDialogProps) {
  const { t } = useTranslation();
  const requestLearn = useLearnStore((s) => s.requestLearn);
  const learnPhase = useLearnStore((s) => s.phase);
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFocusRef = useRef<HTMLInputElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  const [mode, setMode] = useState<CaptureMode>('working');
  const [since, setSince] = useState('');
  const [author, setAuthor] = useState('');
  const [revision, setRevision] = useState('');
  const [patchUrl, setPatchUrl] = useState('');
  const [patchText, setPatchText] = useState('');
  const [compareA, setCompareA] = useState('');
  const [compareB, setCompareB] = useState('');
  const [compareDirA, setCompareDirA] = useState('');
  const [compareDirB, setCompareDirB] = useState('');
  const [pathScope, setPathScope] = useState('');
  const [forceLearn, setForceLearn] = useState(false);
  const [useGraphify, setUseGraphify] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [lang, setLang] = useState<LangOption>('auto');
  const [privacyMode, setPrivacyMode] = useState<PrivacyOption>('');
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const isBusy = learnPhase === 'submitting' || learnPhase === 'running' || learnPhase === 'cancelling' || learnPhase === 'estimating' || learnPhase === 'confirming';
  const patchTextBytes = mode === 'patch' ? utf8ByteLength(patchText) : 0;
  const patchTooLarge = patchTextBytes > MAX_PATCH_TEXT_BYTES;
  const patchErrorId = patchTooLarge ? 'learn-mode-patch-error' : undefined;
  const patchValidationMessage = patchTooLarge
    ? t('LearnDialog.error_patch_too_large', { max: MAX_PATCH_TEXT_BYTES })
    : null;
  const pathScopeDisabled = !isPathScopeMode(mode);
  const pathScopePathCount = parseChangedPaths(pathScope).length;
  const pathScopeTooMany = !pathScopeDisabled && pathScopePathCount > MAX_CHANGED_PATHS;
  const pathScopeErrorId = pathScopeTooMany ? 'learn-mode-path-scope-error' : undefined;
  const pathScopeDescriptionId = 'learn-mode-path-scope-hint';
  const pathScopeDescribedBy = pathScopeErrorId
    ? `${pathScopeDescriptionId} ${pathScopeErrorId}`
    : pathScopeDescriptionId;
  const pathScopeValidationMessage = pathScopeTooMany
    ? t('LearnDialog.error_path_scope_too_many', { max: MAX_CHANGED_PATHS })
    : null;

  let needsValidInput = false;
  switch (mode) {
    case 'since':
      needsValidInput = since.trim().length > 0;
      break;
    case 'revision':
      needsValidInput = revision.trim().length > 0;
      break;
    case 'patch_url':
      needsValidInput = patchUrl.trim().length > 0;
      break;
    case 'patch':
      needsValidInput = patchText.trim().length > 0 && !patchTooLarge;
      break;
    case 'compare':
      needsValidInput = compareA.trim().length > 0 && compareB.trim().length > 0;
      break;
    case 'compare_dir':
      needsValidInput = compareDirA.trim().length > 0 && compareDirB.trim().length > 0;
      break;
    default:
      needsValidInput = true;
      break;
  }
  const canSubmit = !isBusy && needsValidInput && !pathScopeTooMany;

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
    if (open) {
      restoreFocusRef.current = document.activeElement as HTMLElement | null;
      setMode('working');
      setSince('');
      setAuthor('');
      setRevision('');
      setPatchUrl('');
      setPatchText('');
      setCompareA('');
      setCompareB('');
      setCompareDirA('');
      setCompareDirB('');
      setPathScope('');
      setForceLearn(false);
      setUseGraphify(false);
      setDryRun(false);
      setLang('auto');
      setPrivacyMode('');
      setAdvancedOpen(false);
      const raf = requestAnimationFrame(() => firstFocusRef.current?.focus());
      return () => {
        cancelAnimationFrame(raf);
        restoreFocusRef.current?.focus({ preventScroll: true });
        restoreFocusRef.current = null;
      };
    }
    return undefined;
  }, [open]);

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
    if (isAdvancedMode(m) && !advancedOpen) setAdvancedOpen(true);
  }, [advancedOpen]);

  const handleSubmit = useCallback(() => {
    if (!canSubmit) return;
    const payload = buildPayload({
      mode,
      since,
      author,
      revision,
      patchUrl,
      patchText,
      compareA,
      compareB,
      compareDirA,
      compareDirB,
      pathScope,
      forceLearn,
      useGraphify,
      dryRun,
      lang,
      privacyMode,
    });
    void requestLearn(payload);
    onClose();
  }, [
    canSubmit,
    mode,
    since,
    author,
    revision,
    patchUrl,
    patchText,
    compareA,
    compareB,
    compareDirA,
    compareDirB,
    pathScope,
    forceLearn,
    useGraphify,
    dryRun,
    lang,
    privacyMode,
    requestLearn,
    onClose,
  ]);

  if (!open) return null;

  return createPortal(
    <div ref={overlayRef} className="learn-dialog__overlay" onClick={onClose}>
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
          <fieldset className="learn-dialog__fieldset">
            <legend className="learn-dialog__legend">{t('LearnDialog.subtitle')}</legend>
            {/* Quick mode tiles */}
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
                  <span className="learn-dialog__tile-desc">
                    {t(`LearnDialog.mode_${m}_desc` as `LearnDialog.mode_working_desc`)}
                  </span>
                </label>
              ))}
            </div>

          {/* Advanced toggle */}
          <button
            type="button"
            className="learn-dialog__advanced-toggle"
            aria-expanded={advancedOpen}
            aria-controls="learn-dialog-advanced"
            onClick={() => setAdvancedOpen((v) => !v)}
          >
            <span className="learn-dialog__advanced-arrow" aria-hidden="true">
              {advancedOpen ? '▾' : '▸'}
            </span>
            {t('LearnDialog.advanced_toggle')}
          </button>

          {/* Advanced section */}
          {advancedOpen && (
            <div id="learn-dialog-advanced" className="learn-dialog__advanced">
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
                  aria-invalid={pathScopeTooMany || undefined}
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
                    role="alert"
                  >
                    {pathScopeValidationMessage}
                  </p>
                )}
              </div>

              <div className="learn-dialog__advanced-group-label">
                {t('LearnDialog.advanced_sources_title')}
              </div>

              {/* Since */}
              <div
                className="learn-dialog__radio-row"
                onClick={() => handleModeSelect('since')}
              >
                <input
                  id="learn-mode-since"
                  type="radio"
                  name="capture-mode"
                  checked={mode === 'since'}
                  onChange={() => handleModeSelect('since')}
                />
                <label id="learn-mode-since-label" htmlFor="learn-mode-since" className="learn-dialog__radio-label">
                  <span className="learn-dialog__radio-label-main">{t('LearnDialog.mode_since')}</span>
                  <span className="learn-dialog__radio-hint">{t('LearnDialog.mode_since_hint')}</span>
                </label>
                <input
                  id="learn-mode-since-value"
                  type="text"
                  className="learn-dialog__input"
                  aria-labelledby="learn-mode-since-label"
                  placeholder={t('LearnDialog.mode_since_ph')}
                  maxLength={MAX_TEXT_INPUT_LENGTH}
                  value={since}
                  onFocus={() => handleModeSelect('since')}
                  onChange={(e) => {
                    handleModeSelect('since');
                    setSince(e.target.value);
                  }}
                />
              </div>

              {/* Author filter (qualifier for since) */}
              <div className="learn-dialog__author-row" onClick={() => handleModeSelect('since')}>
                <label
                  htmlFor="learn-mode-author"
                  className="learn-dialog__author-label"
                >
                  {t('LearnDialog.author_filter')}
                </label>
                <input
                  id="learn-mode-author"
                  type="text"
                  className="learn-dialog__input"
                  placeholder={t('LearnDialog.author_filter_ph')}
                  maxLength={MAX_TEXT_INPUT_LENGTH}
                  value={author}
                  onFocus={() => handleModeSelect('since')}
                  onChange={(e) => {
                    handleModeSelect('since');
                    setAuthor(e.target.value);
                  }}
                />
              </div>

              {/* Revision */}
              <div
                className="learn-dialog__radio-row"
                onClick={() => handleModeSelect('revision')}
              >
                <input
                  id="learn-mode-revision"
                  type="radio"
                  name="capture-mode"
                  checked={mode === 'revision'}
                  onChange={() => handleModeSelect('revision')}
                />
                <label id="learn-mode-revision-label" htmlFor="learn-mode-revision" className="learn-dialog__radio-label">
                  <span className="learn-dialog__radio-label-main">{t('LearnDialog.mode_revision')}</span>
                  <span className="learn-dialog__radio-hint">{t('LearnDialog.mode_revision_hint')}</span>
                </label>
                <input
                  id="learn-mode-revision-value"
                  type="text"
                  className="learn-dialog__input"
                  aria-labelledby="learn-mode-revision-label"
                  placeholder={t('LearnDialog.mode_revision_ph')}
                  maxLength={MAX_TEXT_INPUT_LENGTH}
                  value={revision}
                  onFocus={() => handleModeSelect('revision')}
                  onChange={(e) => {
                    handleModeSelect('revision');
                    setRevision(e.target.value);
                  }}
                />
              </div>

              {/* Patch URL */}
              <div
                className="learn-dialog__radio-row"
                onClick={() => handleModeSelect('patch_url')}
              >
                <input
                  id="learn-mode-patch-url"
                  type="radio"
                  name="capture-mode"
                  checked={mode === 'patch_url'}
                  onChange={() => handleModeSelect('patch_url')}
                />
                <label id="learn-mode-patch-url-label" htmlFor="learn-mode-patch-url" className="learn-dialog__radio-label">
                  <span className="learn-dialog__radio-label-main">{t('LearnDialog.mode_patch_url')}</span>
                  <span className="learn-dialog__radio-hint">{t('LearnDialog.mode_patch_url_hint')}</span>
                </label>
                <input
                  id="learn-mode-patch-url-value"
                  type="text"
                  className="learn-dialog__input"
                  aria-labelledby="learn-mode-patch-url-label"
                  placeholder={t('LearnDialog.mode_patch_url_ph')}
                  maxLength={MAX_TEXT_INPUT_LENGTH}
                  value={patchUrl}
                  onFocus={() => handleModeSelect('patch_url')}
                  onChange={(e) => {
                    handleModeSelect('patch_url');
                    setPatchUrl(e.target.value);
                  }}
                />
              </div>

              {/* Compare refs */}
              <div
                className="learn-dialog__radio-row"
                onClick={() => handleModeSelect('compare')}
              >
                <input
                  id="learn-mode-compare"
                  type="radio"
                  name="capture-mode"
                  checked={mode === 'compare'}
                  onChange={() => handleModeSelect('compare')}
                />
                <label htmlFor="learn-mode-compare" className="learn-dialog__radio-label">
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

              {/* Compare dirs */}
              <div
                className="learn-dialog__radio-row"
                onClick={() => handleModeSelect('compare_dir')}
              >
                <input
                  id="learn-mode-compare-dir"
                  type="radio"
                  name="capture-mode"
                  checked={mode === 'compare_dir'}
                  onChange={() => handleModeSelect('compare_dir')}
                />
                <label htmlFor="learn-mode-compare-dir" className="learn-dialog__radio-label">
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

              {/* Paste patch */}
              <div
                className="learn-dialog__radio-row learn-dialog__radio-row--block"
                onClick={() => handleModeSelect('patch')}
              >
                <input
                  id="learn-mode-patch"
                  type="radio"
                  name="capture-mode"
                  checked={mode === 'patch'}
                  onChange={() => handleModeSelect('patch')}
                />
                <label id="learn-mode-patch-label" htmlFor="learn-mode-patch" className="learn-dialog__radio-label">
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
                    role="alert"
                  >
                    {patchValidationMessage}
                  </p>
                )}
              </div>

              {/* Options */}
              <div className="learn-dialog__options">
                <div className="learn-dialog__options-title">{t('LearnDialog.options_title')}</div>
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
        </div>

        <footer className="learn-dialog__footer">
          <button
            type="button"
            className="learn-dialog__btn learn-dialog__btn--ghost"
            onClick={onClose}
          >
            {t('LearnDialog.cancel')}
          </button>
          <button
            type="button"
            className="learn-dialog__btn learn-dialog__btn--primary"
            disabled={!canSubmit}
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
