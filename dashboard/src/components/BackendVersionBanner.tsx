import { useEffect, useState } from "react";
import { fetchAPI } from "../api/client";

interface VersionProof {
	pid: number;
	process_started_at: string;
	git_head: string | null;
	git_branch: string | null;
	route_count: number;
	critical_routes: Record<string, boolean>;
	dashboard_bundle: string | null;
	source_stale_since_start: boolean;
	stale_source_sample: string[];
}

export interface BackendVersionBannerProps {
	onRuntimeStaleChange?: (isStale: boolean) => void;
}

/**
 * Operator-facing frontend/backend version-skew guard (incident 2026-07-09):
 * a stale backend process served a newer dashboard and mis-routed the
 * eligibility audit into a misleading CREATIVE_ASSET_NOT_FOUND. This banner
 * surfaces the backend identity and warns loudly when the running process is
 * stale relative to the source tree or is missing a critical route.
 */
export default function BackendVersionBanner({
	onRuntimeStaleChange,
}: BackendVersionBannerProps) {
	const [proof, setProof] = useState<VersionProof | null>(null);
	const [fetchError, setFetchError] = useState<string | null>(null);
	const [isRefreshing, setIsRefreshing] = useState(false);
	const [refreshNonce, setRefreshNonce] = useState(0);

	useEffect(() => {
		let cancelled = false;
		const loadProof = () => {
			setIsRefreshing(true);
			fetchAPI<VersionProof>("/api/local-agent/version-proof")
			.then((data) => {
				if (cancelled) return;
				setProof(data);
				setFetchError(null);
				const missingRoutes = Object.values(data.critical_routes).some(
					(present) => !present,
				);
				onRuntimeStaleChange?.(data.source_stale_since_start || missingRoutes);
			})
			.catch((err) => {
				// An old backend without this endpoint is itself a staleness signal.
				if (!cancelled) {
					setFetchError(err instanceof Error ? err.message : String(err));
					onRuntimeStaleChange?.(true);
				}
			})
			.finally(() => {
				if (!cancelled) setIsRefreshing(false);
			});
		};
		loadProof();
		return () => {
			cancelled = true;
		};
	}, [onRuntimeStaleChange, refreshNonce]);

	const refreshLabel = isRefreshing ? "Checking backend…" : "Refresh version check";

	if (fetchError) {
		return (
			<div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
				<strong>Backend needs restart.</strong> The version check is unavailable
				({fetchError}), so eligibility audits and production actions are locked.
				Stop and restart the local agent, then refresh this check.{" "}
				<button
					type="button"
					onClick={() => setRefreshNonce((current) => current + 1)}
					disabled={isRefreshing}
					className="ml-2 rounded border border-amber-300/40 px-2 py-1 font-semibold hover:bg-amber-500/10 disabled:opacity-50"
				>
					{refreshLabel}
				</button>
			</div>
		);
	}
	if (!proof) return null;

	const missingRoutes = Object.entries(proof.critical_routes)
		.filter(([, present]) => !present)
		.map(([path]) => path);
	const hasWarning = proof.source_stale_since_start || missingRoutes.length > 0;

	if (!hasWarning) {
		return (
			<div className="text-[11px] text-slate-500">
				backend {proof.git_head ? proof.git_head.slice(0, 8) : "unknown"} (
				{proof.git_branch ?? "?"}) · pid {proof.pid} · bundle{" "}
				{proof.dashboard_bundle ?? "?"} · {proof.route_count} routes
			</div>
		);
	}

	return (
		<div className="rounded-lg border border-red-500/50 bg-red-500/10 px-3 py-2 text-xs text-red-200">
			<strong>Backend needs restart.</strong> Eligibility audits and production
			actions are locked. {" "}
			{proof.source_stale_since_start && (
				<span>
					Source files changed after the backend started (
					{proof.stale_source_sample.slice(0, 2).join(", ")}
					{proof.stale_source_sample.length > 2 ? ", …" : ""}) — the running
					process is stale.{" "}
				</span>
			)}
			{missingRoutes.length > 0 && (
				<span>Missing critical routes: {missingRoutes.join(", ")}. </span>
			)}
			Stop and restart the local agent, then refresh this check.{" "}
			<button
				type="button"
				onClick={() => setRefreshNonce((current) => current + 1)}
				disabled={isRefreshing}
				className="ml-2 rounded border border-red-300/40 px-2 py-1 font-semibold hover:bg-red-500/10 disabled:opacity-50"
			>
				{refreshLabel}
			</button>
		</div>
	);
}
