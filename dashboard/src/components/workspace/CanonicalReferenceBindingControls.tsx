import { useEffect, useState } from "react";
import { fetchCreativeAssetEligibilityAudit } from "../../api/creativeAssets";
import type {
	CreativeAsset,
	CreativeAssetEligibilityAuditSurface,
	WorkspaceMode,
} from "../../types";

export interface CanonicalReferenceBinding {
	productReferenceAssetId: string | null;
	startFrameAssetId: string | null;
	endFrameAssetId: string | null;
	characterReferenceAssetId: string | null;
	sceneContextReferenceAssetId: string | null;
	styleReferenceAssetId: string | null;
}

export const EMPTY_BINDING: CanonicalReferenceBinding = {
	productReferenceAssetId: null,
	startFrameAssetId: null,
	endFrameAssetId: null,
	characterReferenceAssetId: null,
	sceneContextReferenceAssetId: null,
	styleReferenceAssetId: null,
};

function bindingSurface(mode: WorkspaceMode): CreativeAssetEligibilityAuditSurface[] {
	if (mode === "HYBRID") return ["HYBRID_START_FRAME_PICKER"];
	if (mode === "F2V") return ["F2V_START_FRAME_PICKER", "F2V_END_FRAME_PICKER"];
	if (mode === "I2V") {
		return ["I2V_CHARACTER_PICKER", "I2V_SCENE_PICKER", "I2V_STYLE_PICKER"];
	}
	return [];
}

function fieldForSurface(surface: CreativeAssetEligibilityAuditSurface): keyof CanonicalReferenceBinding {
	return {
		HYBRID_START_FRAME_PICKER: "productReferenceAssetId",
		HYBRID_END_FRAME_PICKER: "endFrameAssetId",
		F2V_START_FRAME_PICKER: "startFrameAssetId",
		F2V_END_FRAME_PICKER: "endFrameAssetId",
		I2V_CHARACTER_PICKER: "characterReferenceAssetId",
		I2V_SCENE_PICKER: "sceneContextReferenceAssetId",
		I2V_STYLE_PICKER: "styleReferenceAssetId",
	}[surface] as keyof CanonicalReferenceBinding;
}

export default function CanonicalReferenceBindingControls({
	mode,
	productId,
	binding,
	onChange,
}: {
	mode: WorkspaceMode;
	productId: string | null;
	binding: CanonicalReferenceBinding;
	onChange: (next: CanonicalReferenceBinding) => void;
}) {
	const [assets, setAssets] = useState<Record<string, CreativeAsset[]>>({});
	const [error, setError] = useState<string | null>(null);
	const surfaces = bindingSurface(mode);

	useEffect(() => {
		if (surfaces.length === 0) {
			onChange(EMPTY_BINDING);
			setAssets({});
			return;
		}
		let active = true;
		setError(null);
		void Promise.all(
			surfaces.map(async (surface) => {
				const result = await fetchCreativeAssetEligibilityAudit({ surface });
				// Product-scoped assets from another product are never bindable
				// (the server rejects WRONG_PRODUCT); global assets stay listed.
				const eligible = productId
					? result.eligible_assets.filter(
							(asset) => !asset.product_id || asset.product_id === productId,
						)
					: result.eligible_assets;
				return [surface, eligible] as const;
			}),
		)
			.then((entries) => {
				if (active) setAssets(Object.fromEntries(entries));
			})
			.catch(() => {
				if (active) setError("Eligible reference assets could not be loaded.");
			});
		return () => {
			active = false;
		};
	}, [mode, productId]);

	if (surfaces.length === 0) return null;
	return (
		<div data-testid="canonical-reference-binding" className="mt-4 rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-3">
			<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-cyan-200">Canonical reference binding</div>
			<div className="mt-1 text-[11px] text-slate-300">Selections are validated and persisted into execution-package asset slots; no browser automation is used.</div>
			<div className="mt-3 grid gap-3 md:grid-cols-2">
				{surfaces.map((surface) => {
					const field = fieldForSurface(surface);
					// HYBRID: the approved package supplies the product anchor
					// automatically — a manual pick is an OVERRIDE, never mandatory.
					// Style is optional in every current I2V recipe.
					const required =
						surface !== "F2V_END_FRAME_PICKER" &&
						surface !== "HYBRID_START_FRAME_PICKER" &&
						surface !== "I2V_STYLE_PICKER";
					const emptyLabel =
						surface === "HYBRID_START_FRAME_PICKER"
							? "Automatic product anchor (approved package)"
							: surface === "F2V_END_FRAME_PICKER"
								? "No end frame"
								: surface === "I2V_STYLE_PICKER"
									? "No style reference"
									: "Select approved reference";
					return (
						<label key={surface} className="space-y-1 text-xs text-slate-200">
							<span>{surface.replace(/_/g, " ")}{required ? " *" : " (optional)"}</span>
							<select value={binding[field] ?? ""} onChange={(event) => onChange({ ...binding, [field]: event.target.value || null })} className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100">
								<option value="">{emptyLabel}</option>
								{(assets[surface] ?? []).map((asset) => (
									<option key={asset.asset_id} value={asset.asset_id} disabled={!asset.media_id}>
										{asset.display_name}
										{asset.media_id ? "" : " (no media — not bindable)"}
									</option>
								))}
							</select>
						</label>
					);
				})}
			</div>
			{error ? <div className="mt-2 text-xs text-rose-300">{error}</div> : null}
		</div>
	);
}
