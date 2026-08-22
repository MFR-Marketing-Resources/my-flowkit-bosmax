import { useEffect, useState } from "react";

import { getAPI } from "../../api/client";
import { Badge, Section } from "../ui";

type CopyAuthorityAttentionItem = {
	blueprint_id: string;
	revision: number;
	product_id: string;
	product_name: string;
	status: string;
	formula_id: string;
	activatable: boolean;
	current_authority_state: string;
	blocked_reason: string | null;
	current_authority_reason: string | null;
};

type CopyAuthorityAttentionResponse = {
	items: CopyAuthorityAttentionItem[];
	total: number;
	view: "diagnostics";
	provider_calls: 0;
	credit_spend: 0;
	activation_mutations: 0;
};

const REASON_LABELS: Record<string, string> = {
	COPY_V2_TAXONOMY_AUTHORITY_STALE:
		"Taxonomy authority changed after this copy was approved.",
	COPY_V2_EVIDENCE_STALE:
		"Product Truth or evidence changed after this copy was approved.",
	COPY_V2_PRODUCT_TRUTH_STALE:
		"Product Truth is stale for this copy.",
	COPY_V2_ACTIVATION_CANDIDATE_INVALID:
		"This approved copy is no longer activation-ready.",
};

function reasonCodes(item: CopyAuthorityAttentionItem): string[] {
	return (item.blocked_reason || item.current_authority_reason || "COPY_V2_AUTHORITY_ATTENTION")
		.split(/[·,]/)
		.map((reason) => reason.trim())
		.filter(Boolean);
}
function humanReason(item: CopyAuthorityAttentionItem): string {
	return reasonCodes(item)
		.map((code) => REASON_LABELS[code] || code.replaceAll("_", " ").toLowerCase())
		.join(" ");
}

function isDiagnostic(item: CopyAuthorityAttentionItem): boolean {
	return item.current_authority_state !== "CURRENT" &&
		!(item.status === "PRODUCTION_VALID" && item.activatable === true && item.current_authority_state === "NONE");
}

export function CopyAuthorityAttentionPanel() {
	const [items, setItems] = useState<CopyAuthorityAttentionItem[]>([]);
	const [safety, setSafety] = useState({ provider_calls: 0, credit_spend: 0, activation_mutations: 0 });
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");

	useEffect(() => {
		let cancelled = false;
		setLoading(true);
		void getAPI<CopyAuthorityAttentionResponse>(
			"/api/copy-register/v2/bulk/activation-candidates?view=diagnostics",
		)
			.then((response) => {
				if (cancelled) return;
				setItems((response.items ?? []).filter(isDiagnostic));
				setSafety({
					provider_calls: response.provider_calls,
					credit_spend: response.credit_spend,
					activation_mutations: response.activation_mutations,
				});
				setError("");
			})
			.catch((reason: unknown) => {
				if (!cancelled) setError(reason instanceof Error ? reason.message : "Copy-authority attention could not be loaded.");
			})
			.finally(() => {
				if (!cancelled) setLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, []);

	return (
		<Section
			title="COPY AUTHORITY ATTENTION"
			helper="Read-only operational attention for stale or blocked approved copy. Open the exact detail or create a replacement in Copywriting Landbank."
		>
			<div data-testid="copy-authority-attention-panel" className="space-y-3">
				<div
					data-testid="copy-authority-attention-safety"
					className="text-[10px] text-slate-500"
				>
					Read-only · provider calls: {safety.provider_calls} · credit spend: {safety.credit_spend} · activation mutations: {safety.activation_mutations}
				</div>
				{loading ? <p className="text-xs text-slate-500">Loading copy-authority attention…</p> : null}
				{error ? <p className="text-xs text-rose-300">{error}</p> : null}
				{!loading && !error && items.length === 0 ? (
					<p className="rounded-lg border border-dashed border-slate-800 px-3 py-4 text-xs text-slate-500">
						No stale or blocked copy-authority items.
					</p>
				) : null}
				{items.length > 0 ? (
					<div className="space-y-2" data-testid="copy-authority-attention-list">
						{items.map((item) => (
							<div
								key={`${item.blueprint_id}:${item.revision}`}
								data-testid={`copy-authority-attention-${item.blueprint_id}`}
								className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3"
							>
								<div className="flex flex-wrap items-start justify-between gap-2">
									<div>
										<p className="text-sm font-semibold text-slate-100">{item.product_name || item.product_id}</p>
										<p className="mt-1 text-xs text-slate-400">
											{item.formula_id} · Blueprint {item.blueprint_id} · revision {item.revision}
										</p>
									</div>
									<Badge tone="warn">{item.current_authority_state}</Badge>
								</div>
								<p className="mt-2 text-xs text-amber-100">{humanReason(item)}</p>
								<p className="mt-1 font-mono text-[10px] text-amber-200/70">{reasonCodes(item).join(" · ")}</p>
								<a
									href={item.current_authority_state === "STALE"
									? `/creative/storyboard-landbank-v3?product_id=${encodeURIComponent(item.product_id)}`
									: `/creative/copy-authority?product_id=${encodeURIComponent(item.product_id)}&blueprint_id=${encodeURIComponent(item.blueprint_id)}`}
									className="mt-3 inline-flex rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-1.5 text-[10px] font-bold uppercase text-amber-100 hover:bg-amber-500/20"
								>
									{item.current_authority_state === "STALE" ? "Create Replacement in Copywriting Landbank" : "Open Authority Detail"}
								</a>
							</div>
						))}
					</div>
				) : null}
			</div>
		</Section>
	);
}
