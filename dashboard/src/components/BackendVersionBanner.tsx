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

/**
 * Operator-facing frontend/backend version-skew guard (incident 2026-07-09):
 * a stale backend process served a newer dashboard and mis-routed the
 * eligibility audit into a misleading CREATIVE_ASSET_NOT_FOUND. This banner
 * surfaces the backend identity and warns loudly when the running process is
 * stale relative to the source tree or is missing a critical route.
 */
export default function BackendVersionBanner() {
	const [proof, setProof] = useState<VersionProof | null>(null);
	const [fetchError, setFetchError] = useState<string | null>(null);

	useEffect(() => {
		let cancelled = false;
		fetchAPI<VersionProof>("/api/local-agent/version-proof")
			.then((data) => {
				if (!cancelled) setProof(data);
			})
			.catch((err) => {
				// An old backend without this endpoint is itself a staleness signal.
				if (!cancelled)
					setFetchError(err instanceof Error ? err.message : String(err));
			});
		return () => {
			cancelled = true;
		};
	}, []);

	if (fetchError) {
		return (
			<div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
				Backend version-proof unavailable ({fetchError}) — the running backend
				may predate this dashboard build. Restart the local agent before
				trusting eligibility or generation surfaces.
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
			<strong>Backend version mismatch.</strong>{" "}
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
			Restart the local agent before using eligibility audits or generating.
		</div>
	);
}
