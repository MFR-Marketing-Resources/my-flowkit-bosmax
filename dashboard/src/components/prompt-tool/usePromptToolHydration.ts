import { useEffect, useMemo, useState } from "react";
import { fetchAssetsByType } from "../../api/assetRegistry";
import { fetchOperatorContentPack } from "../../api/operator";
import { fetchProductCatalog } from "../../api/products";
import type {
	AssetOptionsResponse,
	ContentPackSummary,
	OperatorProduct,
	Product,
} from "../../types";

const REGISTRY_TYPES = [
	"CHARACTER",
	"SCENE_CONTEXT",
	"CAMERA_STYLE",
	"CAMERA_BEHAVIOR",
	"COPYWRITING_FORMULA",
	"LANGUAGE",
	"PLATFORM",
	"ENGINE_PROFILE",
] as const;

type RegistryType = (typeof REGISTRY_TYPES)[number];

type HydrationState = {
	loading: boolean;
	error: string | null;
	products: Product[];
	operatorPack: ContentPackSummary | null;
	assetOptionsByType: Partial<Record<RegistryType, AssetOptionsResponse>>;
};

function normalizeProductKey(value: string | null | undefined): string {
	return (value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function mergeUniqueStrings(
	...groups: Array<Array<string | null | undefined> | undefined>
): string[] {
	const seen = new Set<string>();
	const merged: string[] = [];
	for (const group of groups) {
		for (const raw of group || []) {
			const value = (raw || "").trim();
			if (!value) {
				continue;
			}
			if (seen.has(value)) {
				continue;
			}
			seen.add(value);
			merged.push(value);
		}
	}
	return merged;
}

function buildOperatorProductLookup(
	operatorPack: ContentPackSummary | null,
): Record<string, OperatorProduct> {
	const lookup: Record<string, OperatorProduct> = {};
	for (const product of operatorPack?.products || []) {
		for (const key of [
			product.product_id,
			product.product_name,
			product.raw_product_title,
			product.product_display_name,
			product.product_short_name,
		]) {
			const normalized = normalizeProductKey(key);
			if (normalized && !lookup[normalized]) {
				lookup[normalized] = product;
			}
		}
	}
	return lookup;
}

export function usePromptToolHydration() {
	const [state, setState] = useState<HydrationState>({
		loading: true,
		error: null,
		products: [],
		operatorPack: null,
		assetOptionsByType: {},
	});

	useEffect(() => {
		let cancelled = false;

		async function load() {
			setState((current) => ({ ...current, loading: true, error: null }));

			const results = await Promise.allSettled([
				fetchProductCatalog(),
				fetchOperatorContentPack(),
				...REGISTRY_TYPES.map((assetType) => fetchAssetsByType(assetType)),
			]);

			if (cancelled) {
				return;
			}

			const [productsResult, operatorResult, ...assetResults] = results;
			const errors: string[] = [];
			const nextAssetOptions: Partial<Record<RegistryType, AssetOptionsResponse>> = {};

			const products =
				productsResult.status === "fulfilled"
					? productsResult.value.items
					: [];
			if (productsResult.status === "rejected") {
				errors.push("products");
			}

			const operatorPack =
				operatorResult.status === "fulfilled" ? operatorResult.value : null;
			if (operatorResult.status === "rejected") {
				errors.push("operator-pack");
			}

			assetResults.forEach((result, index) => {
				const assetType = REGISTRY_TYPES[index];
				if (result.status === "fulfilled") {
					nextAssetOptions[assetType] = result.value;
					return;
				}
				errors.push(assetType.toLowerCase());
			});

			setState({
				loading: false,
				error:
					errors.length > 0
						? `Some dropdown sources are unavailable: ${errors.join(", ")}`
						: null,
				products,
				operatorPack,
				assetOptionsByType: nextAssetOptions,
			});
		}

		load();

		return () => {
			cancelled = true;
		};
	}, []);

	return useMemo(() => {
		const productById = Object.fromEntries(
			state.products.map((product) => [product.id, product]),
		) as Record<string, Product>;
		const operatorProductLookup = buildOperatorProductLookup(state.operatorPack);

		const characterOptions = state.assetOptionsByType.CHARACTER?.options || [];
		const sceneContextOptions = mergeUniqueStrings(
			state.assetOptionsByType.SCENE_CONTEXT?.options.map((option) => option.label),
			state.products.map((product) => product.scene_context),
		);
		const cameraStyleOptions = mergeUniqueStrings(
			state.assetOptionsByType.CAMERA_STYLE?.options.map((option) => option.label),
			state.operatorPack?.camera_styles,
			state.products.map((product) => product.camera_style),
		);
		const cameraBehaviorOptions = mergeUniqueStrings(
			state.assetOptionsByType.CAMERA_BEHAVIOR?.options.map((option) => option.label),
			state.products.map((product) => product.camera_behavior),
		);
		const formulaOptions = mergeUniqueStrings(
			state.assetOptionsByType.COPYWRITING_FORMULA?.options.map(
				(option) => option.label,
			),
			state.operatorPack?.formulas,
			state.products.map((product) => product.formula),
		);
		const triggerOptions = mergeUniqueStrings(
			state.operatorPack?.triggers,
			state.products.map((product) => product.trigger_id),
		);
		const siloOptions = mergeUniqueStrings(
			state.operatorPack?.silos,
			state.products.map((product) => product.silo),
		);
		const languageOptions = mergeUniqueStrings(
			state.assetOptionsByType.LANGUAGE?.options.map((option) => option.label),
			state.operatorPack?.language_defaults,
		);
		const platformOptions = mergeUniqueStrings(
			state.assetOptionsByType.PLATFORM?.options.map((option) => option.label),
		);
		const engineOptions = mergeUniqueStrings(
			state.assetOptionsByType.ENGINE_PROFILE?.options.map(
				(option) => option.label,
			),
			state.operatorPack?.engines,
		);
		const headwearOptions = mergeUniqueStrings(state.operatorPack?.headwear_styles);
		const avatarOptions = mergeUniqueStrings(state.operatorPack?.avatars);
		const requestedCharacterOptions = mergeUniqueStrings(
			characterOptions.map((option) => option.label),
		);

		return {
			loading: state.loading,
			error: state.error,
			products: state.products,
			productById,
			operatorPack: state.operatorPack,
			avatarOptions,
			requestedCharacterOptions,
			sceneContextOptions,
			cameraStyleOptions,
			cameraBehaviorOptions,
			formulaOptions,
			triggerOptions,
			siloOptions,
			languageOptions,
			platformOptions,
			engineOptions,
			headwearOptions,
			getOperatorProductFor(productId: string | null | undefined) {
				const product = productId ? productById[productId] : null;
				if (!product) {
					return null;
				}
				for (const key of [
					product.id,
					product.product_display_name,
					product.raw_product_title,
					product.product_short_name,
				]) {
					const normalized = normalizeProductKey(key);
					if (normalized && operatorProductLookup[normalized]) {
						return operatorProductLookup[normalized];
					}
				}
				return null;
			},
		};
	}, [state]);
}