import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import {
	bulkUpdateProductRelease,
	fetchProductReleaseControl,
	hideProduct,
	releaseProduct,
	type ProductReleaseRow,
} from "../api/productRelease";
import { resolveProductVisualPresentation } from "../utils/productVisualPresentation";

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 50;
type PageSize = (typeof PAGE_SIZE_OPTIONS)[number];

function displayName(row: ProductReleaseRow): string {
	return row.product_short_name || row.product_display_name || row.raw_product_title || row.id;
}

function dateLabel(value?: string | null): string {
	return value ? new Date(value).toLocaleString() : "—";
}

function statusClass(value: string): string {
	if (value === "RELEASED" || value === "ELIGIBLE" || value === "VISIBLE_TO_STAFF") {
		return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
	}
	if (value === "RELEASED_BUT_BLOCKED" || value === "BLOCKED" || value === "HIDDEN_AND_BLOCKED") {
		return "border-rose-500/30 bg-rose-500/10 text-rose-200";
	}
	return "border-amber-500/30 bg-amber-500/10 text-amber-100";
}

function visualLabel(status: string): string {
	if (status === "OFFICIAL") return "OFFICIAL";
	if (status === "ORIGINAL_FALLBACK") return "ORIGINAL FALLBACK";
	return "NO OFFICIAL VISUAL";
}

function visualLabelClass(status: string): string {
	if (status === "OFFICIAL") {
		return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
	}
	if (status === "ORIGINAL_FALLBACK") {
		return "border-amber-500/30 bg-amber-500/10 text-amber-100";
	}
	return "border-slate-700 bg-slate-950 text-slate-400";
}

function ProductThumbnail({ row }: { row: ProductReleaseRow }) {
	const visual = resolveProductVisualPresentation(row as unknown as Record<string, unknown>);
	const [imageFailed, setImageFailed] = useState(false);

	useEffect(() => {
		setImageFailed(false);
	}, [visual.previewUrl]);

	const label = visualLabel(visual.visualStatus);
	const hasPreview = Boolean(visual.previewUrl) && !imageFailed;

	return (
		<div className="flex w-[92px] flex-col items-center gap-2" data-testid={`product-release-visual-${row.id}`}>
			<div className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-lg border border-slate-700 bg-slate-950 p-1">
				{hasPreview ? (
					<img
						src={visual.previewUrl || undefined}
						alt={`${visual.displayName || displayName(row)} product visual`}
						className="h-full w-full object-contain"
						onError={() => setImageFailed(true)}
						data-testid={`product-release-thumbnail-${row.id}`}
					/>
				) : (
					<span className="px-1 text-center text-[9px] uppercase leading-tight text-slate-500" role="img" aria-label="No image available">
						No image
					</span>
				)}
			</div>
			<span className={`rounded border px-1.5 py-0.5 text-center text-[9px] font-semibold leading-tight ${visualLabelClass(visual.visualStatus)}`}>
				{label}
			</span>
		</div>
	);
}

