import { describe, expect, it } from 'vitest';
import {
	isBosmaxInternalPreviewUrl,
	isOfficialProductVisual,
	resolveProductDisplayName,
	resolveProductPreviewUrl,
	resolveProductVisualPresentation,
	withInternalPreviewCacheBust,
} from './productVisualPresentation';
import type { Product } from '../types';

describe('productVisualPresentation canonical resolver', () => {
	// CASE A: Approved Manual / Canva OFFICIAL
	it('CASE A: resolves approved manual/canva official cutout when current_system_visual is OFFICIAL', () => {
		const product = {
			id: 'prod-001',
			raw_product_title: 'Minyak Warisan Cap Burung 25ml',
			product_display_name: 'Minyak Warisan Cap Burung 25ml (Official)',
			image_url: 'https://example.com/source-photo.jpg',
			visual_readiness: {
				product_id: 'prod-001',
				current_system_visual: {
					status: 'OFFICIAL',
					card: 'MANUAL_CUTOUT',
					label: 'Manual / Canva Cutout',
				},
				active_visual_source: 'APPROVED_MANUAL_CANONICAL_CUTOUT',
				active_cutout_preview_url: '/api/product-visual-onboarding/prod-001/cutout/preview/active',
				manual_cutout_preview_url: '/api/product-visual-onboarding/prod-001/cutout/preview/manual',
				original_preview_url: '/api/product-visual-onboarding/prod-001/cutout/preview/original',
				original_display_url: 'https://example.com/source-photo.jpg',
			},
		} as unknown as Product;

		const result = resolveProductVisualPresentation(product);

		expect(result.previewUrl).toBe('/api/product-visual-onboarding/prod-001/cutout/preview/active');
		expect(result.isOfficial).toBe(true);
		expect(result.visualStatus).toBe('OFFICIAL');
		expect(result.displayName).toBe('Minyak Warisan Cap Burung 25ml (Official)');
		expect(resolveProductPreviewUrl(product)).toBe('/api/product-visual-onboarding/prod-001/cutout/preview/active');
		expect(isOfficialProductVisual(product)).toBe(true);
	});

	// CASE B: Approved Auto OFFICIAL
	it('CASE B: resolves approved auto cutout when active_visual_source starts with APPROVED_AUTO', () => {
		const product = {
			id: 'prod-002',
			raw_product_title: 'Habatus Sauda Oil 50ml',
			image_url: 'https://example.com/source-auto.jpg',
			visual_readiness: {
				product_id: 'prod-002',
				current_system_visual: {
					status: 'OFFICIAL',
					card: 'AUTO_CUTOUT',
					label: 'Auto Cutout',
				},
				active_visual_source: 'APPROVED_AUTO_CANONICAL_CUTOUT',
				active_cutout_preview_url: '/api/product-visual-onboarding/prod-002/cutout/preview/active',
				auto_cutout_preview_url: '/api/product-visual-onboarding/prod-002/cutout/preview/auto',
				original_preview_url: '/api/product-visual-onboarding/prod-002/cutout/preview/original',
			},
		} as unknown as Product;

		const result = resolveProductVisualPresentation(product);

		expect(result.previewUrl).toBe('/api/product-visual-onboarding/prod-002/cutout/preview/active');
		expect(result.isOfficial).toBe(true);
		expect(result.visualStatus).toBe('OFFICIAL');
		expect(result.displayName).toBe('Habatus Sauda Oil 50ml');
	});

	// CASE C: Pending Manual candidate
	it('CASE C: falls back to original source when manual cutout is PENDING_REVIEW and not OFFICIAL', () => {
		const product = {
			id: 'prod-003',
			raw_product_title: 'Minyak Urut Moden',
			image_url: 'https://example.com/source-orig.jpg',
			visual_readiness: {
				product_id: 'prod-003',
				cutout_status: 'PENDING_REVIEW',
				current_system_visual: {
					status: 'ORIGINAL_FALLBACK',
					card: 'ORIGINAL_SOURCE',
					label: 'Original Source',
				},
				active_visual_source: 'SAME_PRODUCT_TRUSTED_SOURCE',
				manual_cutout_preview_url: '/api/product-visual-onboarding/prod-003/cutout/preview/manual',
				original_preview_url: '/api/product-visual-onboarding/prod-003/cutout/preview/original',
				original_display_url: 'https://example.com/source-orig.jpg',
			},
		} as unknown as Product;

		const result = resolveProductVisualPresentation(product);

		expect(result.previewUrl).toBe('/api/product-visual-onboarding/prod-003/cutout/preview/original');
		expect(result.isOfficial).toBe(false);
		expect(result.isFallback).toBe(true);
		expect(result.visualStatus).toBe('ORIGINAL_FALLBACK');
	});

	// CASE D: Pending Auto candidate
	it('CASE D: falls back to original source when auto candidate is preparing or pending review', () => {
		const product = {
			id: 'prod-004',
			raw_product_title: 'Jus Herba Tradisional',
			image_url: 'https://example.com/jus-source.jpg',
			visual_readiness: {
				product_id: 'prod-004',
				auto_cutout_status: 'PENDING_REVIEW',
				current_system_visual: {
					status: 'ORIGINAL_FALLBACK',
					card: 'ORIGINAL_SOURCE',
					label: 'Original Source',
				},
				active_visual_source: 'SAME_PRODUCT_TRUSTED_SOURCE',
				auto_cutout_preview_url: '/api/product-visual-onboarding/prod-004/cutout/preview/auto',
				original_display_url: 'https://example.com/jus-source.jpg',
			},
		} as unknown as Product;

		const result = resolveProductVisualPresentation(product);

		expect(result.previewUrl).toBe('https://example.com/jus-source.jpg');
		expect(result.isOfficial).toBe(false);
		expect(result.visualStatus).toBe('ORIGINAL_FALLBACK');
	});

	// CASE E: No configured cutout / NOT_PREPARED
	it('CASE E: falls back to original source when cutout is NOT_PREPARED', () => {
		const product = {
			id: 'prod-005',
			raw_product_title: 'Kopi Herba Warisan',
			image_url: 'https://example.com/kopi.jpg',
			visual_readiness: {
				product_id: 'prod-005',
				cutout_status: 'NOT_PREPARED',
				current_system_visual: {
					status: 'ORIGINAL_FALLBACK',
					card: 'ORIGINAL_SOURCE',
					label: 'Original Source',
				},
				active_visual_source: 'SAME_PRODUCT_TRUSTED_SOURCE',
				original_preview_url: '/api/product-visual-onboarding/prod-005/cutout/preview/original',
			},
		} as unknown as Product;

		const result = resolveProductVisualPresentation(product);

		expect(result.previewUrl).toBe('/api/product-visual-onboarding/prod-005/cutout/preview/original');
		expect(result.isOfficial).toBe(false);
		expect(result.visualStatus).toBe('ORIGINAL_FALLBACK');
	});

	// CASE F: Legacy product without visual_readiness
	it('CASE F1: resolves cached endpoint when image_readiness_status is IMAGE_CACHE_READY and no visual_readiness', () => {
		const product = {
			id: 'prod-legacy-1',
			raw_product_title: 'Legacy Product Cached',
			image_readiness_status: 'IMAGE_CACHE_READY',
			image_url: 'https://example.com/remote.jpg',
		} as unknown as Product;

		const result = resolveProductVisualPresentation(product);

		expect(result.previewUrl).toBe('/api/products/prod-legacy-1/image');
		expect(result.isOfficial).toBe(false);
		expect(result.visualStatus).toBe('COMPATIBILITY_FALLBACK');
	});

	it('CASE F2: resolves remote image_url when image is not cached and no visual_readiness', () => {
		const product = {
			id: 'prod-legacy-2',
			raw_product_title: 'Legacy Product Remote',
			image_url: 'https://example.com/remote-only.jpg',
		} as unknown as Product;

		const result = resolveProductVisualPresentation(product);

		expect(result.previewUrl).toBe('https://example.com/remote-only.jpg');
		expect(result.isOfficial).toBe(false);
		expect(result.visualStatus).toBe('COMPATIBILITY_FALLBACK');
	});

	it('CASE F3: resolves image_analysis.image_url when image_url is missing', () => {
		const product = {
			id: 'prod-legacy-3',
			raw_product_title: 'Legacy Product Analysis',
			image_analysis: {
				image_url: 'https://example.com/analysis.jpg',
			},
		} as unknown as Product;

		const result = resolveProductVisualPresentation(product);

		expect(result.previewUrl).toBe('https://example.com/analysis.jpg');
		expect(result.isOfficial).toBe(false);
	});

	it('CASE F4: returns null when product has no visual fields at all', () => {
		const product = {
			id: 'prod-empty',
			raw_product_title: 'Empty Visual Product',
		} as unknown as Product;

		const result = resolveProductVisualPresentation(product);

		expect(result.previewUrl).toBeNull();
		expect(result.hasVisual).toBe(false);
		expect(result.visualStatus).toBe('NO_IMAGE');
	});

	it('handles null and undefined safely', () => {
		expect(resolveProductVisualPresentation(null)).toEqual({
			displayName: '',
			previewUrl: null,
			visualSource: 'NONE',
			visualStatus: 'NO_IMAGE',
			isOfficial: false,
			isFallback: false,
			hasVisual: false,
		});

		expect(resolveProductVisualPresentation(undefined)).toEqual({
			displayName: '',
			previewUrl: null,
			visualSource: 'NONE',
			visualStatus: 'NO_IMAGE',
			isOfficial: false,
			isFallback: false,
			hasVisual: false,
		});
	});

	it('resolves canonical display name precedence correctly', () => {
		expect(
			resolveProductDisplayName({
				product_display_name: 'Custom Display Name',
				product_short_name: 'Short Name',
				raw_product_title: 'Raw Title',
			} as unknown as Product),
		).toBe('Custom Display Name');

		expect(
			resolveProductDisplayName({
				product_short_name: 'Short Name',
				raw_product_title: 'Raw Title',
			} as unknown as Product),
		).toBe('Short Name');

		expect(
			resolveProductDisplayName({
				raw_product_title: 'Raw Title',
			} as unknown as Product),
		).toBe('Raw Title');

		expect(
			resolveProductDisplayName({
				product_name: 'Cohort Product Name',
			} as unknown as Product),
		).toBe('Cohort Product Name');
	});
});


describe('internal preview cache-bust contract', () => {
	it('cache-busts internal BOSMAX preview paths', () => {
		const internal = '/api/product-visual-onboarding/p1/cutout/preview/original';
		expect(isBosmaxInternalPreviewUrl(internal)).toBe(true);
		expect(withInternalPreviewCacheBust(internal, '123')).toBe(
			'/api/product-visual-onboarding/p1/cutout/preview/original?v=123',
		);
		expect(
			withInternalPreviewCacheBust('/api/products/p1/image', 'abc'),
		).toBe('/api/products/p1/image?v=abc');
	});

	it('leaves absolute external HTTPS URLs byte-for-byte unchanged', () => {
		const external = 'https://cdn.example.com/image.jpg';
		expect(isBosmaxInternalPreviewUrl(external)).toBe(false);
		expect(withInternalPreviewCacheBust(external, '999')).toBe(external);
	});

	it('leaves signed external URLs with query strings unchanged', () => {
		const signed = 'https://cdn.example.com/image.jpg?signature=ABC&expires=123';
		expect(withInternalPreviewCacheBust(signed, 'bust-me')).toBe(signed);
	});
});
