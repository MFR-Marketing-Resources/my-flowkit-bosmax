import { useNavigate } from "react-router-dom";
import type { DataTableColumn } from "../ui";
import {
	INTELLIGENCE_STAGE_LABEL,
	type ExceptionItem,
	type ExceptionKind,
	type IntelligenceStage,
} from "../../api/reporting";

// Drill-down table for one exception kind. Navigates to the product page on row click
// (query-param drill target — there is no /products/:id route). No aggregation here; it
// renders exactly the server page the service selected.

const PRODUCT_COLS: DataTableColumn<ExceptionItem>[] = [
	{
		key: "name",
		header: "Product",
		render: (r) => (
			<span className="font-medium text-slate-200">
				{r.product_display_name ?? r.product_id ?? "—"}
			</span>
		),
		sortValue: (r) => r.product_display_name ?? "",
	},
	{
		key: "cluster",
		header: "Cluster",
		render: (r) => r.cluster ?? "—",
		sortValue: (r) => r.cluster ?? "",
	},
	{
		key: "creative_cluster",
		header: "Creative",
		render: (r) => r.creative_cluster ?? "—",
		sortValue: (r) => r.creative_cluster ?? "",
	},
	{
		key: "type",
		header: "Product Type",
		render: (r) => r.product_type_group ?? "—",
		sortValue: (r) => r.product_type_group ?? "",
	},
	{ key: "mapping", header: "Mapping", render: (r) => r.mapping_status ?? "—" },
	{ key: "prompt", header: "Prompt", render: (r) => r.prompt_readiness_status ?? "—" },
	{ key: "asset", header: "Image", render: (r) => r.asset_status ?? "—" },
	{
		key: "scene",
		header: "Scene Strategy",
		render: (r) => (
			<span className="whitespace-normal break-words">
				{r.scene_strategy_id ?? "—"}
			</span>
		),
	},
	{
		// variants INSIDE the one matched strategy - not a count of strategies. One safe
		// concrete scene is a complete contract, so 1 is never rendered as a warning.
		key: "scene_variants",
		header: "Variants",
		render: (r) => r.scene_variants_count ?? 0,
	},
	{ key: "scene_coverage", header: "Coverage", render: (r) => r.scene_coverage ?? "—" },
	{
		key: "scene_status",
		header: "Scene Contract",
		render: (r) =>
			r.scene_contract_status === "COMPLETE" ? (
				<span className="text-emerald-400">COMPLETE</span>
			) : (
				<span className="text-amber-400">{r.scene_contract_status ?? "—"}</span>
			),
	},
	{
		key: "scene_gap",
		header: "Scene Gap Reason",
		render: (r) => (
			<span className="whitespace-normal break-words text-amber-300">
				{r.scene_gap_reasons?.length ? r.scene_gap_reasons.join(", ") : "—"}
			</span>
		),
	},
];


/** Deep link into the EXISTING Product Intelligence review panel. */
export const intelligenceReviewHref = (productId: string) =>
	`/products?product=${encodeURIComponent(productId)}&tab=INTELLIGENCE`;

const STAGE_TONE: Record<IntelligenceStage, string> = {
	NO_DRAFT: "text-slate-400",
	CLAIM_BLOCKED: "text-red-300",
	CLAIM_REVIEW_REQUIRED: "text-amber-300",
	DRAFT_INCOMPLETE: "text-amber-200",
	READY_FOR_REVIEW: "text-sky-300",
	APPROVED_SNAPSHOT: "text-emerald-400",
};

