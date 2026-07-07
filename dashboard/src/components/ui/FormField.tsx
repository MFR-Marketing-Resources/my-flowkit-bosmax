import type { ReactNode } from "react";
import { HelperText } from "./HelperText";

export interface FormFieldProps {
	label: ReactNode;
	/** Helper text under the label — explains the field to the user. */
	helper?: ReactNode;
	/** Mark the field visually required. */
	required?: boolean;
	/** Inline error/warning message under the control. */
	error?: ReactNode;
	/** id of the control this label points at (accessibility). */
	htmlFor?: string;
	className?: string;
	children: ReactNode;
}

/**
 * Standard form field: uppercase label + optional helper + control + optional
 * inline error. One consistent field layout for every form on every page.
 */
export function FormField({
	label,
	helper,
	required,
	error,
	htmlFor,
	className,
	children,
}: FormFieldProps) {
	return (
		<div className={`space-y-1.5${className ? ` ${className}` : ""}`}>
			<label
				htmlFor={htmlFor}
				className="block text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500"
			>
				{label}
				{required && <span className="ml-1 text-amber-400">*</span>}
			</label>
			{helper != null && <HelperText>{helper}</HelperText>}
			{children}
			{error != null && <HelperText tone="warn">{error}</HelperText>}
		</div>
	);
}
