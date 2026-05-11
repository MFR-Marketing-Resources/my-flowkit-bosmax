const DASHBOARD_PORTAL_URL = 'http://127.0.0.1:8100/operator';

function setPortalState(state, detail = '') {
  document.body.classList.toggle('ready', state === 'ready');
  document.body.classList.toggle('error', state === 'error');

  const statusEl = document.getElementById('portal-status');
  const errorEl = document.getElementById('portal-error');
  if (statusEl) {
    statusEl.textContent = detail || (state === 'ready'
      ? 'Dashboard connected.'
      : state === 'error'
        ? 'Dashboard failed to load.'
        : 'Connecting to localhost dashboard...');
  }
  if (errorEl && state !== 'error') {
    errorEl.textContent = 'Dashboard iframe did not finish loading. Confirm the local agent is serving http://127.0.0.1:8100/operator.';
  }
}

function bootSidePortal() {
  const frame = document.getElementById('dashboard-frame');
  const urlEl = document.getElementById('portal-url');
  if (!frame) {
    setPortalState('error', 'Dashboard iframe element is missing.');
    return;
  }

  if (urlEl) {
    urlEl.textContent = DASHBOARD_PORTAL_URL;
  }

  let settled = false;
  const markReady = () => {
    if (settled) return;
    settled = true;
    setPortalState('ready', 'Dashboard connected.');
  };

  const markError = (message) => {
    if (settled) return;
    settled = true;
    const errorEl = document.getElementById('portal-error');
    if (errorEl && message) {
      errorEl.textContent = message;
    }
    setPortalState('error', message || 'Dashboard failed to load.');
  };

  frame.addEventListener('load', () => {
    window.setTimeout(markReady, 250);
  }, { once: true });

  frame.addEventListener('error', () => {
    markError('Dashboard iframe failed to load. Confirm the local agent and operator route are reachable.');
  }, { once: true });

  window.setTimeout(() => {
    if (!settled) {
      markError('Dashboard load timed out. Confirm http://127.0.0.1:8100/operator is live and allowed inside the extension side panel.');
    }
  }, 12000);

  frame.src = DASHBOARD_PORTAL_URL;
  setPortalState('loading', 'Connecting to localhost dashboard...');
}

document.addEventListener('DOMContentLoaded', bootSidePortal);
