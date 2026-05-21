import { EventEmitter } from 'node:events';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
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

function pluginName(plugin: unknown): string {
  if (!plugin || typeof plugin !== 'object' || !('name' in plugin)) return '';
  const name = (plugin as { name?: unknown }).name;
  return typeof name === 'string' ? name : '';
}

function getApiProxy(): ApiProxyOptions {
  const userConfig = config as UserConfig;
  const proxyConfig = userConfig.server?.proxy;
  if (!proxyConfig || Array.isArray(proxyConfig)) {
    throw new Error('missing /api proxy config');
  }
  return proxyConfig['/api'] as ApiProxyOptions;
}

describe('vite dev API proxy', () => {
  it('registers the PWA plugin for service-worker builds', () => {
    const userConfig = config as UserConfig;
    const plugins = Array.isArray(userConfig.plugins) ? userConfig.plugins : [userConfig.plugins];
    const names = plugins
      .flat()
      .filter(Boolean)
      .map(pluginName);

    expect(names).toContain('vite-plugin-pwa');
  });

  it('keeps the service worker on the immediate activation path', () => {
    const configSource = readFileSync(resolve(__dirname, '../../vite.config.ts'), 'utf8');
    const registerSource = readFileSync(resolve(__dirname, '../../public/registerSW.js'), 'utf8');

    expect(configSource).toContain("registerType: 'autoUpdate'");
    expect(configSource).toContain("injectRegister: 'script-defer'");
    expect(configSource).toContain('skipWaiting: true');
    expect(configSource).toContain('clientsClaim: true');
    expect(registerSource).toContain('controllerchange');
    expect(registerSource).toContain('SKIP_WAITING');
  });

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
