import type { DoctorCheck } from '../api/config';
import type { TranslateFn } from '../i18n/useTranslation';

export function mapDoctorMessage(check: DoctorCheck, t: TranslateFn): string {
  switch (check.name) {
    case 'repo_root':
      return check.status === 'pass' ? t('Doctor.repo_root_pass') : t('Doctor.repo_root_fail');
    case 'sqlite_version':
      return t('Doctor.sqlite_version', { version: check.message.replace(/^SQLite\s*/i, '') });
    case 'config_valid':
      return check.status === 'pass'
        ? t('Doctor.config_valid_pass')
        : t('Doctor.config_valid_fail', { error: check.message.replace(/^Config error:\s*/i, '') });
    case 'review_db':
      return check.status === 'pass' ? t('Doctor.review_db_pass') : t('Doctor.review_db_warn');
    default:
      return check.message;
  }
}
