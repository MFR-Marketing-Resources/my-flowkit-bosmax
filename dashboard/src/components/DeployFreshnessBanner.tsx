import { useEffect, useRef, useState } from "react";
import { fetchAPI } from "../api/client";

interface FreshnessProof {
	git_head: string | null;
	dashboard_bundle: string | null;
}

export interface DeployFreshnessBannerProps {
	/** Poll cadence in ms (default 60s). */
	intervalMs?: number;
	/** Reload action — injectable so tests don't hit window.location. */
	onReload?: () => void;
}

/**
 * Global frontend-freshness guard. A single-page app keeps running the JS bundle
 * it loaded with; once a NEW release is deployed to :8100 the open tab silently
 * runs stale UI until the operator happens to hard-refresh. This banner polls the
 * backend's deployed identity and, the moment the deployed SHA changes from the
 * one this tab loaded with, offers a one-click reload — so a deploy shows up
 * without anyone remembering to refresh. Backend restart / route health is a
 * separate concern owned by BackendVersionBanner.
 */
export default function DeployFreshnessBanner({
	intervalMs = 60_000,
	onReload,
}: DeployFreshnessBannerProps) {
	const loadedSha = useRef<string | null>(null);
	const [updateAvailable, setUpdateAvailable] = useState(false);
	const [dismissed, setDismissed] = useState(false);

	useEffect(() => {
		let cancelled = false;
		const check = () => {
			fetchAPI<FreshnessProof>("/api/local-agent/version-proof")
				.then((data) => {
					if (cancelled) return;
					const sha = data.git_head;
					if (!sha) return;
					if (loadedSha.current === null) {
						// First successful read anchors what THIS tab is running.
						loadedSha.current = sha;
						return;
					}
					if (sha !== loadedSha.current) setUpdateAvailable(true);
				})
				.catch(() => {
					// Transient errors are not a freshness signal — never nag on them.
				});
		};
		check();
		const timer = window.setInterval(check, intervalMs);
		return () => {
			cancelled = true;
			window.clearInterval(timer);
		};
	}, [intervalMs]);

	if (!updateAvailable || dismissed) return null;

	const reload = onReload ?? (() => window.location.reload());

	return (
		<div
			data-testid="deploy-freshness-banner"
			className="fixed inset-x-0 top-0 z-[60] flex items-center justify-center gap-3 border-b border-blue-400/40 bg-blue-600/95 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-blue-950/40 backdrop-blur"
		>
			<span>A new version has been deployed. Reload to get the latest UI.</span>
			<button
				type="button"
				data-testid="deploy-freshness-reload"
				onClick={reload}
				className="rounded-lg border border-white/50 bg-white/15 px-3 py-1 font-bold uppercase tracking-wide hover:bg-white/25"
			>
				Reload now
			</button>
			<button
				type="button"
				aria-label="Dismiss update notice"
				data-testid="deploy-freshness-dismiss"
				onClick={() => setDismissed(true)}
				className="rounded-lg border border-white/30 px-2 py-1 text-white/80 hover:bg-white/10"
			>
				✕
			</button>
		</div>
	);
}
