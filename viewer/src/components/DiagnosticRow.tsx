import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import './DiagnosticRow.css';

export type DiagnosticStatus = 'pass' | 'warn' | 'fail' | 'info' | 'pending';

export interface DiagnosticRowProps {
  status: DiagnosticStatus;
  text: string;
  details?: string | null;
  iconAriaLabel?: string;
  /** Optional right-side status badge text, such as "PASS" / "WARN" / "FAIL". */
  statusLabel?: string;
  'data-testid'?: string;
}

const STATUS_LABEL_KEYS: Record<DiagnosticStatus, MessageKey> = {
  pass: 'Onboarding.doctor_pass_label',
  warn: 'Onboarding.doctor_warn_label',
  fail: 'Onboarding.doctor_fail_label',
  info: 'Onboarding.doctor_info_label',
  pending: 'Onboarding.doctor_info_label',
};

function StatusIcon({ status }: { status: DiagnosticStatus }) {
  switch (status) {
    case 'pass':
      return <CheckCircle2 size={14} aria-hidden="true" />;
    case 'warn':
      return <AlertTriangle size={14} aria-hidden="true" />;
    case 'fail':
      return <XCircle size={14} aria-hidden="true" />;
    case 'info':
      return <Info size={14} aria-hidden="true" />;
    case 'pending':
      return <span className="diag-row__icon-skeleton" aria-hidden="true" />;
  }
}

export function DiagnosticRow({
  status,
  text,
  details,
  iconAriaLabel,
  statusLabel,
  'data-testid': dataTestId,
}: DiagnosticRowProps) {
  const { t } = useTranslation();
  const resolvedAriaLabel = iconAriaLabel ?? t(STATUS_LABEL_KEYS[status]);
  const liveProps =
    status === 'fail' || status === 'warn'
      ? ({ role: 'status', 'aria-live': 'polite' } as const)
      : {};

  return (
    <div
      className="diag-row"
      data-status={status}
      data-testid={dataTestId ?? 'onboarding-diag-row'}
      {...liveProps}
    >
      <span
        className={`diag-row__icon diag-row__icon--${status}`}
        aria-hidden="true"
      >
        <StatusIcon status={status} />
      </span>
      <div className="diag-row__body">
        <span className="sr-only">{resolvedAriaLabel}: </span>
        <span className="diag-row__text">{text}</span>
        {details ? <span className="diag-row__details">{details}</span> : null}
      </div>
      {statusLabel && (
        <span
          className={`diag-row__status-badge diag-row__status-badge--${status}`}
          data-status={status}
          aria-hidden="true"
        >
          {statusLabel}
        </span>
      )}
    </div>
  );
}

export default DiagnosticRow;
