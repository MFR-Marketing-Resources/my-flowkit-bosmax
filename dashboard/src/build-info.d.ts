// Build-identity globals injected by Vite `define` at build time.
// See dashboard/vite.config.ts. Used by main.tsx to emit a boot marker so a
// stale served bundle is diagnosable at a glance (compare against the running
// agent's expected SHA instead of guessing "probably cache").
declare const __BUILD_SHA__: string;
declare const __BUILT_AT__: string;
