/**
 * Faceless Video — pure helpers (unit-testable without rendering).
 * Image-first single clip via F2V/FRAMES one-door. No new engine.
 */

import type {
	ApprovedPackageResolvedAsset,
	UploadedAsset,
	WorkspaceExecutionPackage,
} from "../types";

export const FACELESS_TRANSPORT_MODE = "F2V" as const;
export const FACELESS_SOURCE_MODE = "FRAMES" as const;
export const FACELESS_CHARACTER_PRESENCE = "FACELESS" as const;

export function facelessStartFrameBlocker(
	startFrameAssetId: string | null | undefined,
): string | null {
	if (!String(startFrameAssetId || "").trim()) {
		return "Faceless requires a product or scene image as the start frame before prepare/generate.";
	}
	return null;
}

export function facelessProductBlocker(
	productId: string | null | undefined,
): string | null {
	if (!String(productId || "").trim()) {
		return "Select a product first.";
	}
	return null;
}

export function facelessPrepareBlockers(input: {
	productId: string | null | undefined;
	startFrameAssetId: string | null | undefined;
}): string[] {
	const out: string[] = [];
	const p = facelessProductBlocker(input.productId);
	const s = facelessStartFrameBlocker(input.startFrameAssetId);
	if (p) out.push(p);
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

/**
 * Minimal startAsset when package slots are thin but operator binding has asset id.
 * Prefer package-resolved payloads (media / path / url).
 */
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
			asset.previewUrl ||
			asset.assetId,
	);
}

/**
 * Canonical Faceless → POST /api/flow/generate body.
 *
 * MUST carry startAsset (+ optional image_media_ids) on the existing one-door
 * contract. Package id alone does NOT transport the frame to make_video.
 */
export function buildFacelessGenerateBody(input: {
	prompt: string;
	productId?: string | null;
	workspacePackage?: WorkspaceExecutionPackage | null;
	/** Operator binding — used if package slot missing. */
	startFrameAssetId?: string | null;
	endFrameAssetId?: string | null;
	aspect?: string;
}): Record<string, unknown> {
	const prompt = String(input.prompt || "").trim();
	if (!prompt) {
		throw new Error("Faceless generate requires package prompt_text.");
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
			"Faceless generate blocked: start frame reference missing from package and binding.",
		);
	}

	const image_media_ids = [startAsset?.mediaId, endAsset?.mediaId].filter(
		(id): id is string => Boolean(id && String(id).trim()),
	);

	const body: Record<string, unknown> = {
		mode: FACELESS_TRANSPORT_MODE,
		prompt,
		// GenerateRequest field is `aspect`, not aspectRatio.
		aspect: input.aspect || pkg?.aspect_ratio || "9:16",
		product_id: input.productId ?? pkg?.product_id ?? null,
		// Primary F2V reference path used by ordered_ref_slots → resolve → start_generate.
		startAsset,
		// Explicit media ids when already live (OperatorPage parity).
		image_media_ids,
	};

	// End frame without mediaId: GenerateRequest has no endAsset field on this
	// one-door path — transport via refs.imageAsset (ordered after start).
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

	// Lineage only — NOT a substitute for startAsset (Pydantic may strip unknowns).
	if (pkg?.workspace_execution_package_id) {
		body.workspace_execution_package_id = pkg.workspace_execution_package_id;
	}
	if (pkg?.prompt_fingerprint) {
		body.prompt_fingerprint = pkg.prompt_fingerprint;
	}

	return body;
}
