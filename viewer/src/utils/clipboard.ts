export async function copyToClipboard(text: string): Promise<boolean> {
  const clipboard: Clipboard | undefined =
    typeof navigator === 'undefined' ? undefined : navigator.clipboard;
  if (clipboard && typeof clipboard.writeText === 'function') {
    try {
      await clipboard.writeText(text);
      return true;
    } catch {
      // fall through to textarea fallback for restricted contexts
    }
  }

  if (typeof document === 'undefined' || !document.body) {
    return false;
  }

  let textarea: HTMLTextAreaElement | null = null;
  const activeElement = document.activeElement;
  try {
    textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.readOnly = true;
    textarea.tabIndex = -1;
    textarea.setAttribute('aria-hidden', 'true');
    textarea.style.position = 'fixed';
    textarea.style.top = '0';
    textarea.style.left = '0';
    textarea.style.width = '1px';
    textarea.style.height = '1px';
    textarea.style.padding = '0';
    textarea.style.border = 'none';
    textarea.style.opacity = '0';
    textarea.style.pointerEvents = 'none';
    document.body.appendChild(textarea);
    textarea.focus({ preventScroll: true });
    textarea.select();
    textarea.setSelectionRange(0, text.length);
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    textarea?.parentNode?.removeChild(textarea);
    try {
      const focusTarget = activeElement as { focus?: unknown; isConnected?: boolean } | null;
      if (
        focusTarget &&
        focusTarget.isConnected !== false &&
        typeof focusTarget.focus === 'function'
      ) {
        focusTarget.focus({ preventScroll: true });
      }
    } catch {
      // Focus restoration is best-effort; copy result should not be masked.
    }
  }
}
