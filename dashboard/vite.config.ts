import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { execSync } from 'node:child_process'

// Build-identity stamp — injected into the bundle so the running dashboard can
// announce which commit/build it was compiled from. This is the durable fix for
// recurring "stale bundle / did my patch ship?" confusion: the browser prints
// its build SHA at boot, so it can be compared against the expected commit
// instead of guessing. Falls back to 'unknown' when git is unavailable (e.g. a
// tarball build); FLOWKIT_BUILD_SHA env override wins for CI/hermetic builds.
function resolveBuildSha(): string {
  if (process.env.FLOWKIT_BUILD_SHA) return process.env.FLOWKIT_BUILD_SHA
  try {
    return execSync('git rev-parse --short HEAD', {
      stdio: ['ignore', 'pipe', 'ignore'],
    })
      .toString()
      .trim()
  } catch {
    return 'unknown'
  }
}

const BUILD_SHA = resolveBuildSha()
const BUILT_AT = new Date().toISOString()

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __BUILD_SHA__: JSON.stringify(BUILD_SHA),
    __BUILT_AT__: JSON.stringify(BUILT_AT),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8100',
      '/ws': { target: 'ws://127.0.0.1:8100', ws: true },
      '/health': 'http://127.0.0.1:8100',
    }
  },
  build: { outDir: 'dist' }
})