export default function ProductReleaseControlPage() {
	const auth = useAuth();
	const [rows, setRows] = useState<ProductReleaseRow[]>([]);
	const [summary, setSummary] = useState({ hidden: 0, released: 0, visible_to_staff: 0, released_but_blocked: 0, eligible_to_release: 0 });
	const [totalCount, setTotalCount] = useState(0);
	const [search, setSearch] = useState("");
	const [releaseStatus, setReleaseStatus] = useState("");
	const [visibility, setVisibility] = useState("");
	const [eligibility, setEligibility] = useState("");
	const [blocker, setBlocker] = useState("");
	const [page, setPage] = useState(1);
	const [pageSize, setPageSize] = useState<PageSize>(DEFAULT_PAGE_SIZE);
	const [selected, setSelected] = useState<Set<string>>(new Set());
	const [note, setNote] = useState("");
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [message, setMessage] = useState("");

	const resetPageAndSelection = () => {
		setPage(1);
		setSelected(new Set());
	};

	const offset = (page - 1) * pageSize;
	const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));

	const load = useCallback(async () => {
		if (!auth.hasPermission("products.release")) return;
		setError("");
		try {
			const response = await fetchProductReleaseControl({
				q: search.trim() || undefined,
				releaseStatus: releaseStatus || undefined,
				visibility: visibility || undefined,
				eligibility: eligibility || undefined,
				blocker: blocker || undefined,
				limit: pageSize,
				offset,
			});
			setRows(response.items);
			setTotalCount(response.total_count);
			setSummary(response.summary);
			// Selection is intentionally page-scoped. A navigation or reload cannot
			// carry hidden rows into a later bulk action.
			setSelected(new Set());
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : "Product release authority unavailable.");
		}
	}, [auth, search, releaseStatus, visibility, eligibility, blocker, pageSize, offset]);

	useEffect(() => { void load(); }, [load]);

	useEffect(() => {
		if (page > totalPages) {
			setPage(totalPages);
			setSelected(new Set());
		}
	}, [page, totalPages]);

	const allSelected = rows.length > 0 && rows.every((row) => selected.has(row.id));
	const selectedRows = useMemo(() => rows.filter((row) => selected.has(row.id)), [rows, selected]);

	const goToPage = (nextPage: number) => {
		const boundedPage = Math.min(Math.max(nextPage, 1), totalPages);
		if (boundedPage === page) return;
		setSelected(new Set());
		setPage(boundedPage);
	};

	const changePageSize = (value: string) => {
		const nextPageSize = Number(value) as PageSize;
		if (!PAGE_SIZE_OPTIONS.includes(nextPageSize)) return;
		setPageSize(nextPageSize);
		resetPageAndSelection();
	};

	const runAction = async (action: "RELEASE" | "HIDE", ids: string[]) => {
		if (!ids.length) return;
		setBusy(true);
		setError("");
		setMessage("");
		try {
			const response = ids.length === 1
				? action === "RELEASE"
					? await releaseProduct(ids[0], note)
					: await hideProduct(ids[0], note)
				: await bulkUpdateProductRelease(ids, action, note);
			if (!response.ok) {
				setError(response.message || response.error || "Release action was rejected.");
			} else {
				setMessage(`${action === "RELEASE" ? "Release" : "Hide"} request completed for ${ids.length} product${ids.length === 1 ? "" : "s"}.`);
			}
			setSelected(new Set());
			await load();
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : "Release action failed.");
		} finally {
			setBusy(false);
		}
	};

	if (!auth.hasPermission("products.release")) {
		return <div className="min-h-full bg-slate-950 p-8 text-sm text-rose-300">Only OWNER may view Product Release Control.</div>;
	}

	const rangeStart = totalCount === 0 ? 0 : offset + 1;
	const rangeEnd = totalCount === 0 ? 0 : Math.min(offset + rows.length, totalCount);

	return (
		<div className="min-h-full bg-slate-950 px-4 py-5 text-slate-100 md:px-8">
			<header className="mb-5 rounded-2xl border border-amber-500/20 bg-amber-500/5 p-5">
				<p className="text-[10px] font-bold uppercase tracking-[0.2em] text-amber-300">System · Owner authority</p>
				<h1 className="mt-2 text-2xl font-bold">Product Release Control</h1>
				<p className="mt-2 max-w-4xl text-sm text-slate-400">Operational staff visibility is the intersection of an explicit OWNER release and the current Product Truth, visual, mapping, copy, and readiness gates. Historical products remain queryable here and are never deleted.</p>
			</header>

			<div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
				{[["Hidden", summary.hidden, "product-release-summary-hidden"], ["Released", summary.released, "product-release-summary-released"], ["Visible", summary.visible_to_staff, "product-release-summary-visible"], ["Released · blocked", summary.released_but_blocked, "product-release-summary-blocked"], ["Eligible to release", summary.eligible_to_release, "product-release-summary-eligible"]].map(([label, value, testId]) => <div key={String(label)} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4" data-testid={String(testId)}><p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p><p className="mt-2 text-2xl font-bold text-slate-100">{value}</p></div>)}
			</div>

			<section className="mb-5 rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
				<div className="grid gap-3 md:grid-cols-5">
					<input value={search} onChange={(event) => { setSearch(event.target.value); resetPageAndSelection(); }} placeholder="Search product, brand, id" aria-label="Search products" className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm md:col-span-2" />
					<select value={releaseStatus} onChange={(event) => { setReleaseStatus(event.target.value); resetPageAndSelection(); }} aria-label="Release status filter" className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"><option value="">All release states</option><option value="HIDDEN">Hidden</option><option value="RELEASED">Released</option></select>
					<select value={eligibility} onChange={(event) => { setEligibility(event.target.value); resetPageAndSelection(); }} aria-label="Eligibility filter" className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"><option value="">All eligibility</option><option value="ELIGIBLE">Eligible</option><option value="BLOCKED">Blocked</option></select>
					<select value={visibility} onChange={(event) => { setVisibility(event.target.value); resetPageAndSelection(); }} aria-label="Visibility filter" className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"><option value="">All visibility</option><option value="VISIBLE_TO_STAFF">Visible to staff</option><option value="OWNER_RELEASE_REQUIRED">Release required</option><option value="RELEASED_BUT_BLOCKED">Released · blocked</option><option value="HIDDEN_AND_BLOCKED">Hidden · blocked</option></select>
				</div>
				<div className="mt-3 flex flex-wrap items-center gap-3"><input value={blocker} onChange={(event) => { setBlocker(event.target.value.toUpperCase()); resetPageAndSelection(); }} placeholder="Blocker code filter" aria-label="Blocker filter" className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-mono" /><input value={note} onChange={(event) => setNote(event.target.value)} maxLength={500} placeholder="Optional audit note" aria-label="Audit note" className="min-w-[240px] flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm" /><button type="button" disabled={busy || selectedRows.length === 0} onClick={() => void runAction("RELEASE", selectedRows.map((row) => row.id))} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold disabled:opacity-50">Release selected</button><button type="button" disabled={busy || selectedRows.length === 0} onClick={() => void runAction("HIDE", selectedRows.map((row) => row.id))} className="rounded-lg border border-rose-500/40 px-3 py-2 text-xs font-bold text-rose-200 disabled:opacity-50">Hide selected</button></div>
			</section>

			{error ? <p role="alert" className="mb-4 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</p> : null}
			{message ? <p role="status" className="mb-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200">{message}</p> : null}

			<section className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900/40">
				<table className="w-full min-w-[1340px] text-left text-xs">
					<thead className="border-b border-slate-800 text-[10px] uppercase tracking-wider text-slate-500"><tr><th className="p-4"><input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map((row) => row.id)))} aria-label="Select current page" /></th><th className="p-4">Visual</th><th className="p-4">Product</th><th className="p-4">Lifecycle</th><th className="p-4">Product Truth</th><th className="p-4">Visual readiness</th><th className="p-4">Readiness</th><th className="p-4">Release</th><th className="p-4">Blockers</th><th className="p-4">Owner action</th></tr></thead>
					<tbody>{rows.map((row) => <tr key={row.id} data-testid={`product-release-row-${row.id}`} className="border-b border-slate-800/70 align-top"><td className="p-4"><input type="checkbox" checked={selected.has(row.id)} onChange={() => setSelected((current) => { const next = new Set(current); if (next.has(row.id)) next.delete(row.id); else next.add(row.id); return next; })} aria-label={`Select ${displayName(row)}`} /></td><td className="p-4"><ProductThumbnail row={row} /></td><td className="p-4"><p className="max-w-[220px] font-semibold text-slate-100">{displayName(row)}</p><p className="mt-1 font-mono text-[10px] text-slate-500">{row.id}</p></td><td className="p-4"><span className="rounded border border-slate-700 px-2 py-1 text-[10px]">{row.lifecycle_status || "ACTIVE"}</span></td><td className="p-4"><p>{row.product_truth_status || "NOT_STARTED"}</p>{row.product_truth_update_pending ? <p className="mt-1 text-amber-200">Update pending</p> : null}</td><td className="p-4"><p>{row.visual_readiness?.exact_commerce_status || "UNKNOWN"}</p><p className="mt-1 text-slate-500">{row.visual_readiness?.canonical_media_status || "—"}</p></td><td className="p-4"><span className={`rounded border px-2 py-1 text-[10px] ${statusClass(row.minimum_eligibility_status)}`}>{row.minimum_eligibility_status}</span><p className="mt-2 text-slate-400">{row.mapping_status || "MAPPING_UNKNOWN"} · {row.prompt_readiness_status || "READINESS_UNKNOWN"}</p></td><td className="p-4"><span className={`rounded border px-2 py-1 text-[10px] ${statusClass(row.staff_release_status)}`}>{row.staff_release_status}</span><p className={`mt-2 rounded border px-2 py-1 text-[10px] ${statusClass(row.visibility_reason)}`}>{row.visibility_reason}</p><p className="mt-2 text-slate-500">{dateLabel(row.release_history?.release_updated_at)}</p></td><td className="max-w-[240px] p-4">{row.blocker_codes.length ? <div className="flex flex-wrap gap-1">{row.blocker_codes.map((code) => <span key={code} className="rounded bg-rose-500/10 px-2 py-1 font-mono text-[10px] text-rose-200">{code}</span>)}</div> : <span className="text-emerald-300">No current blockers</span>}</td><td className="p-4"><div className="flex flex-wrap gap-2">{row.staff_release_status === "HIDDEN" ? <button type="button" disabled={busy || row.minimum_eligibility_status !== "ELIGIBLE"} onClick={() => void runAction("RELEASE", [row.id])} className="rounded bg-emerald-600 px-2 py-1 text-[10px] font-bold disabled:cursor-not-allowed disabled:opacity-40">Release</button> : <button type="button" disabled={busy} onClick={() => void runAction("HIDE", [row.id])} className="rounded border border-rose-500/40 px-2 py-1 text-[10px] font-bold text-rose-200 disabled:opacity-40">Hide</button>}{row.staff_release_status === "HIDDEN" && row.minimum_eligibility_status !== "ELIGIBLE" ? <span className="text-[10px] text-rose-200">Blocked — fix inputs first</span> : null}</div></td></tr>)}</tbody>
				</table>
				{rows.length === 0 ? <p className="p-8 text-center text-sm text-slate-500">No products match the release-control filters.</p> : null}
			</section>

			<nav aria-label="Product release pagination" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-xs text-slate-400">
				<p data-testid="product-release-range">Showing {rangeStart}–{rangeEnd} of {totalCount}</p>
				<div className="flex flex-wrap items-center gap-2">
					<span data-testid="product-release-page">Page {page} of {totalPages}</span>
					<select value={pageSize} onChange={(event) => changePageSize(event.target.value)} aria-label="Product release page size" className="rounded border border-slate-700 bg-slate-950 px-2 py-1"><option value="25">25</option><option value="50">50</option><option value="100">100</option></select>
					<button type="button" onClick={() => goToPage(1)} disabled={page <= 1} className="rounded border border-slate-700 px-2 py-1 disabled:cursor-not-allowed disabled:opacity-40">First</button>
					<button type="button" onClick={() => goToPage(page - 1)} disabled={page <= 1} className="rounded border border-slate-700 px-2 py-1 disabled:cursor-not-allowed disabled:opacity-40">Previous</button>
					<button type="button" onClick={() => goToPage(page + 1)} disabled={page >= totalPages} className="rounded border border-slate-700 px-2 py-1 disabled:cursor-not-allowed disabled:opacity-40">Next</button>
					<button type="button" onClick={() => goToPage(totalPages)} disabled={page >= totalPages} className="rounded border border-slate-700 px-2 py-1 disabled:cursor-not-allowed disabled:opacity-40">Last</button>
				</div>
			</nav>
		</div>
	);
}
