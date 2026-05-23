import type { ProductAssetGeneratorRequest } from "../../types";

type ProductAssetGeneratorDraft = ProductAssetGeneratorRequest & {
	product_payload_text: string;
};

export type ProductAssetGeneratorPresetDefinition = {
	id: string;
	label: string;
	family: "PRODUCT_ONLY" | "HUMAN_PLUS_PRODUCT" | "PRODUCT_PLUS_SCENE";
	description: string;
	requiredInputs: string[];
	requiresDatabaseProduct: boolean;
	guidance: string;
	draftPatch: Partial<ProductAssetGeneratorDraft>;
};

export const PRODUCT_ASSET_GENERATOR_PRESETS: ProductAssetGeneratorPresetDefinition[] =
	[
		{
			id: "ecommerce_hero_clean_studio",
			label: "Ecommerce Hero / Clean Studio",
			family: "PRODUCT_ONLY",
			description:
				"Clean catalog-first product image lane with label-safe framing and scale truth anchored to the product row.",
			requiredInputs: ["Database product"],
			requiresDatabaseProduct: true,
			guidance:
				"Use the product row so package form, product physics, and scale truth stay locked before prompt preview.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
		{
			id: "ecommerce_hero_soft_shadow",
			label: "Ecommerce Hero / Soft Shadow",
			family: "PRODUCT_ONLY",
			description:
				"Hero product still with softer depth cues while preserving front-label truth and compact commercial framing.",
			requiredInputs: ["Database product"],
			requiresDatabaseProduct: true,
			guidance:
				"Still use database product truth so the model does not hallucinate a larger or smaller pack.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
		{
			id: "product_packshot_front_label",
			label: "Product Packshot / Front Label",
			family: "PRODUCT_ONLY",
			description:
				"Front-facing packshot preset for products that must keep label and silhouette readable in a single frame.",
			requiredInputs: ["Database product"],
			requiresDatabaseProduct: true,
			guidance:
				"Best for label-safe hero output where the product row is the sovereign source of packaging truth.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
		{
			id: "product_flatlay_clean",
			label: "Product Flatlay / Clean",
			family: "PRODUCT_ONLY",
			description:
				"Top-down flatlay preparation lane for product-only compositions and clean merchandising layouts.",
			requiredInputs: ["Database product"],
			requiresDatabaseProduct: true,
			guidance:
				"Use this when you want product-first styling without character interaction but still need size discipline.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
		{
			id: "avatar_holding_product_halfbody",
			label: "Avatar Holding Product / Half Body",
			family: "HUMAN_PLUS_PRODUCT",
			description:
				"Half-body creator lane where scale truth, hand grip, and torso-to-product proportion must stay believable.",
			requiredInputs: ["Database product", "Character reference"],
			requiresDatabaseProduct: true,
			guidance:
				"Product-holding presets require database product truth so physics DNA, grip hints, and scale prompts can lock the object.",
			draftPatch: {
				target_asset_intent: "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: true,
				strict_validation: true,
			},
		},
		{
			id: "avatar_holding_product_closeup",
			label: "Avatar Holding Product / Closeup",
			family: "HUMAN_PLUS_PRODUCT",
			description:
				"Close framing for hand-product interaction where the product must stay readable without inflating the pack.",
			requiredInputs: ["Database product", "Character reference"],
			requiresDatabaseProduct: true,
			guidance:
				"Best when the hand and pack share the frame. Use database product truth before asking the model to scale the hold.",
			draftPatch: {
				target_asset_intent: "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: true,
				strict_validation: true,
			},
		},
		{
			id: "avatar_seated_with_product_tabletop",
			label: "Avatar Seated / Tabletop Product",
			family: "HUMAN_PLUS_PRODUCT",
			description:
				"Tabletop creator composition where the product stays readable on-surface with a visible human anchor.",
			requiredInputs: [
				"Database product",
				"Character reference",
				"Scene reference",
			],
			requiresDatabaseProduct: true,
			guidance:
				"Use this when you want a gentler lifestyle scene but still need product size truth and surface placement discipline.",
			draftPatch: {
				target_asset_intent: "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: true,
				strict_validation: true,
			},
		},
		{
			id: "creator_lifestyle_with_product_scene",
			label: "Creator Lifestyle / Product Scene",
			family: "PRODUCT_PLUS_SCENE",
			description:
				"Blend creator, product, and scene while keeping product truth sovereign over atmosphere and styling.",
			requiredInputs: [
				"Database product",
				"Character reference",
				"Scene reference",
			],
			requiresDatabaseProduct: true,
			guidance:
				"Use product row truth first, then let scene and creator references influence only the surrounding composition.",
			draftPatch: {
				target_asset_intent: "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: true,
				strict_validation: true,
			},
		},
		{
			id: "hand_only_product_hold_macro",
			label: "Hand Only / Product Hold Macro",
			family: "HUMAN_PLUS_PRODUCT",
			description:
				"Macro-style hand focus where grip, label orientation, and object scale are the primary success criteria.",
			requiredInputs: ["Database product"],
			requiresDatabaseProduct: true,
			guidance:
				"Use this when the product must be held but the face is not the main subject. Scale drift is the main failure mode here.",
			draftPatch: {
				target_asset_intent: "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: true,
				strict_validation: true,
			},
		},
		{
			id: "product_on_counter_lifestyle",
			label: "Product On Counter / Lifestyle",
			family: "PRODUCT_PLUS_SCENE",
			description:
				"Scene-led product composition with environment cues while the product remains the visual anchor.",
			requiredInputs: ["Database product", "Scene reference"],
			requiresDatabaseProduct: true,
			guidance:
				"Scene should decorate around the product. Database product truth still governs size, label, and packaging edges.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
		{
			id: "product_on_shelf_lifestyle",
			label: "Product On Shelf / Lifestyle",
			family: "PRODUCT_PLUS_SCENE",
			description:
				"Shelf or rack context preset where the product must stay correctly proportioned relative to its environment.",
			requiredInputs: ["Database product", "Scene reference"],
			requiresDatabaseProduct: true,
			guidance:
				"Use this for contextual merchandising where environment helps mood but must not distort product dimensions.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
		{
			id: "product_scene_style_blend",
			label: "Product + Scene + Style Blend",
			family: "PRODUCT_PLUS_SCENE",
			description:
				"Blend route for product, scene, and style references where the product remains the sovereign anchor and style stays secondary.",
			requiredInputs: [
				"Database product",
				"Scene reference",
				"Style reference",
			],
			requiresDatabaseProduct: true,
			guidance:
				"Use this when you already have scene or style inspiration but do not want the model to mutate the product pack.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
	];

export function getProductAssetGeneratorPreset(
	presetId: string | null,
): ProductAssetGeneratorPresetDefinition | null {
	if (!presetId) {
		return null;
	}
	return (
		PRODUCT_ASSET_GENERATOR_PRESETS.find((preset) => preset.id === presetId) ||
		null
	);
}
