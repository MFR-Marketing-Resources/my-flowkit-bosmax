import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, Layers3, PackageCheck, RefreshCw, ShieldCheck, Sparkles } from "lucide-react";
import {
	buildV3ProductionManifest,
	fetchV3ProductionCapacity,
	freezeV3ProductionManifest,
	type V3ProductionCapacity,
	type V3ProductionManifestResponse,
} from "../../api/storyboardLandbankV3Round2";
import { Badge, FormField, HelperText, Section, TechnicalDetails } from "../ui";

export interface CopySupplyProduct {
	/** Product id — kept out of the primary UI; shown only in technical detail. */
	id: string;
	/** Human product name for the operator. */
	name: string;
	/** The page's production target (video_count) for this product, if any. */
	target: number;
}

export interface CopySupplyPanelProps {
	/** Products currently in context (draft allocations or the selected plan). */
	products: CopySupplyProduct[];
	/** Seed for the manifest duration input (the page's governed duration). */
	defaultDurationSeconds?: number;
	/** Campaign key threaded into the manifest request, if the page has one. */
	campaignKey?: string;
	/** Production plan id threaded into the manifest request, if a plan is bound. */
	productionPlanId?: string | null;
}

function describeError(error: unknown): string {
	if (!(error instanceof Error)) return "Copy Supply request failed.";
	const start = error.message.indexOf("{");
	if (start >= 0) {
		try {
			const payload = JSON.parse(error.message.slice(start)) as {
				detail?: { code?: string; message?: string };
			};
			const detail = payload?.detail;
			if (detail?.code && detail?.message) return `${detail.code}: ${detail.message}`;
		} catch {
			// Fall through to the raw transport message.
		}
	}
	return error.message;
}

function landbankHref(productId: string): string {
	return `/creative/storyboard-landbank-v3?product_id=${encodeURIComponent(productId)}`;
}

function fillCapacityHref(productId: string, shortfall: number): string {
	// Routes the human to the V3 assistant on the Copy Register (FILL_CAPACITY is
	// one of its plan modes). This link NEVER generates or approves anything — it
	// only carries the gap as context for a human-driven run.
	return `${landbankHref(productId)}&mode=FILL_CAPACITY&needed=${Math.max(0, shortfall)}`;
}

interface CapacityTierProps {
	label: string;
	value: number | undefined;
	tone?: "neutral" | "accent";
	testId: string;
}

function CapacityTier({ label, value, tone = "neutral", testId }: CapacityTierProps) {
	return (
		<div
			data-testid={testId}
			className={`rounded-xl border p-3 ${
				tone === "accent"
					? "border-cyan-500/30 bg-cyan-500/5"
					: "border-slate-800 bg-slate-950/40"
			}`}
		>
			<div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
				{label}
			</div>
			<div className="mt-1 text-xl font-bold tabular-nums text-slate-100">
				{value == null ? "—" : value}
			</div>
		</div>
	);
}

/**
 * Copy Supply — a read-first view of the FOUR-tier V3 copy capacity for a
 * product (Approved semantic -> Projections -> Executable copy -> Production
 * capacity, plus a stale count) and the DRAFT/FROZEN production manifest built
 * from it. It never generates or approves copy; when supply is short it only
 * routes the operator to the human-driven assistant / materialize surfaces.
 */
