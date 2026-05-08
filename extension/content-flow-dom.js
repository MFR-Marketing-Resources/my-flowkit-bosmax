/**
 * Flow Kit — Google Flow DOM Executor
 * 
 * Automates the generation workflow in the Flow UI.
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
    PROMPT_FIELD_FOUND: 'PROMPT_FIELD_FOUND',
    PROMPT_INSERTED: 'PROMPT_INSERTED',
    PROMPT_VERIFIED: 'PROMPT_VERIFIED',
    GENERATE_BUTTON_FOUND: 'GENERATE_BUTTON_FOUND',
    GENERATE_BUTTON_ENABLED: 'GENERATE_BUTTON_ENABLED',
    GENERATE_BUTTON_CLICKED: 'GENERATE_BUTTON_CLICKED',
    GENERATION_STARTED: 'GENERATION_STARTED',
    GENERATION_COMPLETED_OR_TIMEOUT: 'GENERATION_COMPLETED_OR_TIMEOUT',
    DOWNLOAD_CAPTURED_OR_NOT_AVAILABLE: 'DOWNLOAD_CAPTURED_OR_NOT_AVAILABLE'
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
    // Search for button with right arrow icon (M10 20l-1.41-1.41L15.17 12 8.59 5.41 10 4l8 8-8 8z)
    // or similar arrow path
    const paths = document.querySelectorAll('path');
    for (const path of paths) {
      const d = path.getAttribute('d') || '';
      if (d.includes('M10 20') || d.includes('M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z')) {
        return path.closest('button');
      }
    }
    // Fallback: search for button next to composer
    const composer = document.querySelector('textarea, [contenteditable="true"], [role="textbox"]');
    if (composer) {
      const parent = composer.parentElement;
      if (parent) {
        const buttons = parent.querySelectorAll('button');
        if (buttons.length > 0) return buttons[buttons.length - 1]; // Usually the last button in the composer bar
      }
    }
    return document.querySelector('button[aria-label="Generate"]') || document.querySelector('button[title="Generate"]');
  }

  async function executeFlowJob(job) {
    const report = { ok: false, stages: [] };
    const logStage = (stage, status = 'YES') => {
      report.stages.push({ stage, status });
      console.log(`[FlowAgent] Stage: ${stage} - ${status}`);
    };

    try {
      logStage(STAGES.FLOW_TAB_FOUND);

      // 1. Select Mode (Image / Video)
      const modeBtn = findElementByText('button, div[role="button"], span', job.mode === 'IMG' ? 'Image' : 'Video');
      if (!modeBtn) throw new Error(`Mode button ${job.mode} not found`);
      modeBtn.click();
      await sleep(1000);
      logStage(STAGES.FLOW_MODE_SELECTED);

      // 2. Select Submode (for Video)
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

      // 4. Set Count
      const countBtn = findElementByText('button, div[role="button"]', `${job.count}x`);
      if (countBtn) {
        countBtn.click();
        await sleep(500);
        logStage(STAGES.COUNT_SELECTED);
      }

      // 5. Set Model
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

      // 6. Attach Image
      // Check for image previews in the DOM.
      const previews = document.querySelectorAll('img[src^="blob:"], img[src^="https://storage.googleapis.com"]');
      if (previews.length > 0) {
        logStage(STAGES.IMAGE_ATTACHED);
      } else {
        logStage(STAGES.IMAGE_ATTACHED, 'NO (MAYBE BACKGROUND UPLOADED)');
      }

      // 7. Insert Prompt
      const composer = document.querySelector('textarea, [contenteditable="true"], [role="textbox"]');
      if (!composer) throw new Error('Prompt composer not found');
      logStage(STAGES.PROMPT_FIELD_FOUND);

      composer.focus();
      // Clear if contenteditable
      if (composer.getAttribute('contenteditable') === 'true') {
        composer.innerHTML = '';
      }
      
      if ('value' in composer) {
        composer.value = job.prompt;
        composer.dispatchEvent(new Event('input', { bubbles: true }));
        composer.dispatchEvent(new Event('change', { bubbles: true }));
      } else {
        composer.textContent = job.prompt;
        composer.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: job.prompt }));
      }
      await sleep(500);
      logStage(STAGES.PROMPT_INSERTED);

      // Verify prompt
      const actualText = (composer.value || composer.textContent || '').trim();
      if (actualText.length > 0) {
        logStage(STAGES.PROMPT_VERIFIED);
      } else {
        // One more try with focus + execCommand
        composer.focus();
        document.execCommand('insertText', false, job.prompt);
        await sleep(300);
        if ((composer.value || composer.textContent || '').trim().length > 0) {
          logStage(STAGES.PROMPT_VERIFIED);
        } else {
          throw new Error('Prompt insertion verification failed');
        }
      }

      // 8. Click Generate
      const generateBtn = findButtonByIcon();
      if (!generateBtn) throw new Error('Generate button not found');
      logStage(STAGES.GENERATE_BUTTON_FOUND);

      if (generateBtn.disabled) {
        logStage(STAGES.GENERATE_BUTTON_ENABLED, 'NO (WAITING)');
        await sleep(3000);
      }
      
      if (!generateBtn.disabled) {
        logStage(STAGES.GENERATE_BUTTON_ENABLED);
        generateBtn.click();
        logStage(STAGES.GENERATE_BUTTON_CLICKED);
        
        // 9. Detect Job Start
        await sleep(1500);
        // Look for loading states
        const progress = document.querySelector('[role="progressbar"], .loading, .spinner');
        if (generateBtn.disabled || progress) {
          logStage(STAGES.GENERATION_STARTED);
          report.ok = true;
        } else {
          logStage(STAGES.GENERATION_STARTED, 'MAYBE');
          report.ok = true;
        }
      } else {
        throw new Error('Generate button disabled after wait');
      }

      // 10. Download Capture (Not implemented yet, but we report it)
      logStage(STAGES.DOWNLOAD_CAPTURED_OR_NOT_AVAILABLE, 'NOT_IMPLEMENTED');

    } catch (e) {
      console.error('[FlowAgent] Job execution failed:', e);
      report.error = e.message;
      report.ok = false;
    }

    return report;
  }

  // Listen for messages from background script
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === 'EXECUTE_FLOW_JOB') {
      executeFlowJob(msg.job).then(sendResponse);
      return true;
    }
  });

})();
