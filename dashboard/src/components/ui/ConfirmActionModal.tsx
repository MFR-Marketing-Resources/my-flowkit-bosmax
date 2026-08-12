import { useEffect, useState } from "react";
import type { ReactNode } from "react";

export interface ConfirmActionModalProps {
	open: boolean;
	title: ReactNode;
	body?: ReactNode;
	/** If set, the user must type this exact phrase to enable Confirm — the
	 * standard gate for destructive actions (product archive/delete). */
	requiredPhrase?: string;
	confirmLabel?: string;
	/** If set, renders a free-text reason box; its value is passed to onConfirm. */
	reasonLabel?: string;
	reasonPlaceholder?: string;
	reasonDefault?: string;
	/** When reasonLabel is set, require a non-empty reason (default true). */
	reasonRequired?: boolean;
	cancelLabel?: string;
	tone?: "danger" | "default";
	busy?: boolean;
	onConfirm: (reason: string) => void;
	onCancel: () => void;
}

/**
 * One confirmation modal for every destructive/irreversible action, with an
 * optional type-to-confirm phrase gate. Consistent so users learn it once.
 */
export function ConfirmActionModal({
	open,
	title,
	body,
	requiredPhrase,
	confirmLabel = "Confirm",
	reasonLabel,
	reasonPlaceholder,
	reasonDefault,
	reasonRequired = true,
	cancelLabel = "Cancel",
	tone = "default",
	busy,
	onConfirm,
	onCancel,
}: ConfirmActionModalProps) {
	const [phrase, setPhrase] = useState("");
	const [reason, setReason] = useState(reasonDefault ?? "");

	// Reset the typed phrase every time the modal (re)opens so a stale value
	// never carries over from a previous confirmation.
	useEffect(() => {
		if (open) {
			setPhrase("");
			setReason(reasonDefault ?? "");
		}
	}, [open]);

	if (!open) return null;

	const phraseOk = !requiredPhrase || phrase.trim() === requiredPhrase;
	const reasonOk = !reasonLabel || !reasonRequired || reason.trim().length > 0;
	const confirmClass =
		tone === "danger" ? "bg-red-600 hover:bg-red-500" : "bg-blue-600 hover:bg-blue-500";

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
			onClick={onCancel}
		>
			<div
				className="w-full max-w-md space-y-4 rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl"
				onClick={(event) => event.stopPropagation()}
			>
				<h3 className="text-sm font-bold text-slate-100">{title}</h3>
				{body != null && <div className="text-xs text-slate-300">{body}</div>}
				{requiredPhrase && (
					<div className="space-y-1.5">
						<p className="text-[10px] text-slate-500">
							Type{" "}
							<span className="font-mono text-amber-300">{requiredPhrase}</span> to
							confirm.
						</p>
						<input
							value={phrase}
							onChange={(event) => setPhrase(event.target.value)}
							placeholder={requiredPhrase}
							className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
						/>
					</div>
				)}
				{reasonLabel && (
					<div className="space-y-1.5">
						<p className="text-[10px] text-slate-500">{reasonLabel}</p>
						<textarea
							value={reason}
							onChange={(event) => setReason(event.target.value)}
							placeholder={reasonPlaceholder}
							rows={2}
							className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
						/>
					</div>
				)}
				<div className="flex justify-end gap-2">
					<button
						type="button"
						onClick={onCancel}
						disabled={busy}
						className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-40"
					>
						{cancelLabel}
					</button>
					<button
						type="button"
						onClick={() => onConfirm(reason.trim())}
						disabled={!phraseOk || !reasonOk || busy}
						className={`rounded-lg px-4 py-2 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-40 ${confirmClass}`}
					>
						{busy ? "…" : confirmLabel}
					</button>
				</div>
			</div>
		</div>
	);
}
