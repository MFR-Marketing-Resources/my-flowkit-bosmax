/**
 * Faceless Video — pure helpers (unit-testable without rendering).
 *
 * Operator surface: Hybrid product path WITHOUT avatar/face.
 * Internal transport: F2V + HYBRID product-anchor (approved package image).
 * Optional Advanced FRAMES override with start frame.
 * No new engine.
 */

import type {
	ApprovedPackageResolvedAsset,
	UploadedAsset,
	WorkspaceExecutionPackage,
} from "../types";

/** Internal only — never operator chrome. */
export const FACELESS_TRANSPORT_MODE = "F2V" as const;
export const FACELESS_SOURCE_MODE = "HYBRID" as const;
export const FACELESS_OVERRIDE_SOURCE_MODE = "FRAMES" as const;
export const FACELESS_CHARACTER_PRESENCE = "FACELESS" as const;

export const FACELESS_VISUAL_LAW =
	"VISUAL LAW (FACELESS): No visible human face and no AI presenter face. " +
	"Hands, arms, and torso may appear with the head and face kept out of frame. " +
	"The person may hold, interact with, demonstrate, or gently move the product. " +
	"Product identity and packaging remain locked and authoritative.";

export type FacelessSceneMode = "SINGLE" | "EXTEND";

export function facelessProductBlocker(
	productId: string | null | undefined,
): string | null {
	if (!String(productId || "").trim()) {
		return "Select a product first.";
	}
	return null;
}

/** Advanced override only. */
export function facelessStartFrameBlocker(
	startFrameAssetId: string | null | undefined,
	referenceOverride = false,
): string | null {
	if (!referenceOverride) return null;
	if (!String(startFrameAssetId || "").trim()) {
		return "Advanced override requires a start-frame asset.";
	}
	return null;
}

export function facelessModelBlocker(
	model: string | null | undefined,
): string | null {
	if (!String(model || "").trim()) return "Select a video model.";
	return null;
}

export function facelessDurationBlocker(
	sceneMode: FacelessSceneMode,
	durationSeconds: number | null | undefined,
	extendTotalSeconds: number | null | undefined,
): string | null {
	if (sceneMode === "SINGLE") {
		if (
			durationSeconds == null ||
			!Number.isFinite(durationSeconds) ||
			durationSeconds <= 0
		) {
			return "Select a clip duration.";
		}
		return null;
	}
	if (
		extendTotalSeconds == null ||
		!Number.isFinite(extendTotalSeconds) ||
		extendTotalSeconds <= 0
	) {
		return "Select an authorized total duration for Extend.";
	}
	return null;
}

export function facelessPrepareBlockers(input: {
	productId: string | null | undefined;
	model: string | null | undefined;
	sceneMode: FacelessSceneMode;
	durationSeconds?: number | null;
	extendTotalSeconds?: number | null;
	/** Advanced only */
	startFrameAssetId?: string | null;
	referenceOverride?: boolean;
}): string[] {
	const out: string[] = [];
	const p = facelessProductBlocker(input.productId);
	if (p) out.push(p);
	const m = facelessModelBlocker(input.model);
	if (m) out.push(m);
	const d = facelessDurationBlocker(
		input.sceneMode,
		input.durationSeconds,
		input.extendTotalSeconds,
	);
	if (d) out.push(d);
	const s = facelessStartFrameBlocker(
		input.startFrameAssetId,
		Boolean(input.referenceOverride),
	);
	if (s) out.push(s);
	return out;
}

export function optionLabel(
	options: Array<{ id: string; label: string }>,
	id: string,
): string {
	return options.find((o) => o.id === id)?.label ?? id;
}

/** Pick resolved package asset for a slot (start_frame / end_frame). */
export function packageSlotResolvedAsset(
	pkg:
		| Pick<WorkspaceExecutionPackage, "asset_slots" | "resolved_assets">
		| null
		| undefined,
	slotKey: string,
): ApprovedPackageResolvedAsset | null {
	if (!pkg) return null;
	const fromSlot = pkg.asset_slots?.find((s) => s.slot_key === slotKey)
		?.resolved_asset;
	if (fromSlot?.asset_id) return fromSlot;
	const fromResolved = pkg.resolved_assets?.find((a) => a.slot_key === slotKey);
	return fromResolved?.asset_id ? fromResolved : null;
}

/** Package resolved asset → one-door startAsset shape. */
export function resolvedAssetToGenerateAsset(
	asset: ApprovedPackageResolvedAsset | null | undefined,
): UploadedAsset | null {
	if (!asset?.asset_id) return null;
	return {
		mediaId: asset.media_id ?? null,
		fileName: asset.file_name || "frame.png",
		label: asset.label || asset.file_name || asset.asset_id,
		previewUrl: asset.preview_url || undefined,
		downloadUrl: asset.download_url || undefined,
		localFilePath: asset.local_file_path ?? undefined,
		assetId: asset.asset_id,
		assetFingerprint: asset.asset_fingerprint,
		assetSource: asset.asset_source,
		isDefaultPackageAsset: true,
		previewRenderableStatus: asset.preview_renderable_status,
		previewErrorDetail: asset.preview_error_detail ?? null,
		localImagePathPresent: Boolean(
			asset.local_image_path_present ?? asset.local_file_path,
		),
		remoteImageUrlPresent: Boolean(
			asset.remote_image_url_present ??
				(asset.download_url || asset.preview_url),
		),
	};
}

