import { useEffect, useState } from "react";
import { fetchAPI } from "../../api/client";
import { fetchCreativeAssetEligibilityAudit } from "../../api/creativeAssets";
import VisualAssetPicker from "./VisualAssetPicker";
import type {
	CreativeAsset,
	CreativeAssetEligibilityAuditResponse,
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

export interface RegistryAssetRow {
	code: string;
	label: string;
	assetId: string | null;
}

export function registryRowsForEligibleAssets(
	rows: RegistryAssetRow[],
	assets: CreativeAsset[],
): RegistryAssetRow[] {
	const eligibleIds = new Set(assets.map((asset) => asset.asset_id));
	return rows.filter((row) => row.assetId && eligibleIds.has(row.assetId));
}

const BINDING_AUDIT_REASON_LABELS: Array<{
	key: string;
	label: string;
	className: string;
}> = [
	{
		key: "NOT_APPROVED_FOR_REUSE",
		label: "Pending / rejected",
		className: "border-amber-500/30 bg-amber-500/10 text-amber-200",
	},
	{
		key: "RENDERED_TEXT_NOT_ALLOWED_FOR_VIDEO_FRAME",
		label: "Poster excluded",
		className: "border-rose-500/30 bg-rose-500/10 text-rose-200",
	},
	{
		key: "ENGINE_SLOT_NOT_ALLOWED",
		label: "Wrong slot",
		className: "border-purple-500/30 bg-purple-500/10 text-purple-200",
	},
	{
		key: "MODE_NOT_ALLOWED",
		label: "Wrong mode",
		className: "border-sky-500/30 bg-sky-500/10 text-sky-200",
	},
	{
		key: "SEMANTIC_ROLE_MISMATCH",
		label: "Wrong role",
		className: "border-slate-700 bg-slate-900 text-slate-300",
	},
	{
		key: "ASSET_ARCHIVED",
		label: "Archived",
		className: "border-slate-700 bg-slate-900 text-slate-300",
	},
	{
		key: "PREVIEW_OR_FILE_MISSING",
		label: "Source missing",
		className: "border-red-500/30 bg-red-500/10 text-red-200",
	},
	{
		key: "WRONG_PRODUCT_SCOPED",
		label: "Other product",
		className: "border-orange-500/30 bg-orange-500/10 text-orange-200",
	},
];

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

function filterEligibleForProduct(
	assets: CreativeAsset[],
	productId: string | null,
): { bindable: CreativeAsset[]; otherProductCount: number } {
	if (!productId) return { bindable: assets, otherProductCount: 0 };
	const bindable: CreativeAsset[] = [];
	let otherProductCount = 0;
	for (const asset of assets) {
		if (!asset.product_id || asset.product_id === productId) {
			bindable.push(asset);
		} else {
			otherProductCount += 1;
		}
	}
	return { bindable, otherProductCount };
}

/** Match backend `_asset_has_resolvable_source` — LOCAL_FILE/preview assets
 *  saved via IMG factory base64 path have no 48h `media_id` but are bindable. */
function assetHasResolvableSource(asset: CreativeAsset): boolean {
	return Boolean(
		asset.local_file_path ||
			asset.preview_url ||
			asset.download_url ||
			asset.remote_source_url ||
			asset.media_id,
	);
}

function pickerPlaceholder(
	surface: CreativeAssetEligibilityAuditSurface,
	audit: CreativeAssetEligibilityAuditResponse | null | undefined,
	bindableCount: number,
	error: string | null,
): string {
	if (error) return "API fetch failed — refresh eligibility audit";
	if (!audit) return "Loading eligibility audit…";
	if (bindableCount > 0) {
		if (surface === "HYBRID_START_FRAME_PICKER") {
			return "Automatic product anchor (approved package)";
		}
		if (surface === "F2V_END_FRAME_PICKER") return "No end frame";
		if (surface === "I2V_STYLE_PICKER") return "No style reference";
		return "Select approved reference";
	}
	if (audit.library_total_count === 0) return "No Creative Library assets found";
	if (audit.matching_role_total_count === 0) {
		return "No assets with the required role in Creative Library";
	}
	return "Assets found but none eligible for this surface";
}

function renderSurfaceAuditCard(
	surface: CreativeAssetEligibilityAuditSurface,
	audit: CreativeAssetEligibilityAuditResponse | null | undefined,
	bindableCount: number,
	otherProductCount: number,
	error: string | null,
) {
	if (error) {
		return (
			<div
				data-testid={`binding-audit-${surface}`}
				className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[10px] text-red-200"
			>
				<div className="font-bold uppercase tracking-[0.16em]">{surface.replace(/_/g, " ")} Audit</div>
				<div className="mt-1">API fetch failed: {error}</div>
			</div>
		);
	}
	if (!audit) {
		return (
			<div
				data-testid={`binding-audit-${surface}`}
				className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 text-[10px] text-slate-400"
			>
				<div className="font-bold uppercase tracking-[0.16em]">{surface.replace(/_/g, " ")} Audit</div>
				<div className="mt-1">Loading eligibility audit…</div>
			</div>
		);
	}
	const reviewStatusCounts = audit.review_status_counts ?? {};
	const excludedByReason = audit.excluded_by_reason ?? {};
	const pendingCount = reviewStatusCounts.PENDING_REVIEW ?? 0;
	const chips = BINDING_AUDIT_REASON_LABELS.filter((reason) => {
		if (reason.key === "WRONG_PRODUCT_SCOPED") return otherProductCount > 0;
		return (excludedByReason[reason.key] ?? 0) > 0;
	});
	const summary =
		audit.library_total_count === 0
			? "No Creative Library assets found."
			: bindableCount === 0
				? "Assets found but none are eligible for this surface."
				: `${bindableCount} asset${bindableCount === 1 ? "" : "s"} currently selectable.`;
	return (
		<div
			data-testid={`binding-audit-${surface}`}
			className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 text-[10px] text-slate-300"
		>
			<div className="font-bold uppercase tracking-[0.16em] text-slate-200">
				{surface.replace(/_/g, " ")} Audit
			</div>
			<div className="mt-1">
				Library has {audit.library_total_count} assets; role pool {audit.matching_role_total_count};{" "}
				{bindableCount} bindable here; {audit.excluded_count} excluded by audit
				{otherProductCount > 0 ? `; ${otherProductCount} other-product` : ""}.
			</div>
			<div className="mt-1 text-slate-400">{summary}</div>
			<div className="mt-2 flex flex-wrap gap-1.5">
				<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-amber-200">
					Pending approval {pendingCount}
				</span>
				{chips.map((chip) => (
					<span
						key={chip.key}
						className={`rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] ${chip.className}`}
					>
						{chip.label}{" "}
						{chip.key === "WRONG_PRODUCT_SCOPED"
							? otherProductCount
							: audit.excluded_by_reason[chip.key]}
					</span>
				))}
			</div>
		</div>
	);
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
	const [audits, setAudits] = useState<
		Record<string, CreativeAssetEligibilityAuditResponse | null>
	>({});
	const [otherProductCounts, setOtherProductCounts] = useState<Record<string, number>>({});
	const [avatarRegistryRows, setAvatarRegistryRows] = useState<RegistryAssetRow[]>([]);
	const [sceneRegistryRows, setSceneRegistryRows] = useState<RegistryAssetRow[]>([]);
	const [error, setError] = useState<string | null>(null);
	const surfaces = bindingSurface(mode);

	useEffect(() => {
		if (surfaces.length === 0) {
			onChange(EMPTY_BINDING);
			setAssets({});
			setAudits({});
			setOtherProductCounts({});
			return;
		}
		let active = true;
		setError(null);
		void Promise.all(
			surfaces.map(async (surface) => {
				const result = await fetchCreativeAssetEligibilityAudit({ surface });
				// Product-scoped assets from another product are never bindable
				// (the server rejects WRONG_PRODUCT); global assets stay listed.
				const { bindable, otherProductCount } = filterEligibleForProduct(
					result.eligible_assets,
					productId,
				);
				return [surface, bindable, result, otherProductCount] as const;
			}),
		)
			.then((entries) => {
				if (!active) return;
				setAssets(Object.fromEntries(entries.map(([s, bindable]) => [s, bindable])));
				setAudits(Object.fromEntries(entries.map(([s, , audit]) => [s, audit])));
				setOtherProductCounts(
					Object.fromEntries(entries.map(([s, , , count]) => [s, count])),
				);
			})
			.catch(() => {
				if (active) setError("Eligible reference assets could not be loaded.");
			});
		return () => {
			active = false;
		};
	}, [mode, productId]);

	useEffect(() => {
		if (mode !== "I2V") {
			setAvatarRegistryRows([]);
			setSceneRegistryRows([]);
			return;
		}
		let active = true;
		void Promise.all([
			fetchAPI<{ avatars?: Array<{ avatar_code?: string; character_name?: string; generated_asset_id?: string | null }> }>(
				"/api/workspace/avatar-registry/pool",
			),
			fetchAPI<{ scenes?: Array<{ scene_code?: string; scene_name?: string; generated_asset_id?: string | null }> }>(
				"/api/workspace/scene-context-registry/pool",
			),
		])
			.then(([avatarResponse, sceneResponse]) => {
			if (!active) return;
			setAvatarRegistryRows(
				(avatarResponse.avatars ?? []).map((avatar) => ({
					code: String(avatar.avatar_code ?? "").trim(),
					label: String(avatar.character_name ?? avatar.avatar_code ?? "Avatar").trim(),
					assetId: avatar.generated_asset_id ?? null,
				})),
			);
			setSceneRegistryRows(
				(sceneResponse.scenes ?? []).map((scene) => ({
					code: String(scene.scene_code ?? "").trim(),
					label: String(scene.scene_name ?? scene.scene_code ?? "Scene").trim(),
					assetId: scene.generated_asset_id ?? null,
				})),
			);
			})
			.catch(() => {
				if (!active) return;
				setAvatarRegistryRows([]);
				setSceneRegistryRows([]);
			});
		return () => {
			active = false;
		};
	}, [mode]);

	if (surfaces.length === 0) return null;
	return (
		<div
			data-testid="canonical-reference-binding"
			className="mt-4 rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-3"
		>
			<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-cyan-200">
				Canonical reference binding
			</div>
			<div className="mt-1 text-[11px] text-slate-300">
				Selections are validated and persisted into execution-package asset slots; no browser
				automation is used. Empty pickers show exact eligibility exclusion reasons below.
			</div>
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
					const bindable = assets[surface] ?? [];
					const registryRows =
						surface === "I2V_CHARACTER_PICKER"
							? registryRowsForEligibleAssets(avatarRegistryRows, bindable)
							: surface === "I2V_SCENE_PICKER"
								? registryRowsForEligibleAssets(sceneRegistryRows, bindable)
								: null;
					const pickerLabel =
						surface === "I2V_CHARACTER_PICKER"
							? "Avatar Registry (approved I2V image)"
							: surface === "I2V_SCENE_PICKER"
								? "Scene Registry (approved I2V image)"
								: surface.replace(/_/g, " ");
					const audit = audits[surface];
					const otherProductCount = otherProductCounts[surface] ?? 0;
					const emptyLabel = pickerPlaceholder(
						surface,
						audit,
						bindable.length,
						error,
					);
					return (
						<div key={surface} className="space-y-2">
							<label className="space-y-1 text-xs text-slate-200">
								<span>
									{pickerLabel}
									{required ? " *" : " (optional)"}
								</span>
								{registryRows ? (
									<span
										data-testid={`registry-binding-count-${surface}`}
										className="block text-[10px] text-cyan-200/80"
									>
										{surface === "I2V_CHARACTER_PICKER" ? "Avatar" : "Scene"} Registry:
										 {surface === "I2V_CHARACTER_PICKER"
											? avatarRegistryRows.length
											: sceneRegistryRows.length}{" "}
										rows; {registryRows.length} approved I2V image
										{registryRows.length === 1 ? "" : "s"} available.
									</span>
								) : null}
								<select
									data-testid={`binding-picker-${surface}`}
									value={binding[field] ?? ""}
									onChange={(event) =>
										onChange({ ...binding, [field]: event.target.value || null })
									}
									className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
								>
									<option value="">{emptyLabel}</option>
									{registryRows
										? registryRows.map((row) => (
											<option key={row.code} value={row.assetId ?? ""}>
												{row.label} — {row.code}
											</option>
										))
										: bindable.map((asset) => {
										const resolvable = assetHasResolvableSource(asset);
										return (
											<option
												key={asset.asset_id}
												value={asset.asset_id}
												disabled={!resolvable}
											>
												{asset.display_name}
												{resolvable ? "" : " (no media — not bindable)"}
											</option>
										);
										})}
								</select>
								{registryRows ? <VisualAssetPicker label={pickerLabel} value={binding[field] ?? ""} onChange={(value) => onChange({ ...binding, [field]: value || null })} items={registryRows.map((row) => { const asset = bindable.find((candidate) => candidate.asset_id === row.assetId); return { value: row.assetId ?? "", title: row.label, subtitle: row.code, previewUrl: asset?.preview_url ?? asset?.download_url }; })} /> : null}
							</label>
							{renderSurfaceAuditCard(
								surface,
								audit,
								bindable.length,
								otherProductCount,
								error,
							)}
						</div>
					);
				})}
			</div>
			{error ? <div className="mt-2 text-xs text-rose-300">{error}</div> : null}
		</div>
	);
}
