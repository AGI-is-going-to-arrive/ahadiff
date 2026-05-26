import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

type WebManifestIcon = {
  src?: string;
  sizes?: string;
  type?: string;
  purpose?: string;
};

type WebManifest = {
  background_color?: string;
  id?: string;
  start_url?: string;
  scope?: string;
  display?: string;
  theme_color?: string;
  icons?: WebManifestIcon[];
};

function readManifest(): WebManifest {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  const manifestPath = path.resolve(testDir, '../../public/manifest.json');
  return JSON.parse(readFileSync(manifestPath, 'utf8')) as WebManifest;
}

function publicPath(relativePath: string): string {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  return path.resolve(testDir, '../../public', relativePath);
}

describe('PWA manifest', () => {
  it('declares an installable same-origin app shell with PNG icons', () => {
    const manifest = readManifest();
    const icons = manifest.icons ?? [];

    expect(manifest.id).toBe('./');
    expect(manifest.start_url).toBe('./');
    expect(manifest.scope).toBe('./');
    expect(manifest.display).toBe('standalone');
    expect(manifest.background_color).toBe('#FAF8F2');
    expect(manifest.theme_color).toBe('#FAF8F2');
    expect(icons).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          src: './icons/ahadiff-192.png',
          sizes: '192x192',
          type: 'image/png',
        }),
        expect.objectContaining({
          src: './icons/ahadiff-512.png',
          sizes: '512x512',
          type: 'image/png',
        }),
        expect.objectContaining({
          src: './icons/ahadiff.svg',
          sizes: 'any',
          type: 'image/svg+xml',
        }),
      ]),
    );
    expect(existsSync(publicPath('icons/ahadiff-192.png'))).toBe(true);
    expect(existsSync(publicPath('icons/ahadiff-512.png'))).toBe(true);
  });
});
