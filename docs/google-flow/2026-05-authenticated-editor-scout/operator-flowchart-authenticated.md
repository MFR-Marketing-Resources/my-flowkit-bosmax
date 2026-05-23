# Google Flow - Authenticated Operator Flowchart

This flowchart outlines the updated operator user journey within the authenticated Google Flow project workspace.

> [!NOTE]
> **Truth Partitioning Legend**:
> - Steps 1-38 (Workspace entry, Composer dock analysis, Agent ON/OFF layout shifts, Model settings tab and chip selection) are **VERIFIED_LIVE**.
> - Steps 39-44 (File uploading triggers and local file selection) are **VERIFIED_LIVE** as elements but their end-to-end execution flow is **INFERRED_FROM_CODE**.
> - Steps 45-49 (Submission of generation, progress loading, and asset verification in gallery) are **NOT VERIFIED** live due to credit preservation.

```mermaid
graph TD
    Start([1. Dashboard Entry]) --> ViewProjects[Scan project workspace list]
    ViewProjects --> ChooseAction{Select Project Action}
    
    ChooseAction -- Open Existing --> ClickProject[Click existing project card]
    ChooseAction -- Create New --> ClickNewProject[Click "+ New Project" button]
    
    ClickProject & ClickNewProject --> LoadWorkspace[Load Editor Workspace Canvas]
    
    LoadWorkspace --> ComposerDock[Observe Bottom Composer Panel]
    ComposerDock --> AgentCheck{Verify Flow Agent Toggle}
    
    AgentCheck -- Default OFF --> ModelChipCheck[Observe Model selector chip]
    ModelChipCheck --> ClickModelTrigger[Click model selector trigger e.g. Banana]
    ClickModelTrigger --> PopoverOpen[Open Settings Popover]
    
    PopoverOpen --> ModeSelect{Choose Generation Mode}
    ModeSelect -- Image Mode --> ClickImageTab[Click "Image" tab button]
    ModeSelect -- Video Mode --> ClickVideoTab[Click "Video" tab button]
    
    ClickImageTab & ClickVideoTab --> SetAspect[Select Aspect Ratio chip: 16:9, 4:3, 1:1, 3:4, 9:16]
    SetAspect --> SetCount[Select Quantity chip: 1x, x2, x3, x4]
    SetCount --> ChooseModel[Select base model from dropdown list]
    
    ChooseModel --> ClosePopover[Press Escape or click outside to apply]
    ClosePopover --> EnterPrompt[Click contenteditable DIV & type prompt]
    
    AgentCheck -- Toggle ON --> ClickAgentBtn[Click "Agent" button to activate AI helper]
    ClickAgentBtn --> HideModelChip[Model selector chip disappears from UI]
    HideModelChip --> ShowAgentTools[Creative Brief and Parameter Slider buttons appear]
    ShowAgentTools --> ConfigAgent[Configure Creative Brief template and parameter settings]
    ConfigAgent --> EnterPrompt
    
    EnterPrompt --> UploadAsset{Upload Image/Video?}
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
