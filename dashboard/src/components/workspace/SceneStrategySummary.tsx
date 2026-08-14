import type { ProductStrategyTaxonomy } from "../../types";

// Workflow Upgrade V1 (Creative Direction) — read-only Scene Strategy authority
// summary for the selected product. The catalog list already attaches
// strategy_taxonomy to every product row (attach_product_strategy_taxonomies);
// this surface only RENDERS that existing data. It never fetches, never writes,
// and deliberately does NOT offer a scene-variant selector (allowed_scene_strategy,
// actions and camera routes are not delivered to the UI before compilation).

export interface SceneStrategySummaryProps {
	hasProduct: boolean;
	productName?: string | null;
	taxonomy: ProductStrategyTaxonomy | null | undefined;
}

type SceneStrategySummaryState =
	| "NO_PRODUCT"
	| "ABSENT"
	| "STALE"
	| "FALLBACK_ONLY"
	| "REVIEW_REQUIRED"
	| "VERIFIED";

// Worst-condition-first summary state. The individual badges below always show
// every condition independently, so this ordering only picks the headline tone.
export function resolveSceneStrategySummaryState(
	hasProduct: boolean,
	taxonomy: ProductStrategyTaxonomy | null | undefined,
): SceneStrategySummaryState {
	if (!hasProduct) return "NO_PRODUCT";
	if (!taxonomy) return "ABSENT";
	if (taxonomy.is_stale) return "STALE";
	if (taxonomy.scene_coverage_status === "FALLBACK_ONLY" || taxonomy.fallback_used) {
		return "FALLBACK_ONLY";
	}
	if (
		taxonomy.review_status === "REVIEW_REQUIRED" ||
		taxonomy.consumer_status === "BLOCKED_REVIEW_REQUIRED"
	) {
		return "REVIEW_REQUIRED";
	}
	return "VERIFIED";
}

function Chip({
	label,
	tone,
	testId,
}: {
	label: string;
	tone: "ready" | "warn" | "risk" | "muted";
	testId?: string;
}) {
	const toneClass =
		tone === "ready"
			? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
			: tone === "warn"
				? "border-amber-500/30 bg-amber-500/10 text-amber-100"
				: tone === "risk"
					? "border-rose-500/40 bg-rose-500/10 text-rose-200"
					: "border-slate-700 bg-slate-900 text-slate-300";
	return (
		<span
			data-testid={testId}
			className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em] ${toneClass}`}
		>
			{label}
		</span>
	);
}

export default function SceneStrategySummary({
	hasProduct,
	productName,
	taxonomy,
}: SceneStrategySummaryProps) {
	const state = resolveSceneStrategySummaryState(hasProduct, taxonomy);

	return (
		<div
			data-testid="scene-strategy-summary"
			data-state={state}
			data-review-status={taxonomy?.review_status ?? ""}
			data-coverage-status={taxonomy?.scene_coverage_status ?? ""}
			data-consumer-status={taxonomy?.consumer_status ?? ""}
			data-stale={taxonomy ? String(taxonomy.is_stale) : ""}
			data-fallback-used={taxonomy ? String(taxonomy.fallback_used) : ""}
			data-scene-strategy-id={taxonomy?.matched_scene_strategy_id ?? ""}
			className="rounded-xl border border-slate-800 bg-slate-950/60 p-3"
		>
			<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
				Scene Strategy Authority
			</div>
			{state === "NO_PRODUCT" ? (
				<div className="mt-2 text-[11px] text-slate-400">
					Select a product in Step 1 to see its Scene Strategy ID and taxonomy
					status.
				</div>
			) : state === "ABSENT" ? (
				<div className="mt-2 text-[11px] text-amber-200">
					{productName ?? "This product"} has no Scene Strategy taxonomy row
					yet. Compilation will proceed without a matched scene strategy
					authority.
				</div>
			) : taxonomy ? (
				<div className="mt-2 space-y-2">
					<div className="text-xs font-semibold text-white">
						{taxonomy.matched_scene_strategy_id}
					</div>
					<div className="text-[11px] text-slate-400">
						{taxonomy.cluster} · {taxonomy.product_type_group} · confidence{" "}
						{taxonomy.classification_confidence} · {taxonomy.authority_source}
					</div>
					<div className="flex flex-wrap gap-2">
						<Chip
							testId="scene-strategy-review-status"
							label={taxonomy.review_status}
							tone={taxonomy.review_status === "VERIFIED" ? "ready" : "warn"}
						/>
						<Chip
							testId="scene-strategy-consumer-status"
							label={taxonomy.consumer_status}
							tone={taxonomy.consumer_status === "READY" ? "ready" : "warn"}
						/>
						<Chip
							testId="scene-strategy-coverage-status"
							label={`COVERAGE: ${taxonomy.scene_coverage_status}`}
							tone={
								taxonomy.scene_coverage_status === "COVERED"
									? "ready"
									: taxonomy.scene_coverage_status === "PARTIAL"
										? "warn"
										: "risk"
							}
						/>
						{taxonomy.fallback_used ? (
							<Chip
								testId="scene-strategy-fallback-used"
								label="FALLBACK IN USE"
								tone="warn"
							/>
						) : null}
						{taxonomy.is_stale ? (
							<Chip
								testId="scene-strategy-stale"
								label="STALE — RE-DERIVE REQUIRED"
								tone="risk"
							/>
						) : null}
					</div>
				</div>
			) : null}
			<div
				data-testid="scene-strategy-registry-distinction"
				className="mt-3 border-t border-slate-800 pt-2 text-[10px] text-slate-500"
			>
				Scene Strategy is the product's matched authority and is applied
				automatically. Scene Registry images appear only in I2V as visual
				references; T2V, F2V and Hybrid do not configure Scene Registry.
			</div>
		</div>
	);
}
