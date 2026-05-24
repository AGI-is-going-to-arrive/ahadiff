import { useState } from 'react';
import type { ToolUsageHint } from '../api/config';
import type { TranslateFn } from '../i18n/useTranslation';
import { detectPlatform } from '../utils/platform';
import { copyToClipboard } from '../utils/clipboard';
import './UsagePanel.css';

export default function UsagePanel({
  hint,
  t,
}: {
  hint: ToolUsageHint;
  t: TranslateFn;
}) {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const platform = detectPlatform();

  const handleCopy = async (text: string, index: number) => {
    const ok = await copyToClipboard(text);
    if (ok) {
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 1400);
    }
  };

  const platformNote = hint.platform_notes?.[platform];

  return (
    <div className="usage-panel">
      {hint.invocation_pattern && (
        <div className="usage-panel__section">
          <h4 className="usage-panel__heading">{t('Settings_page.integration_usage_invocation_pattern')}</h4>
          <div className="usage-panel__prompt">
            <code>{hint.invocation_pattern}</code>
            <button
              type="button"
              className="usage-panel__copy-btn"
              onClick={() => void handleCopy(hint.invocation_pattern!, 999)}
              aria-label={t('Skills.copy')}
            >
              {copiedIndex === 999 ? t('Skills.copied') : t('Skills.copy')}
            </button>
          </div>
        </div>
      )}

      {hint.quick_start_steps && hint.quick_start_steps.length > 0 && (
        <div className="usage-panel__section">
          <h4 className="usage-panel__heading">{t('Settings_page.integration_usage_quick_start')}</h4>
          <ol className="usage-panel__list">
            {hint.quick_start_steps.map((step, idx) => (
              <li key={idx}>{step}</li>
            ))}
          </ol>
        </div>
      )}

      {hint.example_prompts && hint.example_prompts.length > 0 && (
        <div className="usage-panel__section">
          <h4 className="usage-panel__heading">{t('Settings_page.integration_usage_examples')}</h4>
          <div className="usage-panel__prompts">
            {hint.example_prompts.map((prompt, idx) => (
              <div key={idx} className="usage-panel__prompt">
                <code>{prompt}</code>
                <button
                  type="button"
                  className="usage-panel__copy-btn"
                  onClick={() => void handleCopy(prompt, idx)}
                  aria-label={t('Skills.copy')}
                >
                  {copiedIndex === idx ? t('Skills.copied') : t('Skills.copy')}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {hint.expected_behavior && (
        <div className="usage-panel__section">
          <h4 className="usage-panel__heading">{t('Settings_page.integration_usage_expected')}</h4>
          <p className="usage-panel__text">{hint.expected_behavior}</p>
        </div>
      )}

      {platformNote && (
        <div className="usage-panel__section usage-panel__section--platform">
          <h4 className="usage-panel__heading">{t('Settings_page.integration_usage_platform_notes')}</h4>
          <p className="usage-panel__text">{platformNote}</p>
        </div>
      )}
    </div>
  );
}
