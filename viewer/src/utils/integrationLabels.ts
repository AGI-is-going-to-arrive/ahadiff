import type { InstallManifestAction } from '../api/config';
import type { TranslateFn } from '../i18n/useTranslation';

/**
 * Map a raw `action` from `InstallManifestAction` to a localized label.
 * Falls back to a generic localized label when the action is unknown.
 */
export function actionLabel(action: InstallManifestAction, t: TranslateFn): string {
  switch (action.action) {
    case 'merge-section':
    case 'append-section':
      return t('Settings_page.integration_action_merge_section');
    case 'remove-section':
      return t('Settings_page.integration_action_remove_section');
    case 'write':
      return t('Settings_page.integration_action_write_file');
    case 'remove':
      return t('Settings_page.integration_action_remove_file');
    default:
      return t('Settings_page.integration_action_unknown');
  }
}

/**
 * Map a `file_strategy` to a localized label
 * ("generated" vs "user-managed").
 */
export function strategyLabel(action: InstallManifestAction, t: TranslateFn): string {
  return action.file_strategy === 'generated'
    ? t('Settings_page.integration_strategy_generated')
    : t('Settings_page.integration_strategy_user_managed');
}
