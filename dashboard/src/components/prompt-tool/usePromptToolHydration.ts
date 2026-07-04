import { useEffect, useMemo, useState } from "react";
import { fetchBosmaxPromptToolContext } from "../../api/bosmaxAuthority";
import { fetchProductCatalog } from "../../api/products";
import type {
	BosmaxAuthorityFallback,
	BosmaxAuthorityOption,
	BosmaxFieldProvenance,
	BosmaxProductContext,
	BosmaxPromptToolContextResponse,
	Product,
} from "../../types";

type HydrationState = {
	loading: boolean;
	error: string | null;
	products: Product[];
	authority: BosmaxPromptToolContextResponse | null;
};

function makeProductStub(context: BosmaxProductContext): Product {
	return {
		id: context.product_id,
		product_id: context.product.product_id || context.product_id,
		source:
			((context.product.source || "IMPORTED") as Product["source"]) ||
			"IMPORTED",
		raw_product_title: context.product.raw_product_title || "",
		product_display_name:
			context.product.product_display_name || context.product_id,
		product_short_name:
			context.product.product_display_name || context.product_id,
		category: context.product.category || null,
		subcategory: context.product.subcategory || null,
		type: context.product.type || null,
		price: null,
		currency: null,
		commission_amount: null,
		commission_rate: null,
		product_type_id: null,
		product_type: context.product.product_type || null,
		silo: context.creative.silo || null,
		trigger_id: context.creative.trigger_id || null,
		formula: context.creative.formula || null,
		copywriting_angle: context.creative.copywriting_angle || null,
		claim_risk_level: context.product.claim_risk_level || null,
		shop_name: null,
		price_min: null,
		price_max: null,
		commission: null,
		image_url: null,
		tiktok_product_url: null,
		fastmoss_source_file: null,
		scene_context: context.visual.scene_context || null,
		camera_style: context.visual.camera_style || null,
		camera_behavior: context.visual.camera_behavior || null,
		handling_notes: context.visual.product_handling || null,
		section_5_product_physics_prompt: context.visual.product_physics || null,
		section_9_overlay_hint: context.visual.overlay_hint || null,
		asset_status: "UNRESOLVED",
		media_id: null,
		local_image_path: null,
		created_at: "",
		updated_at: "",
	};
}

function mergeHydratedProduct(
	repoProduct: Product | undefined,
	context: BosmaxProductContext,
): Product {
	const stub = makeProductStub(context);
	if (!repoProduct) {
		return stub;
	}
	return {
		...repoProduct,
		scene_context: stub.scene_context || repoProduct.scene_context,
		camera_style: stub.camera_style || repoProduct.camera_style,
		camera_behavior: stub.camera_behavior || repoProduct.camera_behavior,
		handling_notes: stub.handling_notes || repoProduct.handling_notes,
		section_5_product_physics_prompt:
			stub.section_5_product_physics_prompt ||
			repoProduct.section_5_product_physics_prompt,
		section_9_overlay_hint:
			stub.section_9_overlay_hint || repoProduct.section_9_overlay_hint,
		product_display_name:
			stub.product_display_name || repoProduct.product_display_name,
		product_short_name:
			stub.product_short_name || repoProduct.product_short_name,
		raw_product_title: stub.raw_product_title || repoProduct.raw_product_title,
		category: stub.category || repoProduct.category,
		subcategory: stub.subcategory || repoProduct.subcategory,
		type: stub.type || repoProduct.type,
		product_type: stub.product_type || repoProduct.product_type,
		trigger_id: stub.trigger_id || repoProduct.trigger_id,
		silo: stub.silo || repoProduct.silo,
		formula: stub.formula || repoProduct.formula,
		copywriting_angle:
			stub.copywriting_angle || repoProduct.copywriting_angle,
		claim_risk_level: stub.claim_risk_level || repoProduct.claim_risk_level,
	};
}

