import { describe, expect, it } from 'vitest';
import type { InstallManifestAction } from '../api/config';
import type { TranslateFn } from '../i18n/useTranslation';
import { actionLabel, strategyLabel } from './integrationLabels';

const messages: Record<string, string> = {
  'Settings_page.integration_action_merge_section': 'merge marked section',
  'Settings_page.integration_action_remove_file': 'remove generated file',
  'Settings_page.integration_action_remove_section': 'remove marked section',
  'Settings_page.integration_action_unknown': 'file change',
  'Settings_page.integration_action_write_file': 'write generated file',
  'Settings_page.integration_strategy_generated': 'generated file',
  'Settings_page.integration_strategy_user_managed': 'existing file section',
};

const t: TranslateFn = (key) => messages[key] ?? key;

function action(
  rawAction: string,
  fileStrategy: InstallManifestAction['file_strategy'] = 'generated',
): InstallManifestAction {
  return { action: rawAction, file_strategy: fileStrategy, path: 'example.md' };
}

describe('integration label helpers', () => {
  it('localizes install manifest actions including unknown future actions', () => {
    expect(actionLabel(action('merge-section', 'user-managed'), t)).toBe('merge marked section');
    expect(actionLabel(action('append-section', 'user-managed'), t)).toBe('merge marked section');
    expect(actionLabel(action('remove-section', 'user-managed'), t)).toBe('remove marked section');
    expect(actionLabel(action('write'), t)).toBe('write generated file');
    expect(actionLabel(action('remove'), t)).toBe('remove generated file');
    expect(actionLabel(action('future-action'), t)).toBe('file change');
  });

  it('localizes generated and user-managed file strategies', () => {
    expect(strategyLabel(action('write'), t)).toBe('generated file');
    expect(strategyLabel(action('merge-section', 'user-managed'), t)).toBe(
      'existing file section',
    );
  });
});
