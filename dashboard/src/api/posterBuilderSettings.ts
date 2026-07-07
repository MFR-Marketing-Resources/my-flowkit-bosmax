// Poster / Creative Cockpit builder-settings SSOT (read-only), mirroring the
// imageGenSettings.ts convention: interface + *_FALLBACK const + fetchX() + useX().
//
// The FALLBACK holds the same seeded option lists as the backend so the Poster
// Builder dropdowns and the Cockpit page keep working even against an older /
// stale agent that does not yet expose GET /api/poster/builder-settings.
import { useEffect, useState } from "react";
import { getAPI } from "./client";

export interface PosterSettingOption {
	id: string;
	label: string;
	description?: string;
	default?: boolean;
}

export interface PosterFlowMirrorImageModel {
	key: string;
	label: string;
	pending: boolean;
}

export interface PosterFlowMirrorSettingsSSOT {
	aspect_ratios: string[];
	counts: number[];
	image_models: PosterFlowMirrorImageModel[];
	defaults: { aspect_ratio: string; count: number; image_model: string };
	source: string;
}

export interface PosterCopyComponentsStatus {
	routes: string[];
	copy_sets_scope: string;
	copy_sets_endpoint: string;
	landbank_products: number;
	source: string;
}

export interface PosterAIProviderStatus {
	lane: string;
	configured: boolean;
	status: string;
	provider_id?: string | null;
	model_id?: string | null;
	execution_enabled: boolean;
	source: string;
}

export interface PosterBuilderSettings {
	poster_objectives: PosterSettingOption[];
	poster_types: PosterSettingOption[];
	languages: PosterSettingOption[];
	visual_routes: PosterSettingOption[];
	human_presence_modes: PosterSettingOption[];
	text_density_options: PosterSettingOption[];
	flow_mirror: PosterFlowMirrorSettingsSSOT;
	copy_components: PosterCopyComponentsStatus;
	ai_provider: PosterAIProviderStatus;
	sources: Record<string, string>;
}

export const POSTER_BUILDER_SETTINGS_FALLBACK: PosterBuilderSettings = {
	poster_objectives: [
		{ id: "Product awareness", label: "Product awareness", default: true },
		{ id: "Sales conversion", label: "Sales conversion" },
		{ id: "Education / how-to", label: "Education / how-to" },
		{ id: "Trust & credibility", label: "Trust & credibility" },
		{ id: "Promo / offer", label: "Promo / offer" },
	],
	poster_types: [
		{ id: "Product-only hero poster", label: "Product-only hero poster", default: true },
		{ id: "Lifestyle in-use", label: "Lifestyle in-use" },
		{ id: "Benefit callout", label: "Benefit callout" },
		{ id: "Promo / price", label: "Promo / price" },
		{ id: "Comparison", label: "Comparison" },
	],
	languages: [
		{ id: "ms", label: "Malay", default: true },
		{ id: "en", label: "English" },
		{ id: "zh", label: "Chinese" },
		{ id: "ta", label: "Tamil" },
	],
	visual_routes: [
		{ id: "Premium commercial", label: "Premium commercial", default: true },
		{ id: "UGC authentic", label: "UGC authentic" },
		{ id: "Clean studio", label: "Clean studio" },
		{ id: "Lifestyle editorial", label: "Lifestyle editorial" },
	],
	human_presence_modes: [
		{ id: "No human / product-forward", label: "No human / product-forward", default: true },
		{ id: "Hands only", label: "Hands only" },
		{ id: "Faceless model", label: "Faceless model" },
		{ id: "Full model / creator", label: "Full model / creator" },
	],
	text_density_options: [
		{ id: "low", label: "Low" },
		{ id: "medium", label: "Medium", default: true },
		{ id: "high", label: "High" },
	],
	flow_mirror: {
		aspect_ratios: ["9:16", "1:1", "16:9", "4:3", "3:4"],
		counts: [1, 2, 3, 4],
		image_models: [
			{ key: "NANO_BANANA_PRO", label: "Nano Banana Pro", pending: false },
			{ key: "NANO_BANANA_2", label: "Nano Banana 2", pending: false },
			{ key: "NANO_BANANA_2_LITE", label: "Nano Banana 2 Lite", pending: true },
		],
		defaults: { aspect_ratio: "9:16", count: 1, image_model: "Nano Banana 2" },
		source: "fallback",
	},
	copy_components: {
		routes: ["DIRECT", "STEALTH", "REVIEW_REQUIRED"],
		copy_sets_scope: "product",
		copy_sets_endpoint: "/api/copy-sets/product/{product_id}",
		landbank_products: 0,
		source: "fallback",
	},
	ai_provider: {
		lane: "text_assist",
		configured: false,
		status: "unavailable",
		provider_id: null,
		model_id: null,
		execution_enabled: false,
		source: "fallback",
	},
	sources: {
		poster_dimensions: "fallback",
		flow_mirror: "fallback",
		copy_components: "fallback",
		ai_provider: "fallback",
	},
};

export async function fetchPosterBuilderSettings(): Promise<PosterBuilderSettings> {
	try {
		return await getAPI<PosterBuilderSettings>("/api/poster/builder-settings");
	} catch {
		return POSTER_BUILDER_SETTINGS_FALLBACK;
	}
}

export function usePosterBuilderSettings(): PosterBuilderSettings {
	const [settings, setSettings] = useState<PosterBuilderSettings>(
		POSTER_BUILDER_SETTINGS_FALLBACK,
	);
	useEffect(() => {
		let active = true;
		void fetchPosterBuilderSettings().then((s) => {
			if (active) setSettings(s);
		});
		return () => {
			active = false;
		};
	}, []);
	return settings;
}

/** First option flagged default, else the first option, else "". */
export function defaultOptionId(options: PosterSettingOption[]): string {
	return (options.find((o) => o.default) ?? options[0])?.id ?? "";
}
