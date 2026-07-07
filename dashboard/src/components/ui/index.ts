// Shared UI standard — the one set of primitives every dashboard page uses so
// the whole app looks, reads and operates the same way (section-by-section
// layout with helper text, one sortable/filterable/paginated table, one
// confirm modal). Extracted from the IMG Fastlane reference pattern.
export { Section } from "./Section";
export type { SectionProps } from "./Section";
export { HelperText } from "./HelperText";
export type { HelperTextProps } from "./HelperText";
export { FormField } from "./FormField";
export type { FormFieldProps } from "./FormField";
export { Badge } from "./Badge";
export type { BadgeProps, BadgeTone } from "./Badge";
export { DataTable } from "./DataTable";
export type {
	DataTableProps,
	DataTableColumn,
	DataTableFilter,
} from "./DataTable";
export { ConfirmActionModal } from "./ConfirmActionModal";
export type { ConfirmActionModalProps } from "./ConfirmActionModal";
