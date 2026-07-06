import { useEffect, useState } from "react";
import { getAPI } from "./client";

// Single source of truth for image-generation default settings, shared by every
// image-gen surface (IMG Fastlane, Image Gen, IMG Cockpit, Avatar Registry).
// Aspect ratios, counts, and the image-model list all come from ONE backend
// endpoint (`/api/img-factory/image-gen-settings`, backed by models.json) so the
// pages can never drift apart. Add/rename a model in models.json → every page
// updates. A `pending` model is listed but has no Google internal id yet, so
// generation fails closed until it is configured.

export interface ImageModelOption {
	key: string;
	label: string;
	pending: boolean;
}

export interface ImageGenSettings {
	models: ImageModelOption[];
	default_model: string;
	aspect_options: string[];
	default_aspect: string;
	count_options: number[];
	default_count: number;
}

// Used before the fetch resolves and if the agent is briefly unreachable — kept
// in lockstep with the backend defaults so the UI never renders an empty picker.
export const IMAGE_GEN_SETTINGS_FALLBACK: ImageGenSettings = {
	models: [
		{ key: "NANO_BANANA_PRO", label: "Nano Banana Pro", pending: false },
		{ key: "NANO_BANANA_2", label: "Nano Banana 2", pending: false },
		{ key: "NANO_BANANA_2_LITE", label: "Nano Banana 2 Lite", pending: true },
	],
	default_model: "Nano Banana 2",
	aspect_options: ["9:16", "1:1", "16:9", "4:3", "3:4"],
	default_aspect: "9:16",
	count_options: [1, 2, 3, 4],
	default_count: 1,
};

export async function fetchImageGenSettings(): Promise<ImageGenSettings> {
	try {
		return await getAPI<ImageGenSettings>(
			"/api/img-factory/image-gen-settings",
		);
	} catch {
		return IMAGE_GEN_SETTINGS_FALLBACK;
	}
}

/** Shared React hook: the same image-gen settings on every page. */
export function useImageGenSettings(): ImageGenSettings {
	const [settings, setSettings] = useState<ImageGenSettings>(
		IMAGE_GEN_SETTINGS_FALLBACK,
	);
	useEffect(() => {
		let active = true;
		void fetchImageGenSettings().then((s) => {
			if (active) setSettings(s);
		});
		return () => {
			active = false;
		};
	}, []);
	return settings;
}
