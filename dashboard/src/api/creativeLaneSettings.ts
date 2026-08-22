// Creative lane settings SSOT (Opening Strategy + Background) — Faceless + Montage.
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
	opening_strategy?: { default: string; options: CreativeLaneOption[] };
	actor_profile?: { default: string; options: CreativeLaneOption[] };
	/** Backward-compatible wire alias used by older Montage clients. */
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
	opening_strategy: { default: "AUTO", options: [] },
	hook: { default: "AUTO", options: [] },
	background: { default: "AUTO", options: [] },
	actor_profile: { default: "AUTO", options: [] },
	source: "unavailable",
};

export async function fetchCreativeLaneSettings(
	productId?: string | null,
): Promise<CreativeLaneSettings> {
	const query = productId
		? `?lane=FACELESS&product_id=${encodeURIComponent(productId)}`
		: "";
	return getAPI<CreativeLaneSettings>(`/api/creative-lane-settings${query}`);
}

export async function resolveCreativeLaneSettings(input: {
	hook_id?: string | null;
	background_id?: string | null;
	product_cluster?: string | null;
	has_approved_usp?: boolean;
	scene_context_hint?: string | null;
	product_id?: string | null;
}): Promise<{ hook: ResolvedLaneSetting; background: ResolvedLaneSetting }> {
	return postAPI("/api/creative-lane-settings/resolve", {
		hook_id: input.hook_id ?? "AUTO",
		background_id: input.background_id ?? "AUTO",
		product_cluster: input.product_cluster ?? null,
		has_approved_usp: Boolean(input.has_approved_usp),
		scene_context_hint: input.scene_context_hint ?? null,
		product_id: input.product_id ?? null,
	});
}

export interface FacelessPrepareResponse {
	ok: boolean;
	lane?: string;
	generation_mode?: string;
	model?: string;
	duration_seconds?: number | null;
	total_duration_seconds?: number | null;
	character_presence?: string;
	actor_profile?: Record<string, unknown> | null;
	avatar_id?: null;
	visual_law?: string;
	copy_architecture_v2?: Record<string, unknown> | null;
	debug?: {
		transport_mode?: string;
		source_mode?: string;
		reference_override?: boolean;
	};
	resolution?: {
		opening_strategy?: ResolvedLaneSetting;
		hook: ResolvedLaneSetting;
		background: ResolvedLaneSetting;
		scene_strategy?: Record<string, unknown> | null;
		choreography?: Record<string, unknown> | null;
	};
	faceless_resolution?: Record<string, unknown> | null;
	scene_context_override?: string;
	package?: {
		workspace_execution_package_id?: string;
		prompt_text?: string;
		prompt_fingerprint?: string | null;
		asset_slots?: Array<Record<string, unknown>>;
		[key: string]: unknown;
	};
	durable_lifecycle?: {
		plan: string;
		authorize: string;
		start: string;
		status: string;
		base_clip_duration_seconds: number;
		total_duration_seconds: number | null;
	} | null;
	error_code?: string;
	detail?: string;
}

export async function prepareFacelessPackage(input: {
	product_id: string;
	hook_id: string;
	background_id: string;
	model: string;
	generation_mode: "SINGLE" | "EXTEND";
	duration_seconds?: number | null;
	total_duration_seconds?: number | null;
	/** Advanced override only */
	start_frame_asset_id?: string | null;
	end_frame_asset_id?: string | null;
	copy_fallback_confirmed?: boolean;
	copy_v2_context?: Record<string, unknown> | null;
	actor_profile?: string | null;
	staff_id: string;
}): Promise<FacelessPrepareResponse> {
	return postAPI("/api/faceless/prepare", {
		product_id: input.product_id,
		hook_id: input.hook_id,
		background_id: input.background_id,
		model: input.model,
		generation_mode: input.generation_mode,
		duration_seconds: input.duration_seconds ?? null,
		total_duration_seconds: input.total_duration_seconds ?? null,
		start_frame_asset_id: input.start_frame_asset_id ?? null,
		end_frame_asset_id: input.end_frame_asset_id ?? null,
		copy_fallback_confirmed: false,
		copy_v2_context: input.copy_v2_context ?? null,
		actor_profile: input.actor_profile ?? "AUTO",
		staff_id: input.staff_id,
	});
}

export function useCreativeLaneSettings(productId?: string | null): {
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
		void fetchCreativeLaneSettings(productId)
			.then((s) => {
				if (!active) return;
				const opening = s?.opening_strategy ?? s?.hook;
				if (!opening?.options?.length || !s?.background?.options?.length) {
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
	}, [productId, tick]);
	const openingOptions =
		settings.opening_strategy?.options?.length
			? settings.opening_strategy.options
			: settings.hook.options;

	return {
		settings,
		loading,
		error,
		available: Boolean(
			openingOptions.length && settings.background.options.length,
		),
		reload: () => setTick((n) => n + 1),
	};
}
