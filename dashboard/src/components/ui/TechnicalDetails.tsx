import { useState, type ReactNode } from "react";
import { ChevronDown, Code2 } from "lucide-react";

export interface TechnicalDetailsProps {
	title?: string;
	children?: ReactNode;
	className?: string;
	testId?: string;
	defaultOpen?: boolean;
}

/**
 * Reusable collapsible container for internal engine metadata, fingerprints,
 * raw digests, and diagnostic traces.
 *
 * Normal operators see only the clean collapsed header ("Technical details").
 * Owners and developers can expand it for deep forensic debugging.
 */
export function TechnicalDetails({
	title = "Technical details",
	children,
	className = "",
	testId = "technical-details",
	defaultOpen = false,
}: TechnicalDetailsProps) {
	const [isOpen, setIsOpen] = useState(defaultOpen);

	if (!children) return null;

	return (
		<details
			data-testid={testId}
			open={isOpen}
			onToggle={(e) => setIsOpen(e.currentTarget.open)}
			className={`group rounded-xl border border-dashed border-slate-800 bg-slate-950/40 text-xs transition-colors ${className}`}
		>
			<summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2 text-[11px] font-semibold text-slate-500 hover:text-slate-300">
				<span className="flex items-center gap-2">
					<Code2 size={13} className="text-slate-600 group-hover:text-slate-400" />
					<span>{title}</span>
				</span>
				<ChevronDown
					size={14}
					className={`text-slate-600 transition-transform duration-150 ${
						isOpen ? "rotate-180" : ""
					}`}
				/>
			</summary>
			<div className="border-t border-slate-800/80 p-3 text-slate-400">
				{children}
			</div>
		</details>
	);
}

export default TechnicalDetails;
