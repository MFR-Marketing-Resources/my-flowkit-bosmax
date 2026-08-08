// Creative lane settings SSOT (Hook + Background) — Faceless + Montage.
// ONE vocabulary source: backend GET /api/creative-lane-settings.
// No mirrored full option registry in the frontend (F-02).
import { useEffect, useState } from "react";
import { getAPI, postAPI } from "./client";

export interface CreativeLaneOption {
	id: string;
	label: string;
}

export interface CreativeLaneSettings {
	version: string;
	auto: { id: string; label: string };
	hook: { default: string; options: CreativeLaneOption[] };
	background: { default: string; options: CreativeLaneOption[] };
	semantics?: Record<string, string>;
	source: string;
}

export interface ResolvedLaneSetting {
	setting_id: string;
	display_label: string;
	operator_selection: string;
	resolution: string;
	strategy_intent?: string;
	environment_intent?: string;
	claim_authority?: string;
	product_truth_override?: boolean;
}

/** Fail-closed empty shell — NEVER a second full vocabulary copy. */
export const CREATIVE_LANE_SETTINGS_UNAVAILABLE: CreativeLaneSettings = {
	version: "UNAVAILABLE",
	auto: { id: "AUTO", label: "Auto (AI decided)" },
	hook: { default: "AUTO", options: [] },
	background: { default: "AUTO", options: [] },
	source: "unavailable",
};

export async function fetchCreativeLaneSettings(): Promise<CreativeLaneSettings> {
	return getAPI<CreativeLaneSettings>("/api/creative-lane-settings");
}

export async function resolveCreativeLaneSettings(input: {
	hook_id?: string | null;
	background_id?: string | null;
	product_cluster?: string | null;
	has_approved_usp?: boolean;
	scene_context_hint?: string | null;
}): Promise<{ hook: ResolvedLaneSetting; background: ResolvedLaneSetting }> {
	return postAPI("/api/creative-lane-settings/resolve", {
		hook_id: input.hook_id ?? "AUTO",
		background_id: input.background_id ?? "AUTO",
		product_cluster: input.product_cluster ?? null,
		has_approved_usp: Boolean(input.has_approved_usp),
		scene_context_hint: input.scene_context_hint ?? null,
	});
}

export interface FacelessPrepareResponse {
	ok: boolean;
	lane?: string;
	transport_mode?: string;
	source_mode?: string;
	character_presence?: string;
	resolution?: {
		hook: ResolvedLaneSetting;
		background: ResolvedLaneSetting;
	};
	scene_context_override?: string;
	package?: {
		workspace_execution_package_id?: string;
		prompt_text?: string;
		prompt_fingerprint?: string | null;
		[key: string]: unknown;
	};
	error_code?: string;
	detail?: string;
}

export async function prepareFacelessPackage(input: {
	product_id: string;
	start_frame_asset_id: string;
	end_frame_asset_id?: string | null;
	hook_id: string;
	background_id: string;
	duration_seconds?: number;
	copy_fallback_confirmed?: boolean;
}): Promise<FacelessPrepareResponse> {
	return postAPI("/api/faceless/prepare", {
		product_id: input.product_id,
		start_frame_asset_id: input.start_frame_asset_id,
		end_frame_asset_id: input.end_frame_asset_id ?? null,
		hook_id: input.hook_id,
		background_id: input.background_id,
		duration_seconds: input.duration_seconds ?? 8,
		copy_fallback_confirmed: input.copy_fallback_confirmed ?? true,
	});
}

export function useCreativeLaneSettings(): {
	settings: CreativeLaneSettings;
	loading: boolean;
	error: string | null;
	available: boolean;
	reload: () => void;
} {
	const [settings, setSettings] = useState<CreativeLaneSettings>(
		CREATIVE_LANE_SETTINGS_UNAVAILABLE,
	);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [tick, setTick] = useState(0);

	useEffect(() => {
		let active = true;
		setLoading(true);
		void fetchCreativeLaneSettings()
			.then((s) => {
				if (!active) return;
				if (!s?.hook?.options?.length || !s?.background?.options?.length) {
					setError("Settings payload incomplete");
					setSettings(CREATIVE_LANE_SETTINGS_UNAVAILABLE);
					return;
				}
				setSettings(s);
				setError(null);
			})
			.catch((err: unknown) => {
				if (!active) return;
				setError(err instanceof Error ? err.message : "settings unavailable");
				setSettings(CREATIVE_LANE_SETTINGS_UNAVAILABLE);
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [tick]);

	return {
		settings,
		loading,
		error,
		available: Boolean(
			settings.hook.options.length && settings.background.options.length,
		),
		reload: () => setTick((n) => n + 1),
	};
}