export function bindingFallbackGenerateAsset(
	assetId: string | null | undefined,
	label = "start_frame",
): UploadedAsset | null {
	const id = String(assetId || "").trim();
	if (!id) return null;
	return {
		mediaId: null,
		fileName: `${label}.png`,
		label,
		assetId: id,
		assetFingerprint: `binding:${id}`,
		assetSource: "OPERATOR_BINDING",
		isDefaultPackageAsset: false,
	};
}

export function generateAssetHasTransport(
	asset: UploadedAsset | null | undefined,
): boolean {
	if (!asset) return false;
	return Boolean(
		asset.mediaId ||
		asset.localFilePath ||
		asset.downloadUrl ||
		asset.previewUrl,
	);
}

/**
 * Canonical Faceless → POST /api/flow/generate body.
 * startAsset from package product anchor (normal) or Advanced override binding.
 * model + duration_s required (no hardcoded 8).
 */
export function buildFacelessGenerateBody(input: {
	prompt: string;
	productId?: string | null;
	workspacePackage?: WorkspaceExecutionPackage | null;
	startFrameAssetId?: string | null;
	endFrameAssetId?: string | null;
	aspect?: string;
	model: string;
	durationSeconds: number;
	sceneMode?: FacelessSceneMode;
	extendTotalSeconds?: number | null;
	engine?: string;
}): Record<string, unknown> {
	const prompt = String(input.prompt || "").trim();
	if (!prompt) {
		throw new Error("Faceless generate requires package prompt_text.");
	}
	const model = String(input.model || "").trim();
	if (!model) {
		throw new Error("Faceless generate requires a video model.");
	}
	const durationSeconds = Number(input.durationSeconds);
	if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) {
		throw new Error("Faceless generate requires a positive duration_s.");
	}
	if ((input.sceneMode || "SINGLE") === "EXTEND") {
		throw new Error(
			"Faceless EXTEND uses the durable video-job/native-Extend lifecycle; " +
			"do not submit its base clip through /api/flow/generate.",
		);
	}

	const pkg = input.workspacePackage ?? null;
	const startFromPkg = resolvedAssetToGenerateAsset(
		packageSlotResolvedAsset(pkg, "start_frame"),
	);
	const endFromPkg = resolvedAssetToGenerateAsset(
		packageSlotResolvedAsset(pkg, "end_frame"),
	);

	const startAsset =
		startFromPkg ||
		bindingFallbackGenerateAsset(input.startFrameAssetId, "start_frame");
	const endAsset =
		endFromPkg ||
		bindingFallbackGenerateAsset(input.endFrameAssetId, "end_frame");

	if (!generateAssetHasTransport(startAsset)) {
		throw new Error(
			"Faceless generate blocked: product image anchor missing from package. " +
				"Product must be image-ready, or use Advanced reference override.",
		);
	}

	const image_media_ids = [startAsset?.mediaId, endAsset?.mediaId].filter(
		(id): id is string => Boolean(id && String(id).trim()),
	);

	const body: Record<string, unknown> = {
		mode: FACELESS_TRANSPORT_MODE,
		prompt,
		aspect: input.aspect || pkg?.aspect_ratio || "9:16",
		product_id: input.productId ?? pkg?.product_id ?? null,
		source_mode:
			pkg?.source_mode ||
			(input.startFrameAssetId ? FACELESS_OVERRIDE_SOURCE_MODE : FACELESS_SOURCE_MODE),
		model,
		duration_s: durationSeconds,
		generation_mode: "SINGLE",
		engine: input.engine || "GOOGLE_FLOW",
		startAsset,
		image_media_ids,
	};

	if (
		endAsset &&
		generateAssetHasTransport(endAsset) &&
		!endAsset.mediaId &&
		(endAsset.localFilePath || endAsset.downloadUrl || endAsset.previewUrl)
	) {
		body.refs = {
			imageAsset: {
				mediaId: endAsset.mediaId,
				localFilePath: endAsset.localFilePath,
				downloadUrl: endAsset.downloadUrl || endAsset.previewUrl,
				previewUrl: endAsset.previewUrl,
				assetId: endAsset.assetId,
				fileName: endAsset.fileName,
				assetSource: endAsset.assetSource,
			},
		};
	}

	if (pkg?.workspace_execution_package_id) {
		body.workspace_execution_package_id = pkg.workspace_execution_package_id;
	}
	if (pkg?.prompt_fingerprint) {
		body.prompt_fingerprint = pkg.prompt_fingerprint;
	}

	return body;
}
