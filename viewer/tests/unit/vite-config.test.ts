import { EventEmitter } from 'node:events';
import { describe, expect, it, vi } from 'vitest';
import type { UserConfig } from 'vite';

import config from '../../vite.config';

type ProxyReq = {
  setHeader: (name: string, value: string) => void;
};

type ProxyEvents = EventEmitter & {
  emit: (event: 'proxyReq', proxyReq: ProxyReq, req: { headers: Record<string, string> }) => boolean;
};

type ApiProxyOptions = {
  target?: string;
  changeOrigin?: boolean;
  secure?: boolean;
  configure?: (proxy: ProxyEvents) => void;
};

function getApiProxy(): ApiProxyOptions {
  const userConfig = config as UserConfig;
  const proxyConfig = userConfig.server?.proxy;
  if (!proxyConfig || Array.isArray(proxyConfig)) {
    throw new Error('missing /api proxy config');
  }
  return proxyConfig['/api'] as ApiProxyOptions;
}

describe('vite dev API proxy', () => {
  it('preserves production same-origin paths while targeting the loopback backend in dev', () => {
    const apiProxy = getApiProxy();

    expect(apiProxy.target).toBe('http://127.0.0.1:8765');
    expect(apiProxy.changeOrigin).toBe(true);
    expect(apiProxy.secure).toBe(false);
  });

  it('rewrites Host, Origin, and Referer for the backend loopback guard', () => {
    const apiProxy = getApiProxy();
    const proxy = new EventEmitter() as ProxyEvents;
    const setHeader = vi.fn();

    apiProxy.configure?.(proxy);
    proxy.emit('proxyReq', { setHeader }, { headers: {} });

    expect(setHeader).toHaveBeenCalledWith('Host', '127.0.0.1:8765');
    expect(setHeader).toHaveBeenCalledWith('Origin', 'http://127.0.0.1:8765');
    expect(setHeader).toHaveBeenCalledWith('Referer', 'http://127.0.0.1:8765');
  });
});
