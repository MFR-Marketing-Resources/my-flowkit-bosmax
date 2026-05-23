# Google Flow - Authenticated Extension Flowchart

This flowchart maps the automated extension execution logic inside the new Google Flow workspace interface.

```mermaid
graph TD
    Boot([Page Initialization]) --> CSStart[content-flow-dom.js injected]
    CSStart --> PortConnect[Establish chrome.runtime.connect link]
    
    PortConnect --> BuildCheck{Verify BUILD_ID Match}
    BuildCheck -- Mismatch --> CSBlock[Block execution & report build=legacy error]
    BuildCheck -- Match --> ReadySignal[Transmit RUNTIME_READY state telemetry]
    
    ReadySignal --> QueueListen[Listen for WebSocket execution jobs]
    
    QueueListen --> JobCheck{Job Received?}
    JobCheck -- Yes --> ParseConfig[Parse target prompt, model, and assets]
    
    ParseConfig --> ModelSetup{Check Active Model}
    ModelSetup -- Different --> ClickDropdown[Click model menu trigger button]
    ClickDropdown --> MenuPopup[Wait for Radix menu popup options to load]
    MenuPopup --> SelectModelItem[Click matching model menu item]
    ModelSetup -- Correct --> UploadCheck{Requires Upload?}
    SelectModelItem --> UploadCheck
    
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
