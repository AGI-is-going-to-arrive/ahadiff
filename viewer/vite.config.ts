import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import type { ClientRequest, IncomingMessage } from 'node:http';

const DEV_API_ORIGIN = 'http://127.0.0.1:8765';

function rewriteLoopbackProxyHeaders(proxyReq: ClientRequest, _req: IncomingMessage): void {
  proxyReq.setHeader('Host', '127.0.0.1:8765');
  proxyReq.setHeader('Origin', DEV_API_ORIGIN);
  proxyReq.setHeader('Referer', DEV_API_ORIGIN);
}

// Phase 2G: route-based code splitting + manualChunks budget guard.
// Goal: keep initial gzip < 80KB by ensuring vendor / heavy modules ship in
// their own async chunks. See plan §2G + risk R6 (d3-force / future graph).
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': {
        target: DEV_API_ORIGIN,
        changeOrigin: true,
        secure: false,
        configure: (proxy) => {
          proxy.on('proxyReq', rewriteLoopbackProxyHeaders);
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    emptyOutDir: true,
    manifest: true,
    chunkSizeWarningLimit: 250,
    /**
     * Phase 4F: Strip page-only async dependencies (zod, future d3-force,
     * future prismjs) from the synchronous modulepreload set. Without this,
     * any vendor chunk imported transitively by a single lazy page would be
     * preloaded on initial HTML and counted against the < 80KB initial-gzip
     * budget. We still ship the chunks; they just load on the first route
     * navigation that needs them.
     *
     * `resolveDependencies` runs per-chunk; it controls modulepreload tag
     * emission, not actual chunking — `manualChunks` below is the source of
     * truth for chunk graph.
     */
    modulePreload: {
      resolveDependencies: (
        _filename: string,
        deps: string[],
        _ctx: { hostId: string; hostType: 'js' | 'html' },
      ): string[] => {
        return deps.filter((dep) => {
          // Keep core shell + routing chunks in modulepreload — they're
          // required before any route can render.
          if (dep.includes('vendor-react')) return true;
          if (dep.includes('vendor-router')) return true;
          if (dep.endsWith('.css')) return true;
          // vendor-page-deps holds zod + any other page-only async deps.
          // Skip preloading; first navigation pays the latency.
          if (dep.includes('vendor-page-deps')) return false;
          return true;
        });
      },
    },
    rollupOptions: {
      output: {
        manualChunks: (id: string): string | undefined => {
          if (!id.includes('node_modules')) return undefined;
          // React core lives in its own vendor chunk so the initial route
          // payload only carries it once.
          if (
            id.includes('node_modules/react/') ||
            id.includes('node_modules/react-dom/') ||
            id.includes('node_modules/scheduler/')
          ) {
            return 'vendor-react';
          }
          // Routing + state are also part of the shell, but smaller; keep
          // them together so route-level chunks don't duplicate them.
          // `@remix-run/router` is a transitive dep of react-router-dom and
          // belongs in the same bucket — without this branch it would fall
          // into vendor-misc and quietly enter the initial critical path.
          if (
            id.includes('node_modules/react-router') ||
            id.includes('node_modules/@remix-run/router') ||
            id.includes('node_modules/zustand')
          ) {
            return 'vendor-router';
          }
          // Page-only deps (zod runtime validation, future d3-force,
          // future prismjs) are excluded from modulepreload above so they
          // don't enter the < 80KB initial budget. Adding more lazy-only
          // deps? Add their substring here; the budget guard fails closed.
          if (id.includes('node_modules/zod')) {
            return 'vendor-page-deps';
          }
          // Anything else from node_modules still bucketed for stability.
          return 'vendor-misc';
        },
      },
    },
  },
});