// missing_intelligence drill-down. Every field the owner needs to rule on a product
// without opening SQL: what stage it is at, what is still missing, what the claim gate
// said, where the evidence came from, and whether copy is blocked behind it.
// 08D PI-quality drill-down rows: product + lifecycle + quality class + missing fields
// + governed dispositions + claim gate. All values are server-computed; this renders.
const PI_QUALITY_COLS: DataTableColumn<ExceptionItem>[] = [
	{
		key: "name",
		header: "Product",
		render: (r) => (
			<div className="min-w-[13rem]">
				<div className="font-medium text-slate-200">
					{r.product_display_name ?? r.product_id ?? "—"}
				</div>
				<div className="font-mono text-[10px] text-slate-500">{r.product_id}</div>
			</div>
		),
		sortValue: (r) => r.product_display_name ?? "",
	},
	{
		key: "lifecycle",
		header: "Lifecycle",
		render: (r) => r.lifecycle_status ?? "ACTIVE",
	},
	{
		key: "pi_quality",
		header: "PI quality",
		render: (r) => (
			<span
				className={
					r.pi_quality === "FULLY_COMPLETE"
						? "text-emerald-300"
						: r.pi_quality === "APPROVED_WITH_GOVERNED_ABSENCE"
							? "text-sky-300"
							: r.pi_quality === "LEGACY_APPROVED_INCOMPLETE"
								? "text-amber-300"
								: "text-red-300"
				}
			>
				{r.pi_quality ?? "—"}
			</span>
		),
	},
	{
		key: "missing",
		header: "Missing fields",
		render: (r) =>
			(r.missing_fields ?? []).length ? (r.missing_fields ?? []).join(", ") : "—",
	},
	{
		key: "dispositions",
		header: "Governed dispositions",
		render: (r) => {
			const rows = r.governed_dispositions ?? [];
			if (!rows.length) return "—";
			return (
				<div className="space-y-0.5">
					{rows.map((d) => (
						<div key={d.field_name} className="text-[10px]">
							<span className="font-semibold text-slate-200">{d.field_name}</span>{" "}
							<span className="text-sky-300">{d.disposition}</span>
							{d.reviewed_by ? (
								<span className="text-slate-500"> · {d.reviewed_by}</span>
							) : null}
							{d.reviewed_at ? (
								<span className="text-slate-600"> · {d.reviewed_at}</span>
							) : null}
						</div>
					))}
				</div>
			);
		},
	},
	{
		key: "claim",
		header: "Claim gate",
		render: (r) => r.claim_gate ?? "—",
	},
];

