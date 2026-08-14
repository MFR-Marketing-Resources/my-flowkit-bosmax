import { fetchAPI } from "./client";
import type { CreativeAsset } from "../types";

export interface AvatarRegistryPoolRow {
	avatar_code?: string | null;
	AvatarCode?: string | null;
	character_name?: string | null;
	display_name?: string | null;
	Name?: string | null;
	name?: string | null;
	variant?: string | null;
	Variant?: string | null;
	generated_asset_id?: string | null;
	image_generated?: boolean | null;
}

export function avatarRegistryCode(
	row: AvatarRegistryPoolRow | null | undefined,
): string {
	return String(row?.avatar_code || row?.AvatarCode || "").trim();
}

/** Human-readable registry identity without falling back to `code — code`. */
export function avatarRegistryLabel(
	row: AvatarRegistryPoolRow | null | undefined,
): string {
	const code = avatarRegistryCode(row);
	const name = String(
		row?.character_name ||
			row?.display_name ||
			row?.Name ||
			row?.name ||
			"",
	).trim();
	const variant = String(row?.variant || row?.Variant || "").trim();
	const descriptors = [name, variant].filter(
		(value, index, values) =>
			Boolean(value) &&
			value.toUpperCase() !== code.toUpperCase() &&
			values.findIndex(
				(candidate) => candidate.toUpperCase() === value.toUpperCase(),
			) === index,
	);
	return descriptors.join(" · ") || code || "Avatar";
}

/**
 * Eligibility audits are narrower than the approved registry pool. A generated
 * registry asset therefore falls back to its canonical same-origin preview.
 */
export function avatarRegistryPreviewUrl(
	row: AvatarRegistryPoolRow | null | undefined,
	knownPreviewUrls: Record<string, string>,
): string | null {
	const assetId = String(row?.generated_asset_id || "").trim();
	if (!assetId) return null;
	return (
		knownPreviewUrls[assetId] ||
		`/api/creative-assets/${encodeURIComponent(assetId)}/preview`
	);
}

export function fetchAvatarRegistryPool(): Promise<AvatarRegistryPoolRow[]> {
	return fetchAPI<{ avatars?: AvatarRegistryPoolRow[] }>(
		"/api/workspace/avatar-registry/pool",
	).then((response) => response.avatars ?? []);
}

/** Resolve only canonical AvatarCode values; arbitrary asset labels never pass. */
export function resolveAvatarRegistryCode(
	candidate: string | null | undefined,
	rows: AvatarRegistryPoolRow[],
): string {
	const wanted = String(candidate || "").trim().toUpperCase();
	if (!wanted) return "";
	const match = rows.find(
		(row) => avatarRegistryCode(row).toUpperCase() === wanted,
	);
	return match ? avatarRegistryCode(match) : "";
}

/** Keep recipe presenters inside the approved Avatar Registry authority. */
export function filterRecipesToAvatarRegistry<
	T extends { avatar_code?: string | null },
>(recipes: T[], rows: AvatarRegistryPoolRow[]): T[] {
	const allowed = new Set(
		rows.map((row) => avatarRegistryCode(row).toUpperCase()).filter(Boolean),
	);
	return recipes.filter((recipe) =>
		allowed.has(String(recipe.avatar_code || "").trim().toUpperCase()),
	);
}

/**
 * I2V needs a real, audit-eligible avatar image in addition to a valid registry
 * code. Keep the product recipe order, but exclude presenters whose generated
 * registry image cannot enter the I2V character slot.
 */
export function filterRecipesToEligibleAvatarAssets<
	T extends { avatar_code?: string | null },
>(
	recipes: T[],
	rows: AvatarRegistryPoolRow[],
	eligibleAssetIds: Iterable<string>,
): T[] {
	const eligibleIds = new Set(
		Array.from(eligibleAssetIds, (assetId) => String(assetId).trim()).filter(
			Boolean,
		),
	);
	const eligibleCodes = new Set(
		rows
			.filter((row) =>
				eligibleIds.has(String(row.generated_asset_id || "").trim()),
			)
			.map((row) => avatarRegistryCode(row).toUpperCase())
			.filter(Boolean),
	);
	return filterRecipesToAvatarRegistry(recipes, rows).filter((recipe) =>
		eligibleCodes.has(String(recipe.avatar_code || "").trim().toUpperCase()),
	);
}

/**
 * Convert only approved registry-backed visual assets into IMG picker options.
 * Composite frames and other Creative Library images are deliberately excluded.
 */
export function buildAvatarRegistryReferenceAssets(
	rows: AvatarRegistryPoolRow[],
	assets: CreativeAsset[],
): CreativeAsset[] {
	const assetsById = new Map(assets.map((asset) => [asset.asset_id, asset]));
	const seen = new Set<string>();
	return rows.flatMap((row) => {
		const code = avatarRegistryCode(row);
		const assetId = String(row.generated_asset_id || "").trim();
		const asset = assetId ? assetsById.get(assetId) : undefined;
		if (
			!code ||
			!asset ||
			seen.has(asset.asset_id) ||
			asset.status !== "ACTIVE" ||
			asset.review_status !== "APPROVED"
		) {
			return [];
		}
		seen.add(asset.asset_id);
		const label = avatarRegistryLabel(row);
		return [{ ...asset, display_name: `${label} — ${code}` }];
	});
}
