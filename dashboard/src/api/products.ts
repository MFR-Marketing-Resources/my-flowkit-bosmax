import type { ProductCatalogResponse } from "../types";
import { fetchAPI } from "./client";

export async function fetchProductCatalog(
	limit = 250,
): Promise<ProductCatalogResponse> {
	return fetchAPI<ProductCatalogResponse>(
		`/api/products?limit=${encodeURIComponent(String(limit))}&offset=0`,
	);
}
