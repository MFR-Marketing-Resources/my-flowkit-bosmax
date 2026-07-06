import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Boot build-identity marker. One concise line at startup (safe in production —
// not a debug spam loop) plus a window handle for quick inspection. Makes a
// stale served bundle obvious: compare `window.__FLOWKIT_BUILD__.sha` against
// the running agent's expected commit instead of assuming "probably cache".
const FLOWKIT_BUILD = { sha: __BUILD_SHA__, builtAt: __BUILT_AT__ } as const
;(window as unknown as { __FLOWKIT_BUILD__?: typeof FLOWKIT_BUILD }).__FLOWKIT_BUILD__ =
  FLOWKIT_BUILD
console.info(`[flowkit] build ${FLOWKIT_BUILD.sha} · built ${FLOWKIT_BUILD.builtAt}`)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