const INTELLIGENCE_COLS: DataTableColumn<ExceptionItem>[] = [
	{
		key: "name",
		header: "Product",
		render: (r) => (
			<div className="min-w-[13rem]">
				<div className="font-medium text-slate-200">
					{r.product_display_name ?? r.product_id ?? "—"}
				</div>
				<div className="font-mono text-[10px] text-slate-500">{r.product_id}</div>
			</div>
		),
		sortValue: (r) => r.product_display_name ?? "",
	},
	{
		key: "lifecycle",
		header: "Lifecycle",
		render: (r) =>
			r.lifecycle_status === "ACTIVE" ? (
				<span className="text-emerald-400">ACTIVE</span>
			) : (
				<span className="text-slate-400">{r.lifecycle_status ?? "—"}</span>
			),
	},
	{ key: "cluster", header: "Cluster", render: (r) => r.cluster ?? "—" },
	{ key: "type", header: "Product Type", render: (r) => r.product_type_group ?? "—" },
	{
		key: "stage",
		header: "Intelligence Stage",
		render: (r) => {
			const stage = (r.intelligence_stage ?? null) as IntelligenceStage | null;
			return (
				<span className={stage ? STAGE_TONE[stage] : "text-slate-400"}>
					{stage ? INTELLIGENCE_STAGE_LABEL[stage] : "—"}
				</span>
			);
		},
	},
	{ key: "draft", header: "Draft", render: (r) => r.draft_status ?? "NONE" },
	{
		key: "missing",
		header: "Missing Fields",
		render: (r) =>
			r.missing_field_count ? (
				<span
					className="whitespace-normal break-words text-amber-200"
					title={(r.missing_fields ?? []).join(", ")}
				>
					{r.missing_field_count}: {(r.missing_fields ?? []).slice(0, 3).join(", ")}
					{(r.missing_fields?.length ?? 0) > 3 ? "…" : ""}
				</span>
			) : (
				<span className="text-emerald-400">none</span>
			),
	},
	{ key: "risk", header: "Claim Risk", render: (r) => r.claim_risk_level ?? "—" },
	{ key: "gate", header: "Claim Status", render: (r) => r.claim_gate ?? "—" },
	{
		key: "reasons",
		header: "Claim Reasons",
		render: (r) => (
			<span className="whitespace-normal break-words text-red-300">
				{r.claim_reasons?.length ? r.claim_reasons.join(", ") : "—"}
			</span>
		),
	},
	{ key: "source", header: "Source", render: (r) => r.source ?? "—" },
	{
		key: "snapshot",
		header: "Approved Snapshot",
		render: (r) =>
			r.approved_snapshot ? (
				<span className="text-emerald-400">{r.snapshot_status ?? "YES"}</span>
			) : (
				<span className="text-slate-400">NONE</span>
			),
	},
	{
		key: "copy_blocked",
		header: "Copy Blocked",
		render: (r) =>
			r.copy_blocked ? (
				<span className="text-red-300">Yes</span>
			) : (
				<span className="text-emerald-400">No</span>
			),
	},
	{
		key: "review",
		header: "Review",
		render: (r) =>
			r.product_id ? (
				<a
					href={intelligenceReviewHref(r.product_id)}
					data-testid="intelligence-review-link"
					onClick={(e) => e.stopPropagation()}
					className="rounded border border-sky-400/40 bg-sky-500/15 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-sky-100 hover:bg-sky-500/25"
				>
					Review
				</a>
			) : (
				"—"
			),
	},
];

const FAILED_COLS: DataTableColumn<ExceptionItem>[] = [
	{
		key: "name",
		header: "Product",
		render: (r) => (
			<span className="font-medium text-slate-200">
				{r.product_display_name ?? r.product_id ?? "—"}
			</span>
		),
		sortValue: (r) => r.product_display_name ?? "",
	},
	{ key: "mode", header: "Mode", render: (r) => r.mode ?? "—" },
	{
		key: "error",
		header: "Error",
		render: (r) => (
			<span className="text-red-300">{r.error_code ?? r.error_message ?? "—"}</span>
		),
	},
	{
		key: "failed",
		header: "Failed at",
		render: (r) => r.failed_at ?? r.created_at ?? "—",
		sortValue: (r) => r.failed_at ?? r.created_at ?? "",
	},
];

/** Column key -> server-side `sort_by`. Only these are sortable; the server keeps its own
 * allowlist, so an unknown value can never reach SQL as an identifier. */
const SORT_KEYS: Record<string, string> = {
	name: "product_display_name",
	cluster: "cluster",
	type: "product_type_group",
	mapping: "mapping_status",
	prompt: "prompt_readiness_status",
	asset: "asset_status",
	scene: "matched_scene_strategy_id",
	scene_coverage: "scene_coverage_status",
	failed: "updated_at",
	stage: "intelligence_stage",
	draft: "draft_status",
	risk: "claim_risk_level",
	lifecycle: "lifecycle_status",
};

export interface ExceptionTableProps {
	kind: ExceptionKind;
	items: ExceptionItem[];
	loading?: boolean;
	/** Controlled server-side paging/search/sort. */
	total: number;
	page: number;
	pageSize: number;
	q: string;
	sortBy: string;
	sortDir: "asc" | "desc";
	onPageChange: (page: number) => void;
	onSearchChange: (q: string) => void;
	onSortChange: (sortBy: string, sortDir: "asc" | "desc") => void;
}

