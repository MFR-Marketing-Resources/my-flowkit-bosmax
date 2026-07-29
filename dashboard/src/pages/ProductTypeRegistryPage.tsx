import { RefreshCw, Search, Tags } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
	fetchCatalogAuthorityReport,
	fetchProductStrategyTypeRegistry,
	fetchProductTypeCopyEligibleReport,
	registerProductStrategyType,
} from "../api/products";
import type {
	CatalogAuthorityReport,
	CatalogAuthorityTerminalState,
	ProductStrategyTypeRegistrationRequest,
	ProductStrategyTypeRegistryEntry,
	ProductStrategyTypeRegistryResponse,
	ProductTypeCopyEligibleReport,
	ProductTypeCopyReportProduct,
} from "../types";

type CoverageStatus =
	ProductStrategyTypeRegistrationRequest["scene_coverage_status"];
type RegistryStatus = ProductStrategyTypeRegistrationRequest["registry_status"];
type RegistrationForm = Omit<
	ProductStrategyTypeRegistrationRequest,
	"auto_classification_enabled"
>;

interface CopyStrategyEvidence {
	eligibleCount: number;
	missingStrategyCount: number;
	sampleEligible: ProductTypeCopyReportProduct | null;
}

const EMPTY_REGISTRY: ProductStrategyTypeRegistryResponse = {
	items: [],
	clusters: [],
	scene_strategy_ids: [],
};
const INPUT_CLASS =
	"mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-blue-500 focus:ring-1 focus:ring-blue-500/40";
const PRODUCT_TYPE_PATTERN = /^[a-z][a-z0-9_]*$/;

function tupleKey(
	cluster: string,
	productTypeGroup: string,
	sceneStrategyId: string,
) {
	return `${cluster}\u0000${productTypeGroup}\u0000${sceneStrategyId}`;
}

function initialForm(cluster = "", sceneStrategyId = ""): RegistrationForm {
	const matchedSceneStrategyId = sceneStrategyId || "GENERIC_FALLBACK";
	const fallback = matchedSceneStrategyId === "GENERIC_FALLBACK";
	return {
		cluster,
		product_type_group: "",
		display_name: "",
		matched_scene_strategy_id: matchedSceneStrategyId,
		scene_coverage_status: fallback ? "FALLBACK_ONLY" : "COVERED",
		registry_status: fallback ? "REVIEW_REQUIRED" : "ACTIVE",
		reviewer_id: "",
		reviewer_note: "",
	};
}

function formatTimestamp(value: string | null | undefined) {
	if (!value) return "Not recorded";
	const parsed = new Date(value);
	return Number.isNaN(parsed.getTime())
		? value
		: parsed.toLocaleString(undefined, {
				dateStyle: "medium",
				timeStyle: "short",
			});
}

function statusClass(status: RegistryStatus) {
	return status === "ACTIVE"
		? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
		: "border-amber-500/30 bg-amber-500/10 text-amber-300";
}

function coverageClass(status: CoverageStatus) {
	if (status === "COVERED")
		return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
	if (status === "PARTIAL")
		return "border-amber-500/30 bg-amber-500/10 text-amber-300";
	return "border-slate-600 bg-slate-800/70 text-slate-300";
}

function terminalStateClass(status: CatalogAuthorityTerminalState) {
	if (status === "P6_READY")
		return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
	if (status === "REVIEW_BLOCKED_WITH_EXACT_REASON")
		return "border-amber-500/30 bg-amber-500/10 text-amber-300";
	if (status === "INSUFFICIENT_PRODUCT_TRUTH")
		return "border-rose-500/30 bg-rose-500/10 text-rose-300";
	return "border-slate-600 bg-slate-800/70 text-slate-300";
}

