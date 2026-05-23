# Google Flow - Authenticated Extension Flowchart

This flowchart maps the automated extension execution logic inside the new Google Flow workspace interface.

> [!NOTE]
> **Truth Partitioning Legend**:
> - Page Initialization, script injection, and runtime state transmission are **VERIFIED_LIVE** via diagnostics.
> - Selector targeting, popover interaction, and tab toggling logic are **VERIFIED_LIVE** based on static workspace DOM structure.
> - CDP debugger file interception, programmatic click execution, and generation progress observers are **INFERRED_FROM_CODE** and **NOT VERIFIED** live.

```mermaid
graph TD
    Boot([Page Initialization]) --> CSStart[content-flow-dom.js injected]
    CSStart --> PortConnect[Establish chrome.runtime.connect link]
    
    PortConnect --> BuildCheck{Verify BUILD_ID Match}
    BuildCheck -- Mismatch --> CSBlock[Block execution & report build=legacy error]
    BuildCheck -- Match --> ReadySignal[Transmit RUNTIME_READY state telemetry]
    
    ReadySignal --> QueueListen[Listen for WebSocket execution jobs]
    
    QueueListen --> JobCheck{Job Received?}
    JobCheck -- Yes --> ParseConfig[Parse target prompt, model, mode, and assets]
    
    ParseConfig --> ModelSetup{Check Active Model/Mode}
    ModelSetup -- Different --> ClickDropdown[Click model menu trigger button e.g. Banana]
    ClickDropdown --> PopoverWait[Wait for settings popover to render]
    
    PopoverWait --> ModeSelect{Verify Active Tab}
    ModeSelect -- Video Mode Requested --> ClickVideoTab[Click Video tab in popover]
    ModeSelect -- Image Mode Requested --> ClickImageTab[Click Image tab in popover]
    
    ClickVideoTab & ClickImageTab --> SetAspect[Click target Aspect Ratio chip: 16:9, 4:3, 1:1, 3:4, 9:16]
    SetAspect --> SetCount[Click target Quantity Count chip: 1x, x2, x3, x4]
    SetCount --> ChooseModel[Click active model dropdown and choose base model]
    ChooseModel --> ClosePopover[Press Escape to close settings popover]
    
    ModelSetup -- Correct --> UploadCheck{Requires Upload?}
    ClosePopover --> UploadCheck
    
    UploadCheck -- Yes --> CDPStart[Enable background CDP debugger listener]
    CDPStart --> InterceptFileChooser[Page.setInterceptFileChooserDialog enabled]
    InterceptFileChooser --> TriggerInputClick[Content script clicks hidden file input or Add Media]
    TriggerInputClick --> InterceptFileEvent[Debugger intercepts Page.fileChooserOpened]
    InterceptFileEvent --> InjectPath[Inject local path via DOM.setFileInputFiles]
    InjectPath --> CDPEnd[Detach background debugger session]
    CDPEnd --> ThumbWait[MutationObserver waits for preview thumbnail preview]
    ThumbWait --> PromptWrite[Inject prompt text into contenteditable DIV]
    
    UploadCheck -- No --> PromptWrite
    
    PromptWrite --> DispatchSynth[Dispatch Synthetic input/change events to React]
    DispatchSynth --> SubmitVerify{Check Create Button State}
    
    SubmitVerify -- Disabled --> TimeoutAbort[Abort: Generate button inactive]
    SubmitVerify -- Enabled --> ClickCreate[Trigger programmatic click on "Create" button]
    
    ClickCreate --> ProgressObserver[MutationObserver monitors workspace state]
    ProgressObserver --> StateDetect{Inspect Workspace Updates}
    
    StateDetect -- Completed --> ReportSuccess[Extract media details & emit GENERATION_SUCCESS]
    StateDetect -- Failure Modal --> ReportFailure[Extract error reasons & emit GENERATION_FAILED]
    
    ReportSuccess & ReportFailure & TimeoutAbort & CSBlock --> QueueListen
```
