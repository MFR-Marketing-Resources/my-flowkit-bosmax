import type {
	ProductCatalogResponse,
	ProductIntelligenceFieldProvenanceListResponse,
	ProductIntelligenceLatestSnapshotResponse,
	ProductIntelligenceSnapshotListResponse,
	ProductIntelligenceSnapshotStatus,
} from "../types";
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

export async function fetchProductIntelligence(
	productId: string,
): Promise<ProductIntelligenceLatestSnapshotResponse> {
	return fetchAPI<ProductIntelligenceLatestSnapshotResponse>(
		`/api/products/${encodeURIComponent(productId)}/intelligence`,
	);
}

export async function fetchProductIntelligenceSnapshots(
	productId: string,
	status?: ProductIntelligenceSnapshotStatus,
): Promise<ProductIntelligenceSnapshotListResponse> {
	const params = new URLSearchParams();
	if (status) params.set("status", status);
	const query = params.size > 0 ? `?${params.toString()}` : "";
	return fetchAPI<ProductIntelligenceSnapshotListResponse>(
		`/api/products/${encodeURIComponent(productId)}/intelligence/snapshots${query}`,
	);
}

export async function fetchProductIntelligenceProvenance(
	snapshotId: string,
	fieldName?: string,
): Promise<ProductIntelligenceFieldProvenanceListResponse> {
	const params = new URLSearchParams();
	if (fieldName) params.set("field_name", fieldName);
	const query = params.size > 0 ? `?${params.toString()}` : "";
	return fetchAPI<ProductIntelligenceFieldProvenanceListResponse>(
		`/api/product-intelligence/snapshots/${encodeURIComponent(snapshotId)}/provenance${query}`,
	);
}