export default function CopySupplyPanel({
	products,
	defaultDurationSeconds,
	campaignKey,
	productionPlanId,
}: CopySupplyPanelProps) {
	const [activeProductId, setActiveProductId] = useState<string>(
		products[0]?.id ?? "",
	);
	const activeProduct = useMemo(
		() => products.find((product) => product.id === activeProductId) ?? products[0] ?? null,
		[products, activeProductId],
	);

	const [capacity, setCapacity] = useState<V3ProductionCapacity | null>(null);
	const [capacityLoading, setCapacityLoading] = useState(false);
	const [capacityError, setCapacityError] = useState("");

	const [target, setTarget] = useState<number>(products[0]?.target ?? 0);
	const [duration, setDuration] = useState<number>(defaultDurationSeconds ?? 8);

	const [manifest, setManifest] = useState<V3ProductionManifestResponse | null>(null);
	const [manifestBusy, setManifestBusy] = useState(false);
	const [manifestError, setManifestError] = useState("");

	const capacitySequence = useRef(0);

	// Keep the active product valid as the product set changes underneath us.
	useEffect(() => {
		if (!products.length) {
			if (activeProductId !== "") setActiveProductId("");
			return;
		}
		if (!products.some((product) => product.id === activeProductId)) {
			setActiveProductId(products[0].id);
		}
	}, [products, activeProductId]);

	const loadCapacity = useCallback(async (productId: string) => {
		if (!productId) {
			setCapacity(null);
			return;
		}
		const sequence = ++capacitySequence.current;
		setCapacityLoading(true);
		setCapacityError("");
		try {
			const result = await fetchV3ProductionCapacity(productId);
			if (sequence !== capacitySequence.current) return;
			setCapacity(result);
		} catch (error) {
			if (sequence !== capacitySequence.current) return;
			setCapacity(null);
			setCapacityError(describeError(error));
		} finally {
			if (sequence === capacitySequence.current) setCapacityLoading(false);
		}
	}, []);

	// On product change: reset the per-product target/duration seeds, drop the
	// stale manifest (a manifest is bound to one product), and reload capacity.
	useEffect(() => {
		if (!activeProduct) {
			setCapacity(null);
			setManifest(null);
			return;
		}
		setTarget(activeProduct.target ?? 0);
		setDuration(defaultDurationSeconds ?? 8);
		setManifest(null);
		setManifestError("");
		void loadCapacity(activeProduct.id);
		// defaultDurationSeconds intentionally NOT a dependency: operator edits to
		// the duration input must not be clobbered by parent re-renders.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [activeProduct?.id, loadCapacity]);

	const executable = capacity?.executable_copy_capacity ?? 0;
	// Required vs available: the copy shortfall the operator must still close.
	const shortfall = capacity ? Math.max(0, target - executable) : 0;

	const manifestStatus = manifest?.manifest.status ?? "NONE";
	const canFreeze =
		!!manifest &&
		manifest.manifest.status === "DRAFT" &&
		manifest.valid_count >= 1 &&
		!manifestBusy;

	const buildManifest = useCallback(async () => {
		if (!activeProduct) return;
		setManifestBusy(true);
		setManifestError("");
		try {
			const response = await buildV3ProductionManifest({
				productId: activeProduct.id,
				requestedCapacity: target,
				durationSeconds: duration,
				campaignKey: campaignKey || undefined,
				productionPlanId: productionPlanId || undefined,
			});
			setManifest(response);
		} catch (error) {
			setManifestError(describeError(error));
		} finally {
			setManifestBusy(false);
		}
	}, [activeProduct, target, duration, campaignKey, productionPlanId]);

	const freezeManifest = useCallback(async () => {
		if (!manifest || manifest.manifest.status !== "DRAFT") return;
		setManifestBusy(true);
		setManifestError("");
		try {
			const frozen = await freezeV3ProductionManifest({
				manifestId: manifest.manifest.manifest_id,
				revision: manifest.manifest.revision,
			});
			setManifest((current) =>
				current ? { ...current, manifest: frozen.manifest } : current,
			);
		} catch (error) {
			setManifestError(describeError(error));
		} finally {
			setManifestBusy(false);
		}
	}, [manifest]);

	if (!products.length || !activeProduct) {
		return (
			<Section
				title="Copy Supply"
				helper="Four-tier V3 copy capacity and the production manifest built from it."
			>
				<div
					data-testid="copy-supply-empty"
					className="rounded-xl border border-dashed border-slate-800 bg-slate-950/40 p-4 text-xs text-slate-400"
				>
					Select a product (choose products or open a plan) to review its copy
					supply.
				</div>
			</Section>
		);
	}

	const manifestTone =
		manifestStatus === "FROZEN"
			? "success"
			: manifestStatus === "DRAFT"
				? "info"
				: "neutral";

	return (
		<Section
			step={<Layers3 size={12} />}
			title="Copy Supply"
			helper="Read the four-tier copy capacity, size the manifest against your target, then freeze the supply. This panel never generates or approves copy."
			action={
				<Badge tone={manifestTone as "success" | "info" | "neutral"}>
					Manifest: {manifestStatus}
				</Badge>
			}
			className="mt-4"
		>
			<div data-testid="copy-supply-panel" className="space-y-4">
				{products.length > 1 ? (
					<FormField
						label="Product"
						htmlFor="copy-supply-product"
						helper="Copy capacity is per product; pick which one to review."
					>
						<select
							id="copy-supply-product"
							aria-label="Copy Supply product"
							value={activeProductId}
							onChange={(event) => setActiveProductId(event.target.value)}
							className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
						>
							{products.map((product) => (
								<option key={product.id} value={product.id}>
									{product.name}
								</option>
							))}
						</select>
					</FormField>
				) : (
					<div className="text-sm font-semibold text-slate-200">
						{activeProduct.name}
					</div>
				)}

				{capacityError ? (
					<HelperText tone="danger">Capacity unavailable — {capacityError}</HelperText>
				) : null}

				{/* Four-tier capacity + stale count. */}
				<div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
					<CapacityTier
						testId="copy-supply-tier-semantic"
						label="Approved (semantic)"
						value={capacity?.semantic_capacity}
					/>
					<CapacityTier
						testId="copy-supply-tier-projection"
						label="Projections"
						value={capacity?.projection_capacity}
					/>
					<CapacityTier
						testId="copy-supply-tier-executable"
						label="Executable copy"
						value={capacity?.executable_copy_capacity}
						tone="accent"
					/>
					<CapacityTier
						testId="copy-supply-tier-production"
						label="Production capacity"
						value={capacity?.production_capacity}
					/>
					<CapacityTier
						testId="copy-supply-tier-stale"
						label="Stale copy"
						value={capacity?.stale_copy_count}
					/>
				</div>
				<HelperText>
					<span className="text-slate-400">Executable copy</span> is V2
					production-valid supply. {capacityLoading ? "Loading capacity… " : ""}
					{capacity?.production_capacity_note ? (
						<span data-testid="copy-supply-capacity-note">
							{capacity.production_capacity_note}
						</span>
					) : (
						<span data-testid="copy-supply-capacity-note">
							Production capacity is not a Cartesian guarantee — it reflects
							executable supply, not target × duration combinations.
						</span>
					)}
				</HelperText>

				{/* Required vs available. */}
				<div className="grid gap-3 rounded-xl border border-slate-800 bg-slate-950/40 p-3 sm:grid-cols-3">
					<FormField
						label="Required copy capacity"
						htmlFor="copy-supply-target"
						helper="Defaults to this product's production target."
					>
						<input
							id="copy-supply-target"
							aria-label="Required copy capacity"
							type="number"
							min={0}
							value={target}
							onChange={(event) =>
								setTarget(Math.max(0, Math.trunc(Number(event.target.value) || 0)))
							}
							className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
						/>
					</FormField>
					<FormField
						label="Duration (seconds)"
						htmlFor="copy-supply-duration"
						helper="Threaded into the manifest request."
					>
						<input
							id="copy-supply-duration"
							aria-label="Copy Supply duration seconds"
							type="number"
							min={1}
							value={duration}
							onChange={(event) =>
								setDuration(Math.max(1, Math.trunc(Number(event.target.value) || 1)))
							}
							className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
						/>
					</FormField>
					<div className="space-y-1">
						<div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Shortfall
						</div>
						<div
							data-testid="copy-supply-shortfall"
							className={`text-xl font-bold tabular-nums ${
								shortfall > 0 ? "text-amber-300" : "text-emerald-300"
							}`}
						>
							{shortfall}
						</div>
						<HelperText>
							max(0, required − executable) = max(0, {target} − {executable}).
						</HelperText>
					</div>
				</div>

				{/* Manifest actions + status. */}
				<div className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/40 p-3">
					<div className="flex flex-wrap items-center gap-2">
						<button
							type="button"
							data-testid="copy-supply-build-manifest"
							onClick={() => void buildManifest()}
							disabled={manifestBusy || capacityLoading}
							className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-40"
						>
							<RefreshCw size={13} />
							Build / Refresh Manifest
						</button>
						<button
							type="button"
							data-testid="copy-supply-freeze-manifest"
							onClick={() => void freezeManifest()}
							disabled={!canFreeze}
							className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-200 disabled:opacity-40"
						>
							<ShieldCheck size={13} />
							Freeze Manifest
						</button>
						<span
							data-testid="copy-supply-manifest-status"
							className="text-[11px] font-semibold text-slate-400"
						>
							Status: {manifestStatus}
						</span>
					</div>

					{manifestError ? (
						<HelperText tone="danger">{manifestError}</HelperText>
					) : null}

					{manifest ? (
						<div className="space-y-2" data-testid="copy-supply-manifest-result">
							<div className="flex flex-wrap gap-2 text-[11px]">
								<Badge tone="info">
									<span data-testid="copy-supply-selected-count">
										Selected {manifest.selected_count}
									</span>
								</Badge>
								<Badge tone="success">Valid {manifest.valid_count}</Badge>
								<Badge tone={manifest.blocked_count > 0 ? "warn" : "neutral"}>
									<span data-testid="copy-supply-blocked-count">
										Blocked {manifest.blocked_count}
									</span>
								</Badge>
								<Badge tone={manifest.shortfall > 0 ? "warn" : "neutral"}>
									Manifest shortfall {manifest.shortfall}
								</Badge>
								<Badge tone="neutral">Reuse: {manifest.reuse_policy}</Badge>
							</div>
							{manifest.blocked.length ? (
								<ul
									data-testid="copy-supply-blocked-reasons"
									className="space-y-1 text-[11px] text-amber-200/90"
								>
									{manifest.blocked.map((entry, index) => (
										<li key={`${entry.projection_id}-${index}`}>
											{entry.reason}
										</li>
									))}
								</ul>
							) : null}
							<TechnicalDetails testId="copy-supply-technical-details">
								<dl className="space-y-1 font-mono text-[10px] text-slate-400">
									<div>manifest_id: {manifest.manifest.manifest_id}</div>
									<div>revision: {manifest.manifest.revision}</div>
									<div>status: {manifest.manifest.status}</div>
									<div>digest: {manifest.manifest.manifest_digest}</div>
									<div>product_id: {activeProduct.id}</div>
								</dl>
							</TechnicalDetails>
						</div>
					) : (
						<HelperText>
							No manifest yet — build one to select executable copy for
							production.
						</HelperText>
					)}
				</div>

				{/* Review / materialize / fill-capacity routing (no generation here). */}
				<div className="space-y-2">
					<div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
						Review supply
					</div>
					<div className="flex flex-wrap items-center gap-2 text-xs">
						<a
							href={landbankHref(activeProduct.id)}
							data-testid="copy-supply-open-register"
							className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-slate-300 hover:border-slate-500"
						>
							<BookOpen size={13} /> Open Copy Register
						</a>
						<a
							href={landbankHref(activeProduct.id)}
							data-testid="copy-supply-materialize"
							className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-slate-300 hover:border-slate-500"
						>
							<PackageCheck size={13} /> Materialize Approved Copy
						</a>
						{shortfall > 0 ? (
							<a
								href={fillCapacityHref(activeProduct.id, shortfall)}
								data-testid="copy-supply-fill-capacity"
								className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 font-semibold text-amber-200 hover:border-amber-400"
							>
								<Sparkles size={13} /> Fill Capacity ({shortfall})
							</a>
						) : null}
					</div>
					{shortfall > 0 ? (
						<HelperText tone="warn">
							Fill Capacity only opens the AI Copy Assistant with the gap as
							context. It never auto-generates or auto-approves — new copy still
							needs human approval and materialization before it counts as
							production capacity.
						</HelperText>
					) : null}
				</div>
			</div>
		</Section>
	);
}
