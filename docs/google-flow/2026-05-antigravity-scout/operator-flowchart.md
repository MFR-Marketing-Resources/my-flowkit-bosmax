# Google Flow - Operator Flowchart

This flowchart visualizes the manual operator workflow inside the Google Flow application.

```mermaid
graph TD
    Start([1. Access Landing Page]) --> AccessURL[Go to labs.google/fx/tools/flow]
    AccessURL --> ClickCTA[Click "Create with Google Flow"]
    
    ClickCTA --> AuthGate{Google Sign-in Gate}
    AuthGate -- Sign-in Required --> LogIn[Enter Google Credentials & solve 2FA]
    AuthGate -- Already Authenticated --> Dashboard[Land on Google Flow Dashboard]
    LogIn --> Dashboard
    
    Dashboard --> CreateProj[Click "New Project"]
    CreateProj --> Editor[Open Project Editor Workspace]
    
    Editor --> ModeSelect[Select "Video" Tab]
    ModeSelect --> SubModeSelect[Select "Frames" Sub-mode Tab]
    
    SubModeSelect --> Settings{Configure Settings}
    Settings --> SetAspect[Select "9:16" Portrait aspect chip]
    Settings --> SetCount[Select "1x" Quantity chip]
    Settings --> SetModel[Verify "Veo 3.1 Lite" in model dropdown]
    
    SetAspect & SetCount & SetModel --> UploadStart[Click "Start" Slot]
    UploadStart --> OSFileDialog[Choose image from OS File Picker]
    OSFileDialog --> WaitUpload[Wait for image thumbnail preview]
    
    WaitUpload --> PromptInput[Enter visual description in Prompt textarea]
    PromptInput --> SubmitGate{Submit Generation}
    
    SubmitGate --> ClickGen[Click "Generate" Button]
    ClickGen --> ProgressRing[Observe spinning generation progress ring]
    
    ProgressRing --> GenResult{Generation Success?}
    GenResult -- Yes --> RenderOutput[View final video tile and play preview]
    GenResult -- No (Paygate) --> PaywallWarning[Downgrade quality settings or buy credits]
    GenResult -- No (Error) --> RetryGen[Click retry or inspect prompt constraints]
    
    RenderOutput --> End([End Workflow])
```