export default function ProductTypeRegistryPage() {
	const [registry, setRegistry] =
		useState<ProductStrategyTypeRegistryResponse>(EMPTY_REGISTRY);
	const [copyReport, setCopyReport] =
		useState<ProductTypeCopyEligibleReport | null>(null);
	const [authorityReport, setAuthorityReport] =
		useState<CatalogAuthorityReport | null>(null);
	const [loading, setLoading] = useState(true);
	const [copyReportLoading, setCopyReportLoading] = useState(true);
	const [authorityLoading, setAuthorityLoading] = useState(true);
	const [registryError, setRegistryError] = useState<string | null>(null);
	const [copyReportError, setCopyReportError] = useState<string | null>(null);
	const [authorityError, setAuthorityError] = useState<string | null>(null);
	const [search, setSearch] = useState("");
	const [clusterFilter, setClusterFilter] = useState("ALL");
	const [statusFilter, setStatusFilter] = useState("ALL");
	const [coverageFilter, setCoverageFilter] = useState("ALL");
	const [sceneFilter, setSceneFilter] = useState("ALL");
	const [form, setForm] = useState<RegistrationForm>(() => initialForm());
	const [saving, setSaving] = useState(false);
	const [createError, setCreateError] = useState<string | null>(null);
	const [createSuccess, setCreateSuccess] = useState<string | null>(null);

	const loadRegistry = useCallback(async () => {
		setLoading(true);
		setRegistryError(null);
		try {
			const response = await fetchProductStrategyTypeRegistry();
			setRegistry(response);
			const firstConcreteCluster =
				response.clusters.find(
					(cluster) => cluster !== "generic_unclassified",
				) ?? "";
			const firstSceneStrategy =
				response.scene_strategy_ids.find(
					(sceneStrategyId) => sceneStrategyId !== "GENERIC_FALLBACK",
				) ??
				response.scene_strategy_ids[0] ??
				"";
			setForm((current) =>
				current.cluster
					? current
					: initialForm(firstConcreteCluster, firstSceneStrategy),
			);
		} catch (error) {
			setRegistryError(
				error instanceof Error
					? error.message
					: "Failed to load the Product Type Registry.",
			);
		} finally {
			setLoading(false);
		}
	}, []);

	const loadCopyReport = useCallback(async () => {
		setCopyReportLoading(true);
		setCopyReportError(null);
		try {
			setCopyReport(await fetchProductTypeCopyEligibleReport());
		} catch (error) {
			setCopyReport(null);
			setCopyReportError(
				error instanceof Error
					? error.message
					: "P4 eligibility context is unavailable.",
			);
		} finally {
			setCopyReportLoading(false);
		}
	}, []);

	const loadAuthorityReport = useCallback(async () => {
		setAuthorityLoading(true);
		setAuthorityError(null);
		try {
			setAuthorityReport(await fetchCatalogAuthorityReport());
		} catch (error) {
			setAuthorityReport(null);
			setAuthorityError(
				error instanceof Error
					? error.message
					: "P5.8 final catalog authority is unavailable.",
			);
		} finally {
			setAuthorityLoading(false);
		}
	}, []);

	useEffect(() => {
		void loadRegistry();
		void loadCopyReport();
		void loadAuthorityReport();
	}, [loadAuthorityReport, loadCopyReport, loadRegistry]);

	const concreteClusters = useMemo(
		() =>
			registry.clusters.filter((cluster) => cluster !== "generic_unclassified"),
		[registry.clusters],
	);

	const filteredItems = useMemo(() => {
		const normalizedSearch = search.trim().toLocaleLowerCase();
		return registry.items.filter((item) => {
			if (clusterFilter !== "ALL" && item.cluster !== clusterFilter)
				return false;
			if (statusFilter !== "ALL" && item.registry_status !== statusFilter)
				return false;
			if (
				coverageFilter !== "ALL" &&
				item.scene_coverage_status !== coverageFilter
			)
				return false;
			if (
				sceneFilter !== "ALL" &&
				item.matched_scene_strategy_id !== sceneFilter
			)
				return false;
			if (!normalizedSearch) return true;
			return [
				item.cluster,
				item.product_type_group,
				item.display_name,
				item.matched_scene_strategy_id,
				item.registry_status,
				item.scene_coverage_status,
			].some((value) => value.toLocaleLowerCase().includes(normalizedSearch));
		});
	}, [
		clusterFilter,
		coverageFilter,
		registry.items,
		sceneFilter,
		search,
		statusFilter,
	]);

	const groupedItems = useMemo(() => {
		const groups = new Map<string, ProductStrategyTypeRegistryEntry[]>();
		for (const item of filteredItems) {
			groups.set(item.cluster, [...(groups.get(item.cluster) ?? []), item]);
		}
		const clusterOrder = new Map(
			registry.clusters.map((cluster, index) => [cluster, index]),
		);
		return [...groups.entries()].sort(
			([left], [right]) =>
				(clusterOrder.get(left) ?? Number.MAX_SAFE_INTEGER) -
					(clusterOrder.get(right) ?? Number.MAX_SAFE_INTEGER) ||
				left.localeCompare(right),
		);
	}, [filteredItems, registry.clusters]);

	const copyEvidence = useMemo(() => {
		const evidence = new Map<string, CopyStrategyEvidence>();
		if (!copyReport) return evidence;
		for (const item of copyReport.eligible_by_product_type) {
			evidence.set(
				tupleKey(item.cluster, item.product_type_group, item.scene_strategy_id),
				{
					eligibleCount: item.count,
					missingStrategyCount: 0,
					sampleEligible: null,
				},
			);
		}
		for (const item of copyReport.missing_copy_strategy_groups) {
			const key = tupleKey(
				item.cluster,
				item.product_type_group,
				item.scene_strategy_id,
			);
			const current = evidence.get(key);
			evidence.set(key, {
				eligibleCount: current?.eligibleCount ?? 0,
				missingStrategyCount: item.count,
				sampleEligible: current?.sampleEligible ?? null,
			});
		}
		for (const product of copyReport.sample_eligible) {
			const key = tupleKey(
				product.cluster,
				product.product_type_group,
				product.scene_strategy_id,
			);
			const current = evidence.get(key) ?? {
				eligibleCount: 0,
				missingStrategyCount: 0,
				sampleEligible: null,
			};
			if (!current.sampleEligible) {
				evidence.set(key, { ...current, sampleEligible: product });
			}
		}
		return evidence;
	}, [copyReport]);

	const activeCount = registry.items.filter(
		(item) => item.registry_status === "ACTIVE",
	).length;
	const reviewRequiredCount = registry.items.length - activeCount;
	const terminalExceptions = useMemo(
		() =>
			(authorityReport?.products ?? []).filter(
				(product) =>
					product.lifecycle_status === "ACTIVE" &&
					product.terminal_state !== "P6_READY",
			),
		[authorityReport],
	);

	function updateSceneStrategy(matchedSceneStrategyId: string) {
		setForm((current) => {
			const fallback = matchedSceneStrategyId === "GENERIC_FALLBACK";
			return {
				...current,
				matched_scene_strategy_id: matchedSceneStrategyId,
				scene_coverage_status: fallback
					? "FALLBACK_ONLY"
					: current.scene_coverage_status === "FALLBACK_ONLY"
						? "COVERED"
						: current.scene_coverage_status,
				registry_status: fallback ? "REVIEW_REQUIRED" : current.registry_status,
			};
		});
	}

	async function handleRegister(event: React.FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setCreateError(null);
		setCreateSuccess(null);
		const productTypeGroup = form.product_type_group.trim();
		const displayName = form.display_name.trim();
		const reviewerId = form.reviewer_id.trim();
		const reviewerNote = form.reviewer_note.trim();
		if (
			!form.cluster ||
			!productTypeGroup ||
			!displayName ||
			!form.matched_scene_strategy_id ||
			!reviewerId ||
			!reviewerNote
		) {
			setCreateError("Complete every required registration field.");
			return;
		}
		if (!PRODUCT_TYPE_PATTERN.test(productTypeGroup)) {
			setCreateError(
				"Product type group must start with a lowercase letter and use only lowercase letters, numbers, or underscores.",
			);
			return;
		}
		setSaving(true);
		try {
			const created = await registerProductStrategyType({
				...form,
				product_type_group: productTypeGroup,
				display_name: displayName,
				auto_classification_enabled: false,
				reviewer_id: reviewerId,
				reviewer_note: reviewerNote,
			});
			setCreateSuccess(
				`Registered ${created.cluster} / ${created.product_type_group} as ${created.registry_status}.`,
			);
			setForm((current) => ({
				...initialForm(current.cluster, current.matched_scene_strategy_id),
				reviewer_id: current.reviewer_id,
			}));
			await loadRegistry();
		} catch (error) {
			setCreateError(
				error instanceof Error
					? error.message
					: "Product type registration failed.",
			);
		} finally {
			setSaving(false);
		}
	}

	function resetFilters() {
		setSearch("");
		setClusterFilter("ALL");
		setStatusFilter("ALL");
		setCoverageFilter("ALL");
		setSceneFilter("ALL");
	}

	return (
		<div
			className="mx-auto max-w-7xl space-y-6 p-4 md:p-8"
			data-testid="product-type-registry-page"
		>
			<header className="flex flex-col gap-4 border-b border-slate-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
				<div>
					<div className="flex items-center gap-3">
						<div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-2 text-blue-300">
							<Tags size={20} aria-hidden="true" />
						</div>
						<h1 className="text-2xl font-bold text-slate-100">
							Product Type Registry
						</h1>
					</div>
					<p className="mt-2 max-w-3xl text-sm text-slate-400">
						Manage the official cluster → product type → scene strategy binding.
						Registration changes this registry only; it does not verify or
						approve any product taxonomy.
					</p>
				</div>
				<button
					type="button"
					onClick={() => {
						void loadRegistry();
						void loadCopyReport();
						void loadAuthorityReport();
					}}
					disabled={loading}
					className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm font-semibold text-slate-200 transition hover:border-blue-500/60 hover:text-blue-200 disabled:cursor-not-allowed disabled:opacity-50"
				>
					<RefreshCw size={15} aria-hidden="true" />
					Refresh registry
				</button>
			</header>

			<section
				aria-label="Registry summary"
				className="grid gap-px overflow-hidden rounded-xl border border-slate-800 bg-slate-800 sm:grid-cols-2 lg:grid-cols-4"
			>
				{[
					["Registered rows", registry.items.length],
					["Active rows", activeCount],
					["Review required", reviewRequiredCount],
					[
						"P4 eligible products",
						copyReportLoading
							? "Loading"
							: copyReport
								? copyReport.eligible_count
								: "Unavailable",
					],
				].map(([label, value]) => (
					<div key={label} className="bg-slate-950 px-4 py-3">
						<div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
							{label}
						</div>
						<div className="mt-1 text-xl font-bold text-slate-100">{value}</div>
					</div>
				))}
			</section>

			<section
				aria-label="Final catalog authority"
				className="space-y-4 rounded-xl border border-slate-800 bg-slate-950 p-4"
				data-testid="catalog-authority-summary"
			>
				<div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
					<div>
						<h2 className="text-sm font-bold uppercase tracking-wider text-slate-200">
							P5.8 Final Catalog Authority
						</h2>
						<p className="mt-1 text-xs text-slate-500">
							One terminal state per product. P6 cohort is frozen here; P6 has
							not started.
						</p>
					</div>
					{authorityReport && (
						<div className="font-mono text-[10px] text-slate-500">
							Matrix {authorityReport.matrix_sha256.slice(0, 16)}…
						</div>
					)}
				</div>
				<div className="grid gap-px overflow-hidden rounded-lg border border-slate-800 bg-slate-800 sm:grid-cols-2 xl:grid-cols-5">
					{[
						[
							"Catalog products",
							authorityLoading
								? "Loading"
								: (authorityReport?.total_products ?? "Unavailable"),
						],
						[
							"P6 ready",
							authorityReport?.terminal_state_counts.P6_READY ?? "—",
						],
						[
							"Review blocked",
							authorityReport?.terminal_state_counts
								.REVIEW_BLOCKED_WITH_EXACT_REASON ?? "—",
						],
						[
							"Insufficient truth",
							authorityReport?.terminal_state_counts
								.INSUFFICIENT_PRODUCT_TRUTH ?? "—",
						],
						[
							"Archived",
							authorityReport?.terminal_state_counts.ARCHIVED_NOT_IN_SCOPE ??
								"—",
						],
					].map(([label, value]) => (
						<div key={label} className="bg-slate-950 px-4 py-3">
							<div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
								{label}
							</div>
							<div className="mt-1 text-lg font-bold text-slate-100">
								{value}
							</div>
						</div>
					))}
				</div>
				{authorityError && (
					<div
						className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200"
						data-testid="catalog-authority-warning"
					>
						Registry remains available. Final authority report could not be
						loaded: {authorityError}
					</div>
				)}
				{authorityReport && terminalExceptions.length > 0 && (
					<div className="space-y-2" data-testid="catalog-terminal-exceptions">
						<div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
							Active terminal exceptions ({terminalExceptions.length})
						</div>
						<div className="grid gap-2 lg:grid-cols-2">
							{terminalExceptions.map((product) => (
								<div
									key={product.product_id}
									className="rounded-lg border border-slate-800 bg-slate-900/60 p-3"
									data-testid={`terminal-product-${product.product_id}`}
								>
									<div className="flex flex-wrap items-center gap-2">
										<span
											className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${terminalStateClass(product.terminal_state)}`}
										>
											{product.terminal_state}
										</span>
										<span className="text-[10px] font-semibold text-slate-500">
											{product.mapping_provenance}
										</span>
									</div>
									<div className="mt-2 text-sm font-semibold text-slate-100">
										{product.product_name}
									</div>
									<div className="mt-1 font-mono text-[11px] text-slate-500">
										{product.cluster} / {product.product_type_group}
									</div>
									<div className="mt-2 text-xs text-slate-400">
										{product.terminal_reasons.join(" · ")}
									</div>
								</div>
							))}
						</div>
					</div>
				)}
			</section>

			{copyReportError && (
				<div
					className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200"
					data-testid="p4-report-warning"
				>
					Registry data remains available. P4 eligibility context could not be
					loaded: {copyReportError}
				</div>
			)}

			<section
				aria-label="Registry filters"
				className="border-y border-slate-800 py-4"
			>
				<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
					<label className="relative xl:col-span-2">
						<span className="text-xs font-semibold text-slate-400">
							Search product types
						</span>
						<Search
							size={15}
							aria-hidden="true"
							className="pointer-events-none absolute bottom-2.5 left-3 text-slate-500"
						/>
						<input
							aria-label="Search product types"
							value={search}
							onChange={(event) => setSearch(event.target.value)}
							placeholder="Cluster, type, display name, or scene strategy"
							className={`${INPUT_CLASS} pl-9`}
						/>
					</label>
					<label>
						<span className="text-xs font-semibold text-slate-400">
							Cluster
						</span>
						<select
							aria-label="Filter by cluster"
							value={clusterFilter}
							onChange={(event) => setClusterFilter(event.target.value)}
							className={INPUT_CLASS}
						>
							<option value="ALL">All clusters</option>
							{registry.clusters.map((cluster) => (
								<option key={cluster} value={cluster}>
									{cluster}
								</option>
							))}
						</select>
					</label>
					<label>
						<span className="text-xs font-semibold text-slate-400">
							Registry status
						</span>
						<select
							aria-label="Filter by registry status"
							value={statusFilter}
							onChange={(event) => setStatusFilter(event.target.value)}
							className={INPUT_CLASS}
						>
							<option value="ALL">All statuses</option>
							<option value="ACTIVE">Active</option>
							<option value="REVIEW_REQUIRED">Review required</option>
						</select>
					</label>
					<label>
						<span className="text-xs font-semibold text-slate-400">
							Coverage
						</span>
						<select
							aria-label="Filter by coverage status"
							value={coverageFilter}
							onChange={(event) => setCoverageFilter(event.target.value)}
							className={INPUT_CLASS}
						>
							<option value="ALL">All coverage</option>
							<option value="COVERED">Covered</option>
							<option value="PARTIAL">Partial</option>
							<option value="FALLBACK_ONLY">Fallback only</option>
						</select>
					</label>
					<label>
						<span className="text-xs font-semibold text-slate-400">
							Scene strategy
						</span>
						<select
							aria-label="Filter by scene strategy"
							value={sceneFilter}
							onChange={(event) => setSceneFilter(event.target.value)}
							className={INPUT_CLASS}
						>
							<option value="ALL">All scene strategies</option>
							{registry.scene_strategy_ids.map((sceneStrategyId) => (
								<option key={sceneStrategyId} value={sceneStrategyId}>
									{sceneStrategyId}
								</option>
							))}
						</select>
					</label>
				</div>
				<div className="mt-3 flex items-center justify-between gap-3 text-xs text-slate-500">
					<span data-testid="filtered-row-count">
						Showing {filteredItems.length} of {registry.items.length} rows
					</span>
					<button
						type="button"
						onClick={resetFilters}
						className="font-semibold text-blue-300 hover:text-blue-200"
					>
						Clear filters
					</button>
				</div>
			</section>

			{loading && registry.items.length === 0 ? (
				<div
					className="rounded-xl border border-slate-800 px-4 py-12 text-center text-sm text-slate-400"
					data-testid="registry-loading-state"
				>
					Loading Product Type Registry…
				</div>
			) : registryError ? (
				<div
					role="alert"
					className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-5 text-sm text-red-200"
					data-testid="registry-error-state"
				>
					<div>{registryError}</div>
					<button
						type="button"
						onClick={() => void loadRegistry()}
						className="mt-3 font-semibold underline underline-offset-2"
					>
						Retry registry load
					</button>
				</div>
			) : registry.items.length === 0 ? (
				<div
					className="rounded-xl border border-dashed border-slate-700 px-4 py-12 text-center"
					data-testid="registry-empty-state"
				>
					<div className="text-sm font-semibold text-slate-200">
						No product types are registered.
					</div>
					<div className="mt-1 text-xs text-slate-500">
						Use the official registration form below to create the first row.
					</div>
				</div>
			) : groupedItems.length === 0 ? (
				<div
					className="rounded-xl border border-dashed border-slate-700 px-4 py-12 text-center"
					data-testid="registry-filter-empty-state"
				>
					<div className="text-sm font-semibold text-slate-200">
						No registry rows match these filters.
					</div>
					<button
						type="button"
						onClick={resetFilters}
						className="mt-2 text-xs font-semibold text-blue-300"
					>
						Clear filters
					</button>
				</div>
			) : (
				<div className="space-y-6" data-testid="registry-groups">
					{groupedItems.map(([cluster, items]) => (
						<section
							key={cluster}
							aria-labelledby={`cluster-${cluster}`}
							data-testid={`registry-cluster-${cluster}`}
						>
							<div className="mb-2 flex items-center justify-between">
								<h2
									id={`cluster-${cluster}`}
									className="font-mono text-sm font-bold text-slate-200"
								>
									{cluster}
								</h2>
								<span className="text-xs text-slate-500">
									{items.length} registered{" "}
									{items.length === 1 ? "type" : "types"}
								</span>
							</div>
							<div className="overflow-x-auto rounded-xl border border-slate-800">
								<table className="min-w-[1100px] w-full border-collapse text-left text-xs">
									<thead className="bg-slate-900/80 text-[10px] uppercase tracking-wider text-slate-500">
										<tr>
											{[
												"Cluster",
												"Product type group",
												"Scene strategy",
												"Registry",
												"Coverage",
												"P4 copy support",
												"Review metadata",
												"Products",
											].map((heading) => (
												<th key={heading} className="px-4 py-3 font-semibold">
													{heading}
												</th>
											))}
										</tr>
									</thead>
									<tbody className="divide-y divide-slate-800 bg-slate-950/50">
										{items.map((item) => {
											const evidence = copyEvidence.get(
												tupleKey(
													item.cluster,
													item.product_type_group,
													item.matched_scene_strategy_id,
												),
											);
											const sample = evidence?.sampleEligible;
											return (
												<tr
													key={`${item.cluster}:${item.product_type_group}`}
													data-testid={`registry-row-${item.product_type_group}`}
													className="align-top hover:bg-slate-900/40"
												>
													<td className="px-4 py-3 font-mono text-slate-400">
														{item.cluster}
													</td>
													<td className="px-4 py-3">
														<div className="font-semibold text-slate-100">
															{item.display_name}
														</div>
														<div className="mt-1 font-mono text-[11px] text-slate-500">
															{item.product_type_group}
														</div>
														<div className="mt-1 text-[10px] text-slate-600">
															{item.authority_source}
														</div>
													</td>
													<td className="px-4 py-3 font-mono text-slate-300">
														{item.matched_scene_strategy_id}
													</td>
													<td className="px-4 py-3">
														<span
															className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-bold ${statusClass(item.registry_status)}`}
														>
															{item.registry_status}
														</span>
														<div className="mt-2 text-[10px] text-slate-500">
															{item.auto_classification_enabled
																? "Classifier enabled"
																: "Manual registration only"}
														</div>
													</td>
													<td className="px-4 py-3">
														<span
															className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-bold ${coverageClass(item.scene_coverage_status)}`}
														>
															{item.scene_coverage_status}
														</span>
													</td>
													<td className="px-4 py-3">
														{copyReportLoading ? (
															<span className="text-slate-500">
																Loading P4 evidence…
															</span>
														) : evidence && evidence.eligibleCount > 0 ? (
															<>
																<div className="font-semibold text-emerald-300">
																	P4 supported
																</div>
																<div className="mt-1 text-slate-500">
																	{evidence.eligibleCount} eligible{" "}
																	{evidence.eligibleCount === 1
																		? "product"
																		: "products"}
																</div>
															</>
														) : evidence &&
															evidence.missingStrategyCount > 0 ? (
															<>
																<div className="font-semibold text-red-300">
																	P4 strategy not registered
																</div>
																<div className="mt-1 text-slate-500">
																	{evidence.missingStrategyCount} blocked by
																	missing strategy
																</div>
															</>
														) : (
															<>
																<div className="text-slate-400">
																	No catalog evidence
																</div>
																<div className="mt-1 text-[10px] text-slate-600">
																	The report exposes no per-type zero-count
																	support claim.
																</div>
															</>
														)}
													</td>
													<td className="px-4 py-3 text-slate-400">
														<div>{formatTimestamp(item.updated_at)}</div>
														<div className="mt-1 text-[10px] text-slate-600">
															{item.reviewer_id
																? `Reviewer: ${item.reviewer_id}`
																: "Seeded authority row"}
														</div>
													</td>
													<td className="px-4 py-3">
														<Link
															to={
																sample
																	? `/products?product=${encodeURIComponent(sample.product_id)}&tab=INTELLIGENCE`
																	: "/products"
															}
															className="font-semibold text-blue-300 hover:text-blue-200"
														>
															{sample
																? "Open eligible sample"
																: "Open Products"}
														</Link>
														{sample && (
															<div className="mt-1 max-w-44 truncate text-[10px] text-slate-600">
																{sample.product_name}
															</div>
														)}
													</td>
												</tr>
											);
										})}
									</tbody>
								</table>
							</div>
						</section>
					))}
				</div>
			)}

			<section
				aria-labelledby="register-product-type-heading"
				className="border-t border-slate-800 pt-6"
			>
				<div className="mb-4">
					<h2
						id="register-product-type-heading"
						className="text-lg font-bold text-slate-100"
					>
						Register a new product type
					</h2>
					<p className="mt-1 text-xs text-slate-500">
						Uses the official registry API. New rows never auto-classify,
						verify, or approve products.
					</p>
				</div>
				<form
					onSubmit={(event) => void handleRegister(event)}
					className="grid gap-4 md:grid-cols-2 xl:grid-cols-4"
					data-testid="product-type-registration-form"
				>
					<label>
						<span className="text-xs font-semibold text-slate-400">
							Existing cluster *
						</span>
						<select
							aria-label="Existing cluster"
							value={form.cluster}
							onChange={(event) =>
								setForm((current) => ({
									...current,
									cluster: event.target.value,
								}))
							}
							className={INPUT_CLASS}
							required
						>
							<option value="">Select cluster</option>
							{concreteClusters.map((cluster) => (
								<option key={cluster} value={cluster}>
									{cluster}
								</option>
							))}
						</select>
					</label>
					<label>
						<span className="text-xs font-semibold text-slate-400">
							Product type group *
						</span>
						<input
							aria-label="Product type group"
							value={form.product_type_group}
							onChange={(event) =>
								setForm((current) => ({
									...current,
									product_type_group: event.target.value,
								}))
							}
							placeholder="example_product_type"
							className={INPUT_CLASS}
							required
						/>
					</label>
					<label>
						<span className="text-xs font-semibold text-slate-400">
							Display name *
						</span>
						<input
							aria-label="Display name"
							value={form.display_name}
							onChange={(event) =>
								setForm((current) => ({
									...current,
									display_name: event.target.value,
								}))
							}
							placeholder="Example Product Type"
							className={INPUT_CLASS}
							required
						/>
					</label>
					<label>
						<span className="text-xs font-semibold text-slate-400">
							Scene strategy *
						</span>
						<select
							aria-label="Scene strategy"
							value={form.matched_scene_strategy_id}
							onChange={(event) => updateSceneStrategy(event.target.value)}
							className={INPUT_CLASS}
							required
						>
							{registry.scene_strategy_ids.map((sceneStrategyId) => (
								<option key={sceneStrategyId} value={sceneStrategyId}>
									{sceneStrategyId}
								</option>
							))}
						</select>
					</label>
					<label>
						<span className="text-xs font-semibold text-slate-400">
							Coverage status *
						</span>
						<select
							aria-label="Coverage status"
							value={form.scene_coverage_status}
							onChange={(event) =>
								setForm((current) => ({
									...current,
									scene_coverage_status: event.target.value as CoverageStatus,
								}))
							}
							className={INPUT_CLASS}
							disabled={form.matched_scene_strategy_id === "GENERIC_FALLBACK"}
						>
							<option value="COVERED">Covered</option>
							<option value="PARTIAL">Partial</option>
							<option value="FALLBACK_ONLY">Fallback only</option>
						</select>
					</label>
					<label>
						<span className="text-xs font-semibold text-slate-400">
							Registry status *
						</span>
						<select
							aria-label="Registry status"
							value={form.registry_status}
							onChange={(event) =>
								setForm((current) => ({
									...current,
									registry_status: event.target.value as RegistryStatus,
								}))
							}
							className={INPUT_CLASS}
							disabled={form.matched_scene_strategy_id === "GENERIC_FALLBACK"}
						>
							<option value="REVIEW_REQUIRED">Review required</option>
							<option value="ACTIVE">Active</option>
						</select>
					</label>
					<label>
						<span className="text-xs font-semibold text-slate-400">
							Reviewer ID *
						</span>
						<input
							aria-label="Reviewer ID"
							value={form.reviewer_id}
							onChange={(event) =>
								setForm((current) => ({
									...current,
									reviewer_id: event.target.value,
								}))
							}
							placeholder="operator-id"
							className={INPUT_CLASS}
							required
						/>
					</label>
					<label>
						<span className="text-xs font-semibold text-slate-400">
							Reviewer note *
						</span>
						<input
							aria-label="Reviewer note"
							value={form.reviewer_note}
							onChange={(event) =>
								setForm((current) => ({
									...current,
									reviewer_note: event.target.value,
								}))
							}
							placeholder="Reason for this binding"
							className={INPUT_CLASS}
							required
						/>
					</label>
					<div className="md:col-span-2 xl:col-span-4">
						{createError && (
							<div
								role="alert"
								className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200"
								data-testid="registration-error"
							>
								{createError}
							</div>
						)}
						{createSuccess && (
							<div
								role="status"
								className="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200"
								data-testid="registration-success"
							>
								{createSuccess}
							</div>
						)}
						<div className="flex flex-col gap-3 border-t border-slate-800 pt-4 sm:flex-row sm:items-center sm:justify-between">
							<p className="text-xs text-slate-500">
								Auto-classification is fixed to false for manual registrations.
							</p>
							<button
								type="submit"
								disabled={saving || loading || concreteClusters.length === 0}
								className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
							>
								{saving ? "Registering…" : "Register product type"}
							</button>
						</div>
					</div>
				</form>
			</section>
		</div>
	);
}
