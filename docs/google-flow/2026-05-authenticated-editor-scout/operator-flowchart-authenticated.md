# Google Flow - Authenticated Operator Flowchart

This flowchart outlines the updated operator user journey within the authenticated Google Flow project workspace.

```mermaid
graph TD
    Start([1. Dashboard Entry]) --> ViewProjects[Scan project workspace list]
    ViewProjects --> ChooseAction{Select Project Action}
    
    ChooseAction -- Open Existing --> ClickProject[Click existing project card]
    ChooseAction -- Create New --> ClickNewProject[Click "+ New Project" button]
    
    ClickProject & ClickNewProject --> LoadWorkspace[Load Editor Workspace Canvas]
    
    LoadWorkspace --> ComposerDock[Observe Bottom Composer Panel]
    ComposerDock --> PromptCheck{Verify Prompt Input}
    ComposerDock --> ModelCheck{Verify Model Selector}
    ComposerDock --> AgentCheck{Verify Flow Agent Toggle}
    
    PromptCheck -- Empty --/ Textarea -> EnterPrompt[Click contenteditable DIV & type prompt]
    ModelCheck -- Defaults to Nano Banana 2 --> ClickModelTrigger[Click model dropdown trigger]
    ClickModelTrigger --> SelectModel[Choose target model from popup menu]
    AgentCheck -- Default OFF --> ToggleAgent{Toggle Flow Agent?}
    
    ToggleAgent -- Yes --> ClickAgentBtn[Click "Agent" button to activate AI helper]
    ToggleAgent -- No --> KeepAgentOff[Proceed with Flow Agent disabled]
    
    EnterPrompt & SelectModel & ClickAgentBtn & KeepAgentOff --> UploadAsset{Upload Image/Video?}
    UploadAsset -- Yes --> ClickAddMedia[Click "addAdd Media" button]
    ClickAddMedia --> FilePicker[Select local file from OS file picker]
    FilePicker --> AssetVerify[Confirm thumbnail appears in composer preview]
    UploadAsset -- No --> ReadySubmit[Composer is ready for generation]
    AssetVerify --> ReadySubmit
    
    ReadySubmit --> SubmitGen[Click enabled "arrow_forwardCreate" button]
    SubmitGen --> ObserveProgress[Observe progress loading indicator]
    ObserveProgress --> RenderResult[View output asset tile in the workspace gallery]
    RenderResult --> End([End Workflow])
```
