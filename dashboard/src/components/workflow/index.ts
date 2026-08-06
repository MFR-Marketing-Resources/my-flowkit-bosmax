// V4 workflow kit — the shared design-system components for the guided
// generation shell (one shell, every lane). Additive: teal/violet identity via
// the --color-v4-* tokens in index.css; conforms to the app's dark, Tailwind v4
// tone system. Consumed first by the T2V V4 layout, then rolled to other lanes.
export { WorkflowStep } from "./WorkflowStep";
export type { WorkflowStepProps, WorkflowStepStatus } from "./WorkflowStep";
export { ResolvedChip } from "./ResolvedChip";
export type { ResolvedChipProps } from "./ResolvedChip";
export { StoryboardStrip } from "./StoryboardStrip";
export type { StoryboardStripProps, StoryboardShot } from "./StoryboardStrip";
export { QueueRow } from "./QueueRow";
export type { QueueRowProps, QueueStatus } from "./QueueRow";
export { OperatorCockpit } from "./OperatorCockpit";
export type {
	OperatorCockpitProps,
	CockpitPlanRow,
	CockpitGenerate,
	CockpitState,
} from "./OperatorCockpit";
