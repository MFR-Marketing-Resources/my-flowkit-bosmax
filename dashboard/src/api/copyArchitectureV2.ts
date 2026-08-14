import { useEffect, useState } from "react";
import { getAPI } from "./client";

export type CopyArchitectureV2Lane =
	| "T2V"
	| "F2V"
	| "HYBRID"
	| "I2V"
	| "FACELESS"
	| "MONTAGE"
	| "PRODUCTION_STUDIO_P6"
	| "IMAGE_GEN"
	| "IMG_FASTLANE"
	| "IMG_COCKPIT"
	| "POSTER_BUILDER";

export type CopyArchitectureV2Execution = Record<string, unknown>;

export interface CopyArchitectureV2LaneDescriptor {
	lane_id: CopyArchitectureV2Lane;
	display_name: string;
	media_kind: "VIDEO" | "IMAGE";
	copy_policy: "REQUIRED" | "NOT_REQUIRED";
	current_api_entry_point: string;
	current_service_entry_point: string;
	current_page_entry_point: string;
	adapter: "VideoCopyProjection" | "ImageCopyProjection";
	phase3_scope: string;
	ui_surface_state: "ACTIVE" | "DORMANT_REDIRECTED";
}
export interface CopyArchitectureV2FeatureFlags {
	flag_name: string;
	enabled: boolean;
	shadow_mode: boolean;
	scope: string;
	pilot_scope: string[];
	state: "OFF" | "SHADOW" | "PILOT" | "ON";
}

export interface CopyArchitectureV2ConsumerStatus {
	version: "2";
	v2_only: boolean;
	legacy_storage_enabled: boolean;
	feature_flags: CopyArchitectureV2FeatureFlags;
	legacy_path_unchanged: boolean;
	binding_required_when_enabled: boolean;
	provider_calls: 0;
	credit_spend: false;
}

interface CopyArchitectureV2LaneResponse {
	version: "2";
	items: CopyArchitectureV2LaneDescriptor[];
}

export async function fetchCopyArchitectureV2ConsumerStatus(): Promise<CopyArchitectureV2ConsumerStatus> {
	return getAPI<CopyArchitectureV2ConsumerStatus>(
		"/api/copy-architecture/v2/consumer-status",
	);
}

export async function fetchCopyArchitectureV2Lanes(): Promise<CopyArchitectureV2LaneDescriptor[]> {
	const response = await getAPI<CopyArchitectureV2LaneResponse>(
		"/api/copy-architecture/v2/lanes",
	);
	return response.items;
}

export function useCopyArchitectureV2Lane(lane: CopyArchitectureV2Lane): {
	descriptor: CopyArchitectureV2LaneDescriptor | null;
	status: CopyArchitectureV2ConsumerStatus | null;
	loading: boolean;
	error: string | null;
} {
	const [descriptor, setDescriptor] =
		useState<CopyArchitectureV2LaneDescriptor | null>(null);
	const [status, setStatus] = useState<CopyArchitectureV2ConsumerStatus | null>(
		null,
	);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let active = true;
		setLoading(true);
		setError(null);
		void Promise.all([
			fetchCopyArchitectureV2ConsumerStatus(),
			fetchCopyArchitectureV2Lanes(),
		])
			.then(([nextStatus, lanes]) => {
				if (!active) return;
				setStatus(nextStatus);
				setDescriptor(lanes.find((item) => item.lane_id === lane) ?? null);
			})
			.catch((reason: unknown) => {
				if (!active) return;
				setError(reason instanceof Error ? reason.message : "V2 contract unavailable");
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [lane]);

	return { descriptor, status, loading, error };
}
