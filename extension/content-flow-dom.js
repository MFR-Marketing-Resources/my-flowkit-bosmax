/**
 * Flow Kit — Google Flow DOM Executor
 * 
 * Automates the generation workflow in the Flow UI with human-like interactions.
 */

(function() {
  if (window._flowKitDomInjected) {
    console.log('[FlowAgent] Flow DOM Executor already present');
    return;
  }
  window._flowKitDomInjected = true;
  console.log('[FlowAgent] Flow DOM Executor injected');

  const STAGES = {
    FLOW_TAB_FOUND: 'FLOW_TAB_FOUND',
    FLOW_MODE_SELECTED: 'FLOW_MODE_SELECTED',
    FLOW_SUBMODE_SELECTED: 'FLOW_SUBMODE_SELECTED',
    ASPECT_SELECTED: 'ASPECT_SELECTED',
    COUNT_SELECTED: 'COUNT_SELECTED',
    MODEL_SELECTED: 'MODEL_SELECTED',
    IMAGE_ATTACHED: 'IMAGE_ATTACHED',
    COMPOSER_FOUND: 'COMPOSER_FOUND',
    COMPOSER_TYPE: 'COMPOSER_TYPE',
    PROMPT_INSERT_METHOD: 'PROMPT_INSERT_METHOD',
    PROMPT_VISIBLE: 'PROMPT_VISIBLE',
    PROMPT_EDITABLE_AFTER_INSERT: 'PROMPT_EDITABLE_AFTER_INSERT',
    GENERATE_ARROW_ENABLED: 'GENERATE_ARROW_ENABLED',
    GENERATE_CLICKED: 'GENERATE_CLICKED',
    GENERATION_STARTED: 'GENERATION_STARTED',
    VIDEO_JOB_RUNNING_OR_GENERATED: 'VIDEO_JOB_RUNNING_OR_GENERATED',
    DOWNLOAD_CAPTURE: 'DOWNLOAD_CAPTURE'
  };

  async function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  function findElementByText(selector, text) {
    const elements = document.querySelectorAll(selector);
    for (const el of elements) {
      if (el.textContent.trim().toLowerCase() === text.toLowerCase()) return el;
    }
    // Fallback to fuzzy match
    for (const el of elements) {
      if (el.textContent.trim().toLowerCase().includes(text.toLowerCase())) return el;
    }
    return null;
  }

  function findButtonByIcon() {
    // Search for button with right arrow icon
    const paths = document.querySelectorAll('path');
    for (const path of paths) {
      const d = path.getAttribute('d') || '';
      if (d.includes('M10 20l-1.41-1.41L15.17 12 8.59 5.41 10 4l8 8-8 8z') ||
          d.includes('M10 20') ||
          d.includes('M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z')) {
        return path.closest('button');
      }
    }
    const composer = document.querySelector('textarea, [contenteditable="true"], [role="textbox"]');
    if (composer) {
      const parent = composer.parentElement;
      if (parent) {
        const buttons = parent.querySelectorAll('button');
        if (buttons.length > 0) return buttons[buttons.length - 1];
      }
    }
    return document.querySelector('button[aria-label="Generate"]') || document.querySelector('button[title="Generate"]');
  }

  function getComposerText(el) {
    if ('value' in el) return el.value;
    return el.textContent || '';
  }

  function isComposerEditable(el) {
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
    if (el.getAttribute('contenteditable') === 'false') return false;
    return true;
  }

  async function keyboardClear(el) {
    el.focus();
    await sleep(50);
    if ('value' in el) {
      el.value = '';
    } else {
      el.innerHTML = '';
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(50);
  }

  function setNativeValue(el, value) {
    const proto = Object.getPrototypeOf(el);
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    setter?.call(el, value);
    el.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, inputType: 'insertText', data: value }));
    el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function insertTextLikeUser(el, text) {
    el.focus();
    const ok = document.execCommand && document.execCommand('insertText', false, text);
    if (!ok) {
      el.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, inputType: 'insertText', data: text }));
      if ('value' in el) {
        const start = el.selectionStart || 0;
        const end = el.selectionEnd || 0;
        el.value = el.value.substring(0, start) + text + el.value.substring(end);
        el.selectionStart = el.selectionEnd = start + text.length;
      } else {
        el.textContent = `${el.textContent || ''}${text}`;
      }
      el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
    }
  }

  async function humanTypePrompt(composer, prompt) {
    composer.click();
    composer.focus();
    await sleep(100);

    await keyboardClear(composer);

    const chunks = prompt.match(/.{1,12}/g) || [];
    for (const chunk of chunks) {
      insertTextLikeUser(composer, chunk);
      await sleep(10);
    }

    await sleep(300);
  }

  async function executeFlowJob(job) {
    const report = { ok: false, stages: [] };
    const logStage = (stage, status = 'YES') => {
      report.stages.push({ stage, status });
      console.log(`[FlowAgent] Stage: ${stage} - ${status}`);
    };

    try {
      logStage(STAGES.FLOW_TAB_FOUND);

      // 1. Select Mode
      const modeBtn = findElementByText('button, div[role="button"], span', job.mode === 'IMG' ? 'Image' : 'Video');
      if (!modeBtn) throw new Error(`Mode button ${job.mode} not found`);
      modeBtn.click();
      await sleep(1000);
      logStage(STAGES.FLOW_MODE_SELECTED);

      // 2. Select Submode
      if (job.mode !== 'IMG') {
        const submodeText = job.mode === 'F2V' ? 'Frames' : 'Ingredients';
        const submodeBtn = findElementByText('button, div[role="button"], span', submodeText);
        if (!submodeBtn) throw new Error(`Submode button ${submodeText} not found`);
        submodeBtn.click();
        await sleep(1000);
        logStage(STAGES.FLOW_SUBMODE_SELECTED);
      }

      // 3. Set Aspect Ratio
      const aspectBtn = findElementByText('button, div[role="button"]', job.aspectRatio);
      if (aspectBtn) {
        aspectBtn.click();
        await sleep(500);
        logStage(STAGES.ASPECT_SELECTED);
      }

      // 4. Set Model
      const modelDropdown = document.querySelector('[aria-haspopup="listbox"]') || 
                           findElementByText('button', 'Nano Banana') || 
                           findElementByText('button', 'Veo');
      if (modelDropdown) {
        modelDropdown.click();
        await sleep(800);
        const modelOption = findElementByText('[role="option"], li, span', job.modelLabel);
        if (modelOption) {
          modelOption.click();
          await sleep(800);
          logStage(STAGES.MODEL_SELECTED);
        }
      }

      // 5. Attach Image (Check if preview exists)
      const previews = document.querySelectorAll('img[src^="blob:"], img[src^="https://storage.googleapis.com"]');
      if (previews.length > 0) {
        logStage(STAGES.IMAGE_ATTACHED);
      } else {
        logStage(STAGES.IMAGE_ATTACHED, 'NO (MAYBE BACKGROUND UPLOADED)');
      }

      // 6. Composer Setup
      const composer = document.querySelector('textarea, [contenteditable="true"], [role="textbox"]');
      if (!composer) {
        logStage(STAGES.COMPOSER_FOUND, 'NO');
        throw new Error('PROMPT_FIELD_NOT_FOUND');
      }
      logStage(STAGES.COMPOSER_FOUND);
      const cType = composer.tagName === 'TEXTAREA' ? 'TEXTAREA' : (composer.getAttribute('contenteditable') === 'true' ? 'CONTENTEDITABLE' : 'OTHER');
      logStage(STAGES.COMPOSER_TYPE, cType);

      // 7. Human-like Typing
      logStage(STAGES.PROMPT_INSERT_METHOD, 'HUMAN_TYPING');
      await humanTypePrompt(composer, job.prompt);
      
      const actual = getComposerText(composer);
      if (!actual || !actual.includes(job.prompt.slice(0, 10))) {
        logStage(STAGES.PROMPT_VISIBLE, 'NO');
        throw new Error('PROMPT_INSERT_FAILED');
      }
      logStage(STAGES.PROMPT_VISIBLE);

      if (!isComposerEditable(composer)) {
        logStage(STAGES.PROMPT_EDITABLE_AFTER_INSERT, 'NO');
        throw new Error('PROMPT_INSERT_LOCKED_OR_UNTRUSTED');
      }
      logStage(STAGES.PROMPT_EDITABLE_AFTER_INSERT);

      // 8. Click Generate
      const generateBtn = findButtonByIcon();
      if (!generateBtn) throw new Error('GENERATE_ARROW_NOT_FOUND');
      if (generateBtn.disabled) {
        await sleep(2000); // Wait for validation
      }

      if (generateBtn.disabled) {
        logStage(STAGES.GENERATE_ARROW_ENABLED, 'NO');
        throw new Error('GENERATE_ARROW_DISABLED_AFTER_PROMPT');
      }
      logStage(STAGES.GENERATE_ARROW_ENABLED);
      
      generateBtn.click();
      logStage(STAGES.GENERATE_CLICKED);

      // 9. Detect Job Start
      await sleep(1500);
      const progress = document.querySelector('[role="progressbar"], .loading, .spinner');
      if (generateBtn.disabled || progress) {
        logStage(STAGES.GENERATION_STARTED);
        logStage(STAGES.VIDEO_JOB_RUNNING_OR_GENERATED);
        report.ok = true;
      } else {
        logStage(STAGES.GENERATION_STARTED, 'MAYBE');
        logStage(STAGES.VIDEO_JOB_RUNNING_OR_GENERATED, 'MAYBE');
        report.ok = true;
      }

      logStage(STAGES.DOWNLOAD_CAPTURE, 'NOT_IMPLEMENTED');

    } catch (e) {
      console.error('[FlowAgent] Job execution failed:', e);
      report.error = e.message;
      report.ok = false;
      // Add error as a stage for visibility in the report
      report.stages.push({ stage: 'ERROR', status: e.message });
    }

    return report;
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === 'EXECUTE_FLOW_JOB') {
      executeFlowJob(msg.job).then(sendResponse);
      return true;
    }
  });

})();
