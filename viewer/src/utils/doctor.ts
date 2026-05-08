import type { DoctorCheck } from '../api/config';
import type { TranslateFn } from '../i18n/useTranslation';

function extractVersion(msg: string): string {
  return msg.replace(/^.*?(\d[\d.]+).*$/, '$1');
}

export function mapDoctorMessage(check: DoctorCheck, t: TranslateFn): string {
  const pass = check.status === 'pass';
  switch (check.name) {
    case 'repo_root':
      return pass ? t('Doctor.repo_root_pass') : t('Doctor.repo_root_fail');
    case 'state_dir_path':
      return pass ? t('Doctor.state_dir_pass') : t('Doctor.state_dir_fail');
    case 'sqlite_version':
      return t('Doctor.sqlite_version', { version: check.message.replace(/^SQLite\s*/i, '') });
    case 'sqlite_runtime_gate':
      return pass
        ? t('Doctor.sqlite_runtime_pass', { version: extractVersion(check.message) })
        : t('Doctor.sqlite_runtime_fail', { version: extractVersion(check.message) });
    case 'config_valid':
      return pass
        ? t('Doctor.config_valid_pass')
        : t('Doctor.config_valid_fail', { error: check.message.replace(/^Config error:\s*/i, '') });
    case 'config_unknown_keys':
      return pass ? t('Doctor.config_unknown_pass') : t('Doctor.config_unknown_warn');
    case 'config_sensitive_keys':
      return pass ? t('Doctor.config_sensitive_pass') : t('Doctor.config_sensitive_warn');
    case 'config_precedence_conflicts':
      return pass ? t('Doctor.config_precedence_pass') : t('Doctor.config_precedence_warn');
    case 'review_db':
      return pass ? t('Doctor.review_db_pass') : t('Doctor.review_db_warn');
    case 'review_db_quick_check':
      return pass ? t('Doctor.review_db_quick_check_pass')
        : check.status === 'fail' ? t('Doctor.review_db_quick_check_fail')
        : t('Doctor.review_db_quick_check_warn');
    case 'usage_db':
      return pass ? t('Doctor.usage_db_pass') : t('Doctor.usage_db_warn');
    case 'audit_file':
      return pass ? t('Doctor.audit_file_pass') : t('Doctor.audit_file_warn');
    default:
      return t('Doctor.unknown_check', { name: check.name });
  }
}
