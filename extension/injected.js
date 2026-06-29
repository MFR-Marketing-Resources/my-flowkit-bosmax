/**
 * Injected into MAIN world on labs.google — has access to window.grecaptcha
 * Also intercepts TRPC fetch responses to capture fresh signed media URLs.
 */
(function () {
if (window.__flowkitInjectedInit) return;
window.__flowkitInjectedInit = true;
try { if (document.documentElement) document.documentElement.dataset.flowkitCaptchaBridgeInjected = 'true'; } catch (_) {}

const SITE_KEY = '6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV';

// ─── TRPC Response Monitor ─────────────────────────────────
// Monkey-patch fetch to intercept TRPC responses containing media URLs.
// Fresh signed GCS URLs are extracted and forwarded to the agent.

const _originalFetch = window.fetch;
window.fetch = async function (...args) {
  const response = await _originalFetch.apply(this, args);
  try {
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
    // Only intercept TRPC calls on labs.google that return project/flow data
    if (url.includes('/fx/api/trpc/') && response.ok) {
      const clone = response.clone();
      clone.text().then(text => {
        if (text.includes('storage.googleapis.com/ai-sandbox-videofx/')) {
          window.dispatchEvent(new CustomEvent('TRPC_MEDIA_URLS', {
            detail: { url, body: text },
          }));
        }
      }).catch(() => {});
    }
  } catch {}
  return response;
};


// ─── Capture grecaptcha actions (learn the agent endpoint's reCAPTCHA action) ──
// Records the `action` of every grecaptcha.enterprise.execute call into a DOM
// dataset (readable from the extension via executeScript) so we can discover the
// exact action the Flow UI uses for flowCreationAgent:streamChat.
(function hookGrecaptchaAction() {
  function logAction(action) {
    if (!action) return;
    try {
      const el = document.documentElement;
      let arr = [];
      try { arr = JSON.parse(el.dataset.flowkitActions || '[]'); } catch (_) {}
      arr.push({ action, ts: Date.now() });
      el.dataset.flowkitActions = JSON.stringify(arr.slice(-50));
    } catch (_) {}
  }
  function tryWrap() {
    const ent = window.grecaptcha && window.grecaptcha.enterprise;
    if (ent && ent.execute && !ent.__flowkitActionWrapped) {
      const orig = ent.execute.bind(ent);
      ent.execute = function (key, opts) {
        try { logAction(opts && opts.action); } catch (_) {}
        return orig(key, opts);
      };
      ent.__flowkitActionWrapped = true;
      return true;
    }
    return false;
  }
  if (!tryWrap()) {
    const iv = setInterval(() => { if (tryWrap()) clearInterval(iv); }, 300);
    setTimeout(() => clearInterval(iv), 60000);
  }
})();

window.addEventListener('GET_CAPTCHA', async ({ detail }) => {
  const { requestId, pageAction } = detail;
  try {
    await waitForGrecaptcha();
    const token = await window.grecaptcha.enterprise.execute(SITE_KEY, {
      action: pageAction,
    });
    window.dispatchEvent(new CustomEvent('CAPTCHA_RESULT', {
      detail: { requestId, token },
    }));
  } catch (e) {
    window.dispatchEvent(new CustomEvent('CAPTCHA_RESULT', {
      detail: { requestId, error: e.message },
    }));
  }
});

function waitForGrecaptcha(timeout = 10000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const check = () => {
      if (window.grecaptcha?.enterprise?.execute) return resolve();
      if (Date.now() - start > timeout) return reject(new Error('grecaptcha not available'));
      setTimeout(check, 200);
    };
    check();
  });
}
})();
