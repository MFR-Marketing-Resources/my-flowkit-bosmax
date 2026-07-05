import type { ProductCatalogResponse } from "../types";
import { fetchAPI } from "./client";

export async function fetchProductCatalog(
	limit = 250,
): Promise<ProductCatalogResponse> {
	return fetchAPI<ProductCatalogResponse>(
		`/api/products?limit=${encodeURIComponent(String(limit))}&offset=0`,
	);
}

/**
 * Server-side product search. Unlike {@link fetchProductCatalog}, this queries
 * the full catalog rather than the first client-loaded page, so canonical
 * products that sit beyond the initial limit window (e.g. MANUAL products that
 * sort after the FastMoss rows) remain discoverable by name.
 */
export async function searchProducts(
	query: string,
	limit = 25,
): Promise<ProductCatalogResponse> {
	return fetchAPI<ProductCatalogResponse>(
		`/api/products/search?q=${encodeURIComponent(query)}&limit=${encodeURIComponent(
			String(limit),
		)}&offset=0`,
	);
}
