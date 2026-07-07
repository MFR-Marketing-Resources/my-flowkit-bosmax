import type { ReactNode } from "react";

export interface HelperTextProps {
	children: ReactNode;
	/** tone tweaks the colour: muted (default), warn (amber), danger (red). */
	tone?: "muted" | "warn" | "danger";
	className?: string;
}

const TONE: Record<NonNullable<HelperTextProps["tone"]>, string> = {
	muted: "text-slate-500",
	warn: "text-amber-300/80",
	danger: "text-red-300/80",
};

/** Small guidance/helper line. Always present so the user is never guessing. */
export function HelperText({
	children,
	tone = "muted",
	className,
}: HelperTextProps) {
	return (
		<p className={`text-[10px] ${TONE[tone]}${className ? ` ${className}` : ""}`}>
			{children}
		</p>
	);
}
