/**
 * Flow Kit — Content Script
 *
 * Injected into Google Flow tabs to solve reCAPTCHA and automate UI.
 */

// Avoid multiple injections
if (!window._flowKitInjected) {
  window._flowKitInjected = true;
  console.log('[FlowAgent] Content script injected');
  const CAPTCHA_PROTOCOL_VERSION = 'FLOWKIT_CAPTCHA_V1';

  // Default timeout for async listener handlers in content.js (captcha path).
  // reCAPTCHA Enterprise can normally resolve well under 5s; if grecaptcha
  // hangs we surface a structured timeout instead of leaking the port.
  const DEFAULT_CAPTCHA_RESPOND_ASYNC_TIMEOUT_MS = 8000;

  function respondAsync(sendResponse, task, timeoutMs = DEFAULT_CAPTCHA_RESPOND_ASYNC_TIMEOUT_MS) {
    let settled = false;
    let timer = null;

    const done = (payload) => {
      if (settled) return;
      settled = true;
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      try {
        sendResponse(payload || { ok: true });
      } catch (error) {
        console.warn('[FlowAgent] sendResponse failed:', error);
      }
    };

    timer = setTimeout(() => {
      done({
        ok: false,
        error: 'ERR_CONTENT_ASYNC_RESPONSE_TIMEOUT',
        detail: `content.js respondAsync exceeded ${timeoutMs}ms`,
      });
    }, timeoutMs);

    Promise.resolve()
      .then(task)
      .then((result) => done(result))
      .catch((error) => done({ ok: false, error: String(error?.message || error) }));

    return true;
  }

  async function handleMessage(msg, sender) {
    if (msg.type === 'GET_CAPTCHA') {
      try {
        const token = await solveRecaptcha(msg.pageAction || 'IMAGE_GENERATION');
        return { token };
      } catch (e) {
        return { error: e.message || 'CAPTCHA_FAILED' };
      }
    }

    if (msg.type === 'PING') {
      return { ok: true };
    }

    if (msg.type === 'FLOWKIT_CAPTCHA_PING') {
      return {
        ok: true,
        content_script_loaded: true,
        content_script_protocol_version: CAPTCHA_PROTOCOL_VERSION,
        location_href: window.location.href,
        timestamp: new Date().toISOString(),
      };
    }

    return null;
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'PING') {
      sendResponse({ ok: true });
      return false;
    }

    if (message.type === 'FLOWKIT_CAPTCHA_PING') {
      sendResponse({
        ok: true,
        content_script_loaded: true,
        content_script_protocol_version: CAPTCHA_PROTOCOL_VERSION,
        location_href: window.location.href,
        timestamp: new Date().toISOString(),
      });
      return false;
    }

    if (message.type !== 'GET_CAPTCHA') {
      return false;
    }

    return respondAsync(sendResponse, async () => {
      const data = await handleMessage(message, sender);
      return data ?? { ok: false, error: 'ERR_UNKNOWN_MESSAGE_TYPE' };
    });
  });

  /**
   * Google Flow uses reCAPTCHA Enterprise.
   * We must find the enterprise checkbox/hidden input or use the grecaptcha object.
   */
  async function solveRecaptcha(action) {
    return new Promise((resolve, reject) => {
      // reCAPTCHA Enterprise is usually available on window.grecaptcha.enterprise
      const grecaptcha = window.grecaptcha?.enterprise || window.grecaptcha;

      if (!grecaptcha?.execute) {
        // Try to find it in the main world if not in isolated world
        // (This extension uses standard injection, so we might need to proxy to main world)
        reject(new Error('reCAPTCHA not found in content script context'));
        return;
      }

      // Site key from Google Flow
      const siteKey = '6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV';

      grecaptcha.ready(async () => {
        try {
          const token = await grecaptcha.execute(siteKey, { action });
          resolve(token);
        } catch (e) {
          reject(e);
        }
      });
    });
  }
}
