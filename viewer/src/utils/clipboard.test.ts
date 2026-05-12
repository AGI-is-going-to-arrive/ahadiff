import { describe, it, expect, vi, afterEach } from 'vitest';

const makeClipboardModule = async () => {
  vi.resetModules();
  return import('./clipboard');
};

describe('copyToClipboard', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('returns true when navigator.clipboard.writeText succeeds', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });

    const { copyToClipboard } = await makeClipboardModule();
    const result = await copyToClipboard('hello');

    expect(result).toBe(true);
    expect(writeText).toHaveBeenCalledWith('hello');
  });

  it('falls back to execCommand when writeText rejects', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'));
    vi.stubGlobal('navigator', { clipboard: { writeText } });

    const textarea = {
      value: '',
      readOnly: false,
      tabIndex: 0,
      setAttribute: vi.fn(),
      style: {} as Record<string, string>,
      focus: vi.fn(),
      select: vi.fn(),
      setSelectionRange: vi.fn(),
      parentNode: { removeChild: vi.fn() },
    };
    const createElement = vi.fn().mockReturnValue(textarea);
    const appendChild = vi.fn();
    vi.stubGlobal('document', {
      createElement,
      body: { appendChild },
      execCommand: vi.fn().mockReturnValue(true),
    });

    const { copyToClipboard } = await makeClipboardModule();
    const result = await copyToClipboard('fallback');

    expect(result).toBe(true);
    expect(createElement).toHaveBeenCalledWith('textarea');
    expect(textarea.value).toBe('fallback');
    expect(textarea.parentNode.removeChild).toHaveBeenCalledWith(textarea);
  });

  it('falls back to execCommand when clipboard is undefined', async () => {
    vi.stubGlobal('navigator', { clipboard: undefined });

    const textarea = {
      value: '',
      readOnly: false,
      tabIndex: 0,
      setAttribute: vi.fn(),
      style: {} as Record<string, string>,
      focus: vi.fn(),
      select: vi.fn(),
      setSelectionRange: vi.fn(),
      parentNode: { removeChild: vi.fn() },
    };
    vi.stubGlobal('document', {
      createElement: vi.fn().mockReturnValue(textarea),
      body: { appendChild: vi.fn() },
      execCommand: vi.fn().mockReturnValue(true),
    });

    const { copyToClipboard } = await makeClipboardModule();
    const result = await copyToClipboard('no api');

    expect(result).toBe(true);
  });

  it('returns false when execCommand returns false', async () => {
    vi.stubGlobal('navigator', { clipboard: undefined });

    const textarea = {
      value: '',
      readOnly: false,
      tabIndex: 0,
      setAttribute: vi.fn(),
      style: {} as Record<string, string>,
      focus: vi.fn(),
      select: vi.fn(),
      setSelectionRange: vi.fn(),
      parentNode: { removeChild: vi.fn() },
    };
    vi.stubGlobal('document', {
      createElement: vi.fn().mockReturnValue(textarea),
      body: { appendChild: vi.fn() },
      execCommand: vi.fn().mockReturnValue(false),
    });

    const { copyToClipboard } = await makeClipboardModule();
    const result = await copyToClipboard('fail');

    expect(result).toBe(false);
  });

  it('restores focus after textarea fallback copy', async () => {
    vi.stubGlobal('navigator', { clipboard: undefined });

    const activeElement = {
      isConnected: true,
      focus: vi.fn(),
    };
    const textarea = {
      value: '',
      readOnly: false,
      tabIndex: 0,
      setAttribute: vi.fn(),
      style: {} as Record<string, string>,
      focus: vi.fn(),
      select: vi.fn(),
      setSelectionRange: vi.fn(),
      parentNode: { removeChild: vi.fn() },
    };
    vi.stubGlobal('document', {
      activeElement,
      createElement: vi.fn().mockReturnValue(textarea),
      body: { appendChild: vi.fn() },
      execCommand: vi.fn().mockReturnValue(true),
    });

    const { copyToClipboard } = await makeClipboardModule();
    const result = await copyToClipboard('restore focus');

    expect(result).toBe(true);
    expect(activeElement.focus).toHaveBeenCalledWith({ preventScroll: true });
  });

  it('returns false when document is undefined (SSR)', async () => {
    vi.stubGlobal('navigator', { clipboard: undefined });
    vi.stubGlobal('document', undefined);

    const { copyToClipboard } = await makeClipboardModule();
    const result = await copyToClipboard('ssr');

    expect(result).toBe(false);
  });

  it('returns false when navigator and document are both unavailable', async () => {
    vi.stubGlobal('navigator', undefined);
    vi.stubGlobal('document', undefined);

    const { copyToClipboard } = await makeClipboardModule();
    const result = await copyToClipboard('ssr');

    expect(result).toBe(false);
  });

  it('cleans up textarea when execCommand throws', async () => {
    vi.stubGlobal('navigator', { clipboard: undefined });

    const removeChild = vi.fn();
    const textarea = {
      value: '',
      readOnly: false,
      tabIndex: 0,
      setAttribute: vi.fn(),
      style: {} as Record<string, string>,
      focus: vi.fn(),
      select: vi.fn(),
      setSelectionRange: vi.fn(),
      parentNode: { removeChild },
    };
    vi.stubGlobal('document', {
      createElement: vi.fn().mockReturnValue(textarea),
      body: { appendChild: vi.fn() },
      execCommand: vi.fn().mockImplementation(() => {
        throw new Error('exec failed');
      }),
    });

    const { copyToClipboard } = await makeClipboardModule();
    const result = await copyToClipboard('cleanup');

    expect(result).toBe(false);
    expect(removeChild).toHaveBeenCalledWith(textarea);
  });
});