export function usePromptToolHydration() {
	const [state, setState] = useState<HydrationState>({
		loading: true,
		error: null,
		products: [],
		authority: null,
	});

	useEffect(() => {
		let cancelled = false;

		async function load() {
			setState((current) => ({ ...current, loading: true, error: null }));

			const results = await Promise.allSettled([
				fetchBosmaxPromptToolContext(),
				fetchProductCatalog(),
			]);

			if (cancelled) {
				return;
			}

			const [authorityResult, productsResult] = results;
			const errors: string[] = [];
			const authority =
				authorityResult.status === "fulfilled" ? authorityResult.value : null;
			if (authorityResult.status === "rejected") {
				errors.push("bosmax-authority");
			}

			const products =
				productsResult.status === "fulfilled"
					? productsResult.value.items
					: [];
			if (productsResult.status === "rejected") {
				errors.push("products");
			}

			setState({
				loading: false,
				error:
					errors.length > 0
						? `Some dropdown sources are unavailable: ${errors.join(", ")}`
						: null,
				products,
				authority,
			});
		}

		load();

		return () => {
			cancelled = true;
		};
	}, []);

	return useMemo(() => {
		const authorityContexts = state.authority?.product.contexts || [];
		// Build productById from the UNION of catalog products AND authority
		// contexts. Catalog rows seed it so a selected product still resolves when
		// authority context is empty (no more null-silence); authority contexts
		// then overlay/enrich the shared fields where present.
		const productById: Record<string, Product> = {};
		for (const product of state.products) {
			productById[product.id] = product;
		}
		const authorityContextIds = new Set<string>();
		for (const context of authorityContexts) {
			authorityContextIds.add(context.product_id);
			const repoProduct = state.products.find(
				(product) => product.id === context.product_id,
			);
			productById[context.product_id] = mergeHydratedProduct(
				repoProduct,
				context,
			);
		}

		// An EMPTY authority options array must still fall back to catalog products
		// (an empty array is truthy in JS — the old `|| fallback` silently kept the
		// selector empty whenever authority returned zero options).
		const authorityOptions = state.authority?.product.options;
		const productOptions =
			authorityOptions && authorityOptions.length > 0
				? authorityOptions
				: state.products.map((product) => ({
						value: product.id,
						label: `${product.product_display_name} (${product.id})`,
						source_status: "PRODUCT_DERIVED",
						warnings: [],
						metadata: {},
					} as BosmaxAuthorityOption));
		const characterOptions = state.authority?.character.character_options || [];
		const avatarOptions = state.authority?.character.avatar_options || [];
		const headwearOptions = state.authority?.character.headwear_suggestions || [];
		const sceneContextOptions = state.authority?.visual.scene_context_options || [];
		const cameraStyleOptions = state.authority?.visual.camera_style_options || [];
		const cameraBehaviorOptions =
			state.authority?.visual.camera_behavior_options || [];
		const styleReferenceOptions =
			state.authority?.visual.style_reference_options || [];
		const overlayHintOptions =
			state.authority?.visual.overlay_hint_options || [];
		const productHandlingOptions =
			state.authority?.visual.product_handling_options || [];
		const productPhysicsOptions =
			state.authority?.visual.product_physics_options || [];
		const formulaOptions = state.authority?.creative.formula_options || [];
		const triggerOptions = state.authority?.creative.trigger_options || [];
		const siloOptions = state.authority?.creative.silo_options || [];
		const copySignalProducts =
			state.authority?.creative.products_with_copy_signals || [];
		const languageOptions = state.authority?.execution.language_options || [];
		const platformOptions = state.authority?.execution.platform_options || [];
		const engineOptions = state.authority?.execution.engine_options || [];
		const durationOptions = state.authority?.execution.duration_options || [];
		const sourceRouteOptions =
			state.authority?.execution.source_route_options || [];
		const destinationModeOptions =
			state.authority?.execution.destination_mode_options || [];
		const outputTypeOptions =
			state.authority?.execution.output_type_options || [];
		const wardrobeFallback =
			state.authority?.character.wardrobe_fallback ||
			({
				label: "Wardrobe manual fallback",
				reason:
					"Canonical wardrobe registry is not present in this checkout. Manual override remains available.",
				source_status: "NOT_FOUND",
				warnings: ["MANUAL_FALLBACK"],
			} as BosmaxAuthorityFallback);
		const missingSources = state.authority?.provenance.missing_sources || [];
		const sourceMatrix = state.authority?.provenance.source_matrix || [];
		const provenanceWarnings = state.authority?.provenance.warnings || [];

		return {
			loading: state.loading,
			error: state.error,
			products: state.products,
			productById,
			productOptions,
			characterOptions,
			avatarOptions,
			requestedCharacterOptions: characterOptions,
			sceneContextOptions,
			cameraStyleOptions,
			cameraBehaviorOptions,
			styleReferenceOptions,
			overlayHintOptions,
			productHandlingOptions,
			productPhysicsOptions,
			formulaOptions,
			triggerOptions,
			siloOptions,
			languageOptions,
			platformOptions,
			engineOptions,
			durationOptions,
			sourceRouteOptions,
			destinationModeOptions,
			outputTypeOptions,
			headwearOptions,
			wardrobeFallback,
			missingSources,
			sourceMatrix,
			provenanceWarnings,
			copySignalProducts,
			hasAuthorityContext(productId: string | null | undefined) {
				return productId ? authorityContextIds.has(productId) : false;
			},
			getProductContext(productId: string | null | undefined) {
				return productId
					? authorityContexts.find((context) => context.product_id === productId) ||
						null
					: null;
			},
			getCopySignals(productId: string | null | undefined) {
				const option = productId
					? copySignalProducts.find((item) => item.value === productId) || null
					: null;
				return (option?.metadata || {}) as Record<string, string | null | undefined>;
			},
			getFieldWarnings(context: BosmaxProductContext | null): string[] {
				if (!context) {
					return [];
				}
				const warnings = new Set<string>(context.warnings);
				for (const item of context.provenance) {
					for (const warning of item.warnings || []) {
						warnings.add(`${item.field}: ${warning}`);
					}
				}
				return Array.from(warnings);
			},
			getFieldProvenance(context: BosmaxProductContext | null): BosmaxFieldProvenance[] {
				return context?.provenance || [];
			},
		};
	}, [state]);
}
