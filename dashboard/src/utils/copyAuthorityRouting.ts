const LANDBANK_ROUTE = "/creative/storyboard-landbank-v3";
const AUTHORITY_ROUTE = "/creative/copy-authority";

/**
 * Resolve legacy/generic V2 links without making Copy Authority a normal
 * operator surface. Only a complete product + blueprint pair is an exact
 * authority-detail link; every other entry returns to the canonical Landbank.
 */
export function resolveCopyAuthorityRoute(search: string): string {
	const params = new URLSearchParams(search);
	const productId = params.get("product_id")?.trim() ?? "";
	const blueprintId = params.get("blueprint_id")?.trim() ?? "";

	if (productId && blueprintId) {
		return `${AUTHORITY_ROUTE}${search}`;
	}

	params.delete("blueprint_id");
	const query = params.toString();
	return `${LANDBANK_ROUTE}${query ? `?${query}` : ""}`;
}

export function isExactCopyAuthorityRoute(search: string): boolean {
	const params = new URLSearchParams(search);
	return Boolean(params.get("product_id")?.trim() && params.get("blueprint_id")?.trim());
}