/**
 * Server-driven drill-down. Paging, search and sorting are resolved by the API over the
 * WHOLE cohort — the previous version fetched a truncated first 100 rows and then
 * searched, sorted and paginated that subset locally, so anything past row 100 was
 * invisible. This deliberately does NOT reuse the shared client-side DataTable, whose
 * header sort and search would silently apply to only the rows on screen.
 */
export function ExceptionTable({
	kind, items, loading, total, page, pageSize, q, sortBy, sortDir,
	onPageChange, onSearchChange, onSortChange,
}: ExceptionTableProps) {
	const navigate = useNavigate();
	const cols =
		kind === "failed_generation"
			? FAILED_COLS
			: kind === "missing_intelligence"
				? INTELLIGENCE_COLS
				: kind.startsWith("pi_")
					? PI_QUALITY_COLS
					: PRODUCT_COLS;
	const pageCount = Math.max(1, Math.ceil(total / pageSize));
	const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
	const to = Math.min(page * pageSize, total);

	const toggleSort = (colKey: string) => {
		const key = SORT_KEYS[colKey];
		if (!key) return;
		onSortChange(key, sortBy === key && sortDir === "asc" ? "desc" : "asc");
	};

	return (
		<div className="space-y-3">
			<div className="flex flex-wrap items-center justify-between gap-3">
				<input
					value={q}
					onChange={(e) => onSearchChange(e.target.value)}
					placeholder="Search all products…"
					aria-label="Search all products"
					className="w-64 rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-200 placeholder:text-slate-500"
				/>
				<span className="text-xs text-slate-400" data-testid="exception-range">
					{from}–{to} of {total.toLocaleString()}
				</span>
			</div>

			<div className="overflow-x-auto rounded-lg border border-slate-800">
				<table className="min-w-[720px] w-full text-left text-xs">
					<thead className="bg-slate-900/60 text-slate-400">
						<tr>
							{cols.map((c) => {
								const key = SORT_KEYS[c.key];
								const active = key && sortBy === key;
								return (
									<th key={c.key} className="px-3 py-2 font-medium">
										{key ? (
											<button
												type="button"
												onClick={() => toggleSort(c.key)}
												className="inline-flex items-center gap-1 hover:text-slate-200"
											>
												{c.header}
												{active ? <span>{sortDir === "asc" ? "▲" : "▼"}</span> : null}
											</button>
										) : (
											c.header
										)}
									</th>
								);
							})}
						</tr>
					</thead>
					<tbody>
						{items.length === 0 ? (
							<tr>
								<td colSpan={cols.length} className="px-3 py-6 text-center text-slate-500">
									{loading
										? "Loading…"
										: "No records — nothing in this exception bucket."}
								</td>
							</tr>
						) : (
							items.map((r) => (
								<tr
									key={r.request_id ?? r.product_id ?? ""}
									onClick={() => {
										if (r.product_id)
											navigate(
												kind === "missing_intelligence" ||
													kind.startsWith("pi_")
													? intelligenceReviewHref(r.product_id)
													: `/products?product=${encodeURIComponent(r.product_id)}`,
											);
									}}
									className="cursor-pointer border-t border-slate-800 text-slate-300 hover:bg-slate-800/50"
								>
									{cols.map((c) => (
										<td key={c.key} className="px-3 py-2">
											{c.render(r)}
										</td>
									))}
								</tr>
							))
						)}
					</tbody>
				</table>
			</div>

			<div className="flex items-center justify-between gap-3">
				<span className="text-xs text-slate-500" data-testid="exception-page">
					Page {page} / {pageCount}
				</span>
				<div className="flex gap-2">
					<button
						type="button"
						disabled={page <= 1 || loading}
						onClick={() => onPageChange(page - 1)}
						className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-300 disabled:opacity-40"
					>
						Prev
					</button>
					<button
						type="button"
						disabled={page >= pageCount || loading}
						onClick={() => onPageChange(page + 1)}
						className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-300 disabled:opacity-40"
					>
						Next
					</button>
				</div>
			</div>
		</div>
	);
}
