/**
 * Faceless Video — pure helpers (unit-testable without rendering).
 * Image-first single clip via F2V/FRAMES one-door. No new engine.
 */

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
