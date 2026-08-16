import type { Product, ProductVisualReadiness } from '../types';
import type { CohortProduct } from '../api/creativeProduction';

export type ProductVisualStatus =
	| 'OFFICIAL'
	| 'ORIGINAL_FALLBACK'
	| 'COMPATIBILITY_FALLBACK'
	| 'BLOCKED'
	| 'NOT_SELECTED'
	| 'NO_IMAGE';

export interface ResolvedProductVisual {
	displayName: string;
	previewUrl: string | null;
	visualSource: string;
	visualStatus: ProductVisualStatus;
	isOfficial: boolean;
	isFallback: boolean;
	hasVisual: boolean;
}

export type ProductInput =
	| Product
	| CohortProduct
	| Partial<Product>
	| Record<string, unknown>
	| null
	| undefined;

/**
 * Return a browser-safe URL candidate if valid non-empty string with http/path/data scheme.
 */
/**
 * True only for BOSMAX-controlled internal API paths eligible for cache-busting.
 * External http(s) URLs — including signed/query-bearing CDN URLs — must remain
 * byte-for-byte identical to backend authority.
 */
export function isBosmaxInternalPreviewUrl(url: string): boolean {
	const trimmed = String(url || '').trim();
	if (!trimmed) return false;
	// Relative API paths
	if (trimmed.startsWith('/api/product-visual-onboarding/')) return true;
	if (trimmed.startsWith('/api/products/')) return true;
	// Absolute same-origin style API URLs
	try {
		const parsed = new URL(trimmed, 'http://bosmax.internal');
		const path = parsed.pathname || '';
		if (path.startsWith('/api/product-visual-onboarding/')) return true;
		if (path.startsWith('/api/products/')) return true;
	} catch {
		return false;
	}
	return false;
}

/**
 * Append a cache-bust token only to internal BOSMAX preview routes.
 * External URLs are returned unchanged (no ?v= / &v= mutation).
 */
export function withInternalPreviewCacheBust(
	url: string | null | undefined,
	version: string,
): string | null | undefined {
	if (url == null || url === '') return url;
	if (!isBosmaxInternalPreviewUrl(url)) return url;
	const token = encodeURIComponent(String(version ?? ''));
	const sep = url.includes('?') ? '&' : '?';
	return `${url}${sep}v=${token}`;
}

function safeUrl(candidate: unknown): string | null {
	if (!candidate || typeof candidate !== "string") return null;
	const trimmed = candidate.trim();
	if (!trimmed || trimmed.toUpperCase() === "UNKNOWN" || trimmed.toUpperCase() === "NONE") {
		return null;
	}
	if (/^(https?:\/\/|\/|data:)/i.test(trimmed)) {
		return trimmed;
	}
	return null;
}

/**
 * Single shared canonical resolver for product visual presentation across ALL
 * production and workspace surfaces (Video Production, Image Production,
 * Studio, Registries, Catalog).
 *
 * CANONICAL PRECEDENCE CONTRACT:
 *
 * 1. Priority 1 — Persisted OFFICIAL visual:
 *    When backend authority reports current_system_visual.status === 'OFFICIAL'
 *    or active_visual_source starts with APPROVED_:
 *    - Resolves active_cutout_preview_url (or specific approved card preview if active_cutout is missing).
 *    - NEVER falls back to source image when an official cutout exists.
 *
 * 2. Priority 2 — No OFFICIAL visual (or pending candidates):
 *    - When no official selection exists, resolves original_preview_url or original_display_url.
 *    - PENDING candidates (PENDING_REVIEW, NOT_PREPARED, REJECTED, SUPERSEDED) are NEVER promoted to OFFICIAL.
 *
 * 3. Priority 3 — Compatibility fallback:
 *    - If visual_readiness does not provide a usable URL (e.g. legacy/minimal product projection):
 *      a. Verified /api/products/{id}/image if image_readiness_status === 'IMAGE_CACHE_READY'.
 *      b. image_url
 *      c. rendered_img_src
 *      d. image_analysis.image_url
 *
 * Canonical product display name:
 *    product_display_name -> product_short_name -> raw_product_title -> product_name -> ''
 */
