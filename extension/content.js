/**
 * Flow Kit — Content Script
 *
 * Injected into Google Flow tabs to solve reCAPTCHA and automate UI.
 */

// Avoid multiple injections
if (!window._flowKitInjected) {
  window._flowKitInjected = true;
  console.log('[FlowAgent] Content script injected');

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

    return null;
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'PING') {
      sendResponse({ ok: true });
      return false;
    }

    if (message.type !== 'GET_CAPTCHA') {
      return false;
    }

    ;(async () => {
      try {
        const data = await handleMessage(message, sender);
        sendResponse(data ?? { ok: false, error: 'UNHANDLED_MESSAGE_TYPE' });
      } catch (error) {
        sendResponse({ error: String(error?.message || error) });
      }
    })();
    return true;
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
