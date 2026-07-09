import { useEffect, useState } from "react";
import { updateCreativeAsset } from "../../api/creativeAssets";
import type { CreativeAsset } from "../../types";

// The truth/safety gates the operator must explicitly attest before an asset can be
// APPROVED for reuse. This is the SAME gate the backend enforces
// (APPROVAL_REQUIRES_ALL_TRUTH_PASS) — the modal is the explicit, human,
// per-gate attestation path that lets a legitimate reviewer set them to PASS.
// No silent auto-approval: every gate must be checked, and a gate already marked
// FAIL cannot be attested away here.
const GATES = [
	{
		key: "identity",
		label: "Identity lock verified",
		hint: "Product / character identity is correct and not drifted.",
		get: (a: CreativeAsset) => a.identity_lock_status,
	},
	{
		key: "scale",
		label: "Scale truth verified",
		hint: "Product scale is truthful (not over/under-scaled).",
		get: (a: CreativeAsset) => a.scale_truth_status,
	},
	{
		key: "claim",
		label: "Claim safety verified",
		hint: "No unsafe / overstated product claims.",
		get: (a: CreativeAsset) => a.claim_safety_status,
	},
] as const;

function statusLabel(value: string | null | undefined): string {
	return value && value.trim() ? value : "UNVERIFIED";
}

export interface ApproveAssetModalProps {
	asset: CreativeAsset | null;
	open: boolean;
	onCancel: () => void;
	/** Called with the updated (APPROVED) asset after a successful attestation. */
	onApproved: (updated: CreativeAsset) => void;
}

/**
 * One shared, explicit truth/safety attestation dialog for approving a Creative
 * Library asset for reuse. Used by every approve surface (Creative Library, IMG
 * Fastlane, IMG Cockpit) so approval is governed and consistent everywhere.
 * Approval means "approved for reuse" — it does NOT by itself make an asset F2V
 * eligible (role/mode/slot/rendered-text/source/resolver gates still apply).
 */
export default function ApproveAssetModal({
	asset,
	open,
	onCancel,
	onApproved,
}: ApproveAssetModalProps) {
	const [checked, setChecked] = useState<Record<string, boolean>>({});
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);

	// Reset the attestation every time the dialog (re)opens or the target changes so
	// a stale tick never carries over to a different asset.
	useEffect(() => {
		if (open) {
			setChecked({});
			setBusy(false);
			setError(null);
		}
	}, [open, asset?.asset_id]);

	if (!open || !asset) return null;

	const failedGate = GATES.find((g) => (g.get(asset) ?? "") === "FAIL");
	const allChecked = GATES.every((g) => checked[g.key]);
	const canConfirm = allChecked && !failedGate && !busy;

	const confirm = async () => {
		setBusy(true);
		setError(null);
		try {
			const updated = await updateCreativeAsset(asset.asset_id, {
				review_status: "APPROVED",
				identity_lock_status: "PASS",
				scale_truth_status: "PASS",
				claim_safety_status: "PASS",
			});
			onApproved(updated);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to approve asset.",
			);
		} finally {
			setBusy(false);
		}
	};

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
			onClick={onCancel}
		>
			<div
				className="w-full max-w-md space-y-4 rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl"
				onClick={(event) => event.stopPropagation()}
			>
				<div>
					<h3 className="text-sm font-bold text-slate-100">
						Approve asset for reuse
					</h3>
					<p className="mt-1 text-xs text-slate-400">
						Attest the truth/safety gates for{" "}
						<strong className="text-slate-200">{asset.display_name}</strong>. The
						backend blocks approval unless every gate is verified
						(APPROVAL_REQUIRES_ALL_TRUTH_PASS).
					</p>
				</div>

				{failedGate ? (
					<div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
						This asset has a failed gate ({failedGate.label}). Resolve it before
						approving — it cannot be attested here.
					</div>
				) : null}

				<div className="space-y-2">
					{GATES.map((gate) => (
						<label
							key={gate.key}
							className="flex cursor-pointer items-start gap-2 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2"
						>
							<input
								type="checkbox"
								checked={Boolean(checked[gate.key])}
								disabled={Boolean(failedGate) || busy}
								onChange={(event) =>
									setChecked((prev) => ({
										...prev,
										[gate.key]: event.target.checked,
									}))
								}
								className="mt-0.5"
							/>
							<span className="text-[11px] text-slate-200">
								<span className="font-semibold">{gate.label}</span>
								<span className="ml-1 rounded-full border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[9px] uppercase tracking-[0.14em] text-slate-400">
									now: {statusLabel(gate.get(asset))}
								</span>
								<span className="mt-0.5 block text-[10px] text-slate-500">
									{gate.hint}
								</span>
							</span>
						</label>
					))}
				</div>

				<p className="text-[10px] text-slate-500">
					Approval marks this asset APPROVED for reuse. It does not by itself make
					it F2V eligible — role, mode, engine slot, rendered-text and source
					gates still apply in the F2V resolver.
				</p>

				{error ? (
					<div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
						{error}
					</div>
				) : null}

				<div className="flex justify-end gap-2">
					<button
						type="button"
						onClick={onCancel}
						disabled={busy}
						className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-40"
					>
						Cancel
					</button>
					<button
						type="button"
						onClick={() => void confirm()}
						disabled={!canConfirm}
						className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
					>
						{busy ? "…" : "Attest & Approve"}
					</button>
				</div>
			</div>
		</div>
	);
}
