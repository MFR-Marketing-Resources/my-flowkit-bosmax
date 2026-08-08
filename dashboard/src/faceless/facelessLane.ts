/**
 * Faceless Video — pure helpers (unit-testable without rendering).
 *
 * PRODUCT SURFACE (operator-facing):
 *   Product + hands/body product plate → short clip. NO avatar / no face presenter.
 *   Same family as Hybrid product path, without AI presenter identity.
 *
 * ENGINE TRANSPORT (internal, never operator mode chrome):
 *   F2V + FRAMES + character_presence FACELESS on the existing one-door
 *   POST /api/flow/generate. Not a second engine. Not I2V/T2V mode pickers.
 */
import type {
	ApprovedPackageResolvedAsset,
	UploadedAsset,
	WorkspaceExecutionPackage,
} from "../types";

/** Internal one-door job mode — not an operator "F2V vs I2V" product choice. */
export const FACELESS_TRANSPORT_MODE = "F2V" as const;
export const FACELESS_SOURCE_MODE = "FRAMES" as const;
export const FACELESS_CHARACTER_PRESENCE = "FACELESS" as const;

/** Google Flow independent 8s blocks (same route Hybrid EXTEND uses). */
export const FACELESS_EXTEND_ROUTE = "GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS" as const;
export const FACELESS_EXTEND_TOTALS: Record<number, number[]> = {
	16: [8, 8],
	24: [8, 8, 8],
	32: [8, 8, 8, 8],
	48: [8, 8, 8, 8, 8, 8],
	56: [8, 8, 8, 8, 8, 8, 8],
};

export type FacelessSceneMode = "SINGLE" | "EXTEND";

export function facelessStartFrameBlocker(
	startFrameAssetId: string | null | undefined,
): string | null {
	if (!String(startFrameAssetId || "").trim()) {
		return "Faceless requires a product or scene image (hands / body + product, no face) as the start frame.";
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
	sceneMode?: FacelessSceneMode;
	extendTotalSeconds?: number | null;
	model?: string | null;
}): string[] {
	const out: string[] = [];
	const p = facelessProductBlocker(input.productId);
	const s = facelessStartFrameBlocker(input.startFrameAssetId);
	if (p) out.push(p);
	if (s) out.push(s);
	if (!String(input.model || "").trim()) {
		out.push("Select a video model (e.g. Omni Flash or Veo 3.1 - Lite).");
	}
	if (input.sceneMode === "EXTEND") {
		const total = input.extendTotalSeconds;
		if (total == null || !FACELESS_EXTEND_TOTALS[total]) {
			out.push("Extend requires an authorised total duration (e.g. 16s / 24s).");
		}
	}
	return out;
}

export function optionLabel(
	options: Array<{ id: string; label: string }>,
	id: string,
): string {
	return options.find((o) => o.id === id)?.label ?? id;
}

export function facelessExtendPlanSummary(totalSeconds: number): string {
	const plan = FACELESS_EXTEND_TOTALS[totalSeconds];
	if (!plan) return `${totalSeconds}s`;
	return `${totalSeconds}s → ${plan.map((s) => `${s}s`).join(" + ")}`;
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
 * Product surface carries model + duration like Hybrid.
 * MUST also carry startAsset (+ optional image_media_ids). Package id alone
 * does NOT transport the frame to make_video.
 *
 * `mode: F2V` here is internal transport only — not operator product mode chrome.
 */
export function buildFacelessGenerateBody(input: {
	prompt: string;
	productId?: string | null;
	workspacePackage?: WorkspaceExecutionPackage | null;
	/** Operator binding — used if package slot missing. */
	startFrameAssetId?: string | null;
	endFrameAssetId?: string | null;
	aspect?: string;
	/** ui_label e.g. "Veo 3.1 - Lite" | "Omni Flash" */
	model?: string | null;
	/** SINGLE block seconds, or first EXTEND block (usually 8). */
	durationSeconds?: number | null;
	sceneMode?: FacelessSceneMode;
	extendTotalSeconds?: number | null;
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

	const model =
		String(input.model || pkg?.model || "").trim() || "Veo 3.1 - Lite";
	const sceneMode = input.sceneMode || "SINGLE";
	let duration_s =
		input.durationSeconds != null
			? Number(input.durationSeconds)
			: Number(pkg?.duration_seconds || 8);
	if (sceneMode === "EXTEND") {
		// First independent block; remaining blocks are Flow extend path.
		duration_s = 8;
	}

	const body: Record<string, unknown> = {
		// Internal one-door transport (not operator F2V/I2V product chrome).
		mode: FACELESS_TRANSPORT_MODE,
		prompt,
		aspect: input.aspect || pkg?.aspect_ratio || "9:16",
		product_id: input.productId ?? pkg?.product_id ?? null,
		model,
		duration_s,
		startAsset,
		image_media_ids,
	};

	if (sceneMode === "EXTEND" && input.extendTotalSeconds != null) {
		body.generation_mode = "EXTEND";
		body.requested_total_duration_seconds = input.extendTotalSeconds;
		body.extend_route = FACELESS_EXTEND_ROUTE;
	} else {
		body.generation_mode = "SINGLE";
	}

	// End frame without mediaId: transport via refs.imageAsset.
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

	// Lineage only — NOT a substitute for startAsset.
	if (pkg?.workspace_execution_package_id) {
		body.workspace_execution_package_id = pkg.workspace_execution_package_id;
	}
	if (pkg?.prompt_fingerprint) {
		body.prompt_fingerprint = pkg.prompt_fingerprint;
	}

	return body;
}