export function resolveProductVisualPresentation(
	product: ProductInput,
): ResolvedProductVisual {
	if (!product) {
		return {
			displayName: '',
			previewUrl: null,
			visualSource: 'NONE',
			visualStatus: 'NO_IMAGE',
			isOfficial: false,
			isFallback: false,
			hasVisual: false,
		};
	}

	const anyProduct = product as Record<string, unknown>;
	const productId = String(
		anyProduct.id || anyProduct.product_id || '',
	).trim();
	const displayName = String(
		anyProduct.product_display_name ||
			anyProduct.product_short_name ||
			anyProduct.raw_product_title ||
			anyProduct.product_name ||
			'',
	).trim();

	const readiness = anyProduct.visual_readiness as
		| ProductVisualReadiness
		| undefined;
	const current = readiness?.current_system_visual;
	const activeSource = String(readiness?.active_visual_source || '').trim();
	const isOfficialAuthority =
		current?.status === 'OFFICIAL' || activeSource.startsWith('APPROVED_');

	// Priority 1 — Persisted OFFICIAL Visual
	if (isOfficialAuthority) {
		const activeCutout = safeUrl(readiness?.active_cutout_preview_url);
		const manualCutout = safeUrl(readiness?.manual_cutout_preview_url);
		const autoCutout = safeUrl(readiness?.auto_cutout_preview_url);

		let officialUrl: string | null = activeCutout;
		if (!officialUrl) {
			if (current?.card === 'MANUAL_CUTOUT' && manualCutout) {
				officialUrl = manualCutout;
			} else if (current?.card === 'AUTO_CUTOUT' && autoCutout) {
				officialUrl = autoCutout;
			} else if (manualCutout || autoCutout) {
				officialUrl = manualCutout || autoCutout;
			}
		}

		if (officialUrl) {
			return {
				displayName,
				previewUrl: officialUrl,
				visualSource: activeSource || current?.card || 'OFFICIAL_CUTOUT',
				visualStatus: 'OFFICIAL',
				isOfficial: true,
				isFallback: false,
				hasVisual: true,
			};
		}
	}

	// Priority 2 — Persisted Original Same-Product Fallback
	const originalPreview =
		safeUrl(readiness?.original_preview_url) ||
		safeUrl(readiness?.original_display_url);
	if (originalPreview) {
		return {
			displayName,
			previewUrl: originalPreview,
			visualSource: readiness?.original_display_source || 'ORIGINAL_SOURCE',
			visualStatus: 'ORIGINAL_FALLBACK',
			isOfficial: false,
			isFallback: true,
			hasVisual: true,
		};
	}

	// Priority 3 — Safe Compatibility Fallback
	if (anyProduct.image_readiness_status === 'IMAGE_CACHE_READY' && productId) {
		return {
			displayName,
			previewUrl: '/api/products/' + encodeURIComponent(productId) + '/image',
			visualSource: 'IMAGE_CACHE',
			visualStatus: 'COMPATIBILITY_FALLBACK',
			isOfficial: false,
			isFallback: true,
			hasVisual: true,
		};
	}

	const legacyCandidates = [
		safeUrl(anyProduct.image_url),
		safeUrl(anyProduct.rendered_img_src),
		safeUrl((anyProduct.image_analysis as { image_url?: string } | undefined)?.image_url),
	];

	for (const candidate of legacyCandidates) {
		if (candidate) {
			return {
				displayName,
				previewUrl: candidate,
				visualSource: 'LEGACY_FALLBACK',
				visualStatus: 'COMPATIBILITY_FALLBACK',
				isOfficial: false,
				isFallback: true,
				hasVisual: true,
			};
		}
	}

	return {
		displayName,
		previewUrl: null,
		visualSource: 'NONE',
		visualStatus: 'NO_IMAGE',
		isOfficial: false,
		isFallback: false,
		hasVisual: false,
	};
}

/**
 * Convenience helper returning just the resolved preview URL.
 */
export function resolveProductPreviewUrl(product: ProductInput): string | null {
	return resolveProductVisualPresentation(product).previewUrl;
}

/**
 * Convenience helper returning just the canonical display name.
 */
export function resolveProductDisplayName(product: ProductInput): string {
	return resolveProductVisualPresentation(product).displayName;
}

/**
 * Convenience helper checking whether the product has a resolved OFFICIAL visual.
 */
export function isOfficialProductVisual(product: ProductInput): boolean {
	return resolveProductVisualPresentation(product).isOfficial;
}
