import { useCallback, useEffect, useMemo, useState } from "react";
import {
	createFactoryPlan,
	type FactoryContextDefaults,
	type FactoryPlanProjection,
	type FactoryTaskProjection,
	getFactoryPlan,
	listFactoryPlans,
	pauseFactoryPlan,
	prepareFactoryPlan,
	resumeFactoryPlan,
} from "../../api/productTreatmentFactory";

const DEFAULT_CONTEXT: FactoryContextDefaults = {
	selected_action_index: 0,
	format: "PGC",
	logical_mode: "HYBRID",
	generation_mode: "SINGLE",
	model_key: "veo_3_1_fast",
	duration_seconds: 8,
};

const READINESS_STATES = [
	"READY",
	"REVIEW_REQUIRED",
	"EVIDENCE_REQUIRED",
	"ASSET_REQUIRED",
	"COPY_SUPPLY_REQUIRED",
	"UNSUPPORTED_PRODUCT_TAXONOMY",
] as const;

const MAX_VISIBLE_PRODUCTS = 100;

function asRecord(value: unknown): Record<string, unknown> {
	return value !== null && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

function asRecords(value: unknown): Array<Record<string, unknown>> {
	return Array.isArray(value) ? value.map(asRecord) : [];
}

function asStrings(value: unknown): string[] {
	return Array.isArray(value)
		? value
				.map((item) => String(item ?? "").trim())
				.filter((item) => item.length > 0)
		: [];
}

function display(
	value: unknown,
	fallback = "Not recorded in snapshot",
): string {
	if (value === null || value === undefined || value === "") return fallback;
	if (typeof value === "boolean") return value ? "YES" : "NO";
	if (Array.isArray(value)) {
		const values = value
			.map((item) =>
				typeof item === "object" ? JSON.stringify(item) : String(item),
			)
			.filter(Boolean);
		return values.length ? values.join(", ") : fallback;
	}
	if (typeof value === "object") return JSON.stringify(value);
	return String(value);
}

function parseProductIds(value: string): string[] {
	return Array.from(
		new Set(
			value
				.split(/[\n,]/)
				.map((item) => item.trim())
				.filter(Boolean),
		),
	).sort();
}

function errorMessage(reason: unknown): string {
	return reason instanceof Error ? reason.message : String(reason);
}

function tone(status: string): string {
	if (/READY|SATISFIED|COMPLETED$/.test(status)) {
		return "border-emerald-500/40 bg-emerald-500/10 text-emerald-200";
	}
	if (/FAILED|UNSUPPORTED/.test(status)) {
		return "border-rose-500/40 bg-rose-500/10 text-rose-200";
	}
	if (/RUNNING|PREPARING/.test(status)) {
		return "border-sky-500/40 bg-sky-500/10 text-sky-200";
	}
	return "border-amber-500/40 bg-amber-500/10 text-amber-100";
}

function StatusBadge({ value }: { value: string }) {
	return (
		<span
			className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide ${tone(value)}`}
		>
			{value}
		</span>
	);
}

interface ProductView {
	productId: string;
	tasks: FactoryTaskProjection[];
	snapshot: Record<string, unknown>;
	context: Record<string, unknown>;
	readiness: Record<string, unknown>;
	resolved: Record<string, unknown>;
	template: Record<string, unknown>;
	primaryStatus: string;
	taxonomy: string;
	nextActions: string[];
	blockerCodes: string[];
}

function buildProductViews(plan: FactoryPlanProjection): ProductView[] {
	const grouped = new Map<string, FactoryTaskProjection[]>();
	for (const task of plan.tasks) {
		const current = grouped.get(task.product_id) ?? [];
		current.push(task);
		grouped.set(task.product_id, current);
	}
	return Array.from(grouped.entries())
		.map(([productId, tasks]) => {
			const snapshot = tasks[0]?.snapshot ?? {};
			const context = asRecord(snapshot.context);
			const readiness = asRecord(snapshot.readiness);
			const resolved = asRecord(snapshot.resolved_authority);
			const template = asRecord(snapshot.treatment_template);
			const profile = asRecord(readiness.applicability_profile);
			const taxonomy = asRecord(resolved.taxonomy);
			const taxonomyParts = [
				profile.product_family,
				profile.product_type,
				taxonomy.product_type_group,
				taxonomy.cluster,
			]
				.map((item) => String(item ?? "").trim())
				.filter(Boolean);
			const readinessBlockers = asRecords(readiness.blockers).map((blocker) =>
				String(blocker.code ?? ""),
			);
			const taskBlockers = tasks.flatMap((task) =>
				[task.blocker_code, task.error_code].filter((value): value is string =>
					Boolean(value),
				),
			);
			const nextActions = Array.from(
				new Set([
					...asStrings(readiness.next_actions),
					...tasks
						.map((task) => task.next_action)
						.filter((value): value is string => Boolean(value)),
				]),
			).sort();
			return {
				productId,
				tasks: [...tasks].sort((left, right) =>
					left.task_type.localeCompare(right.task_type),
				),
				snapshot,
				context,
				readiness,
				resolved,
				template,
				primaryStatus: String(
					readiness.primary_status ??
						(snapshot.scan_error_code ? "REVIEW_REQUIRED" : "REVIEW_REQUIRED"),
				),
				taxonomy: taxonomyParts.join(" / ") || "UNRESOLVED_TAXONOMY",
				nextActions,
				blockerCodes: Array.from(
					new Set([...readinessBlockers, ...taskBlockers].filter(Boolean)),
				).sort(),
			};
		})
		.sort((left, right) => left.productId.localeCompare(right.productId));
}

function KeyValue({
	label,
	value,
	mono = false,
}: {
	label: string;
	value: unknown;
	mono?: boolean;
}) {
	return (
		<div className="min-w-0">
			<div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
				{label}
			</div>
			<div
				className={`mt-1 break-words text-xs text-slate-200 ${mono ? "font-mono" : ""}`}
			>
				{display(value)}
			</div>
		</div>
	);
}

function ProductAuthorityCard({ view }: { view: ProductView }) {
	const productTruth = asRecord(view.resolved.product_truth);
	const copy = asRecord(view.resolved.copy);
	const selection = asRecord(view.resolved.selection);
	const assets = asRecord(view.resolved.assets);
	const treatment = asRecord(view.resolved.treatment);
	const copyPreview = asRecord(view.snapshot.copy_preview);
	const evidence = asRecords(view.readiness.evidence_requirements);
	const provenance = asRecords(productTruth.provenance);
	const readinessBlockers = asRecords(view.readiness.blockers);
	const actionSequence = asRecords(view.template.action_sequence);
	const shots = asRecords(view.template.shot_grammar);
	const compatibility = asRecord(view.template.compatibility_profile);
	const existingTreatments = asRecords(view.snapshot.existing_treatments);
	const visualTreatment = existingTreatments[0] ?? {};
	const eligibleAssets = asRecord(assets.eligible_asset_ids_by_role);
	const candidateTask = view.tasks.find(
		(task) => task.task_type === "TREATMENT_CANDIDATE",
	);
	const lineage = asRecord(candidateTask?.result.lineage);

	return (
		<details
			data-testid={`ptf-product-${view.productId}`}
			className="rounded-xl border border-slate-800 bg-slate-950/70"
		>
			<summary className="cursor-pointer list-none p-3">
				<div className="flex flex-wrap items-start justify-between gap-2">
					<div className="min-w-0">
						<div className="break-all font-mono text-xs font-semibold text-white">
							{view.productId}
						</div>
						<div className="mt-1 text-[11px] text-slate-400">
							{view.taxonomy}
						</div>
					</div>
					<div className="flex flex-wrap items-center gap-2">
						<StatusBadge value={view.primaryStatus} />
						<span className="text-[10px] text-slate-500">
							{view.blockerCodes.length} blocker
							{view.blockerCodes.length === 1 ? "" : "s"}
						</span>
					</div>
				</div>
			</summary>

			<div className="space-y-4 border-t border-slate-800 p-3">
				<div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
					<KeyValue
						label="Product Truth snapshot"
						value={productTruth.snapshot_id}
						mono
					/>
					<KeyValue
						label="Taxonomy fingerprint"
						value={asRecord(view.resolved.taxonomy).taxonomy_fingerprint}
						mono
					/>
					<KeyValue
						label="Readiness hash"
						value={view.readiness.readiness_sha256}
						mono
					/>
					<KeyValue
						label="Product authority hash"
						value={view.readiness.product_authority_sha256}
						mono
					/>
				</div>

				<section>
					<h4 className="text-xs font-semibold text-rose-200">
						Exact blockers and next actions
					</h4>
					{view.blockerCodes.length || readinessBlockers.length ? (
						<div className="mt-2 grid gap-2 md:grid-cols-2">
							{readinessBlockers.map((blocker, index) => (
								<div
									key={`${display(blocker.code)}-${index}`}
									className="rounded-lg border border-rose-500/30 bg-rose-950/20 p-2 text-[11px]"
								>
									<div className="font-mono font-semibold text-rose-200">
										{display(blocker.code)}
									</div>
									<div className="mt-1 text-slate-300">
										{display(blocker.message)}
									</div>
									<div className="mt-1 font-mono text-amber-200">
										{display(blocker.next_action)}
									</div>
								</div>
							))}
							{view.blockerCodes
								.filter(
									(code) =>
										!readinessBlockers.some(
											(blocker) => String(blocker.code) === code,
										),
								)
								.map((code) => (
									<div
										key={code}
										className="rounded-lg border border-rose-500/30 bg-rose-950/20 p-2 font-mono text-[11px] text-rose-200"
									>
										{code}
									</div>
								))}
						</div>
					) : (
						<div className="mt-2 text-xs text-emerald-300">
							No blocker recorded.
						</div>
					)}
					<div className="mt-2 text-[11px] text-slate-400">
						Next action:{" "}
						<span className="font-mono text-amber-200">
							{view.nextActions.join(", ") || "NONE"}
						</span>
					</div>
				</section>

				<section>
					<h4 className="text-xs font-semibold text-cyan-200">
						Evidence applicability and provenance
					</h4>
					<div className="mt-2 overflow-x-auto">
						<table className="min-w-full text-left text-[11px]">
							<thead className="text-slate-500">
								<tr>
									<th className="px-2 py-1">Requirement</th>
									<th className="px-2 py-1">State</th>
									<th className="px-2 py-1">Rule</th>
									<th className="px-2 py-1">Source fields</th>
									<th className="px-2 py-1">Provenance hashes</th>
								</tr>
							</thead>
							<tbody>
								{evidence.map((item) => (
									<tr
										key={display(item.requirement_code)}
										className="border-t border-slate-800"
									>
										<td className="px-2 py-1 font-mono text-slate-200">
											{display(item.requirement_code)}
										</td>
										<td className="px-2 py-1">
											<StatusBadge value={display(item.state)} />
										</td>
										<td className="px-2 py-1 font-mono text-slate-400">
											{display(item.rule_code)}
										</td>
										<td className="px-2 py-1 text-slate-300">
											{display(item.source_fields)}
										</td>
										<td className="max-w-[280px] break-all px-2 py-1 font-mono text-slate-400">
											{display(item.provenance_hashes)}
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
					{evidence.length === 0 ? (
						<div className="mt-2 text-xs text-slate-500">
							No evidence-requirement snapshot was resolved.
						</div>
					) : null}
					<div className="mt-2 grid gap-2 md:grid-cols-2">
						{provenance.map((item) => (
							<div
								key={display(item.provenance_id)}
								className="rounded-lg border border-slate-800 bg-slate-900/60 p-2 text-[11px]"
							>
								<div className="font-mono text-cyan-200">
									{display(item.field_name)} ·{" "}
									{display(item.verification_status)}
								</div>
								<div className="mt-1 text-slate-400">
									{display(item.source_type)} · {display(item.source_lane)}
								</div>
								<div className="mt-1 break-all font-mono text-slate-500">
									{display(item.provenance_sha256)}
								</div>
							</div>
						))}
					</div>
				</section>

				<div className="grid gap-3 lg:grid-cols-2">
					<section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
						<h4 className="text-xs font-semibold text-violet-200">
							Copy and Treatment authority
						</h4>
						<div className="mt-3 grid gap-3 sm:grid-cols-2">
							<KeyValue
								label="Copy grounding"
								value={`${display(copy.grounding_ready)} · ${display(copy.grounding_source)}`}
							/>
							<KeyValue
								label="Approved Copy Sets"
								value={copy.approved_copy_set_ids}
								mono
							/>
							<KeyValue
								label="Copy candidate preview"
								value={`produced=${display(copyPreview.produced, "0")}`}
							/>
							<KeyValue
								label="Approved Treatments"
								value={treatment.approved_treatment_ids}
								mono
							/>
							<KeyValue
								label="Selected Treatments"
								value={treatment.selected_treatment_ids}
								mono
							/>
							<KeyValue label="P6 ready" value={treatment.p6_ready} />
							<KeyValue
								label="Template → Treatment lineage"
								value={
									Object.keys(lineage).length
										? lineage
										: {
												template_id: candidateTask?.template_id,
												template_sha256: candidateTask?.template_sha256,
												treatment_id: candidateTask?.treatment_id,
												treatment_sha256: candidateTask?.treatment_sha256,
											}
								}
								mono
							/>
							<KeyValue
								label="Treatment availability hash"
								value={treatment.availability_sha256}
								mono
							/>
						</div>
					</section>

					<section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
						<h4 className="text-xs font-semibold text-fuchsia-200">
							Action, format and visual authority
						</h4>
						<div className="mt-3 grid gap-3 sm:grid-cols-2">
							<KeyValue label="Action" value={view.template.action_text} />
							<KeyValue
								label="Format / mode"
								value={`${display(view.context.format)} / ${display(view.context.logical_mode)} / ${display(view.context.generation_mode)}`}
							/>
							<KeyValue
								label="Avatar"
								value={
									visualTreatment.avatar_code ?? selection.selected_avatar_code
								}
							/>
							<KeyValue
								label="Wardrobe"
								value={visualTreatment.wardrobe_text}
							/>
							<KeyValue
								label="Background / scene"
								value={
									visualTreatment.scene_template_id ??
									selection.selected_scene_template_id
								}
							/>
							<KeyValue
								label="Camera"
								value={
									visualTreatment.camera_preset_code ??
									selection.selected_camera_preset_code
								}
							/>
							<KeyValue
								label="Actor policy"
								value={view.template.actor_policy}
							/>
							<KeyValue
								label="Required asset roles"
								value={compatibility.required_asset_roles}
							/>
						</div>
						<div className="mt-3">
							<div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
								Eligible assets by role
							</div>
							<div className="mt-1 break-all font-mono text-[11px] text-slate-300">
								{display(eligibleAssets)}
							</div>
						</div>
					</section>
				</div>

				<div className="grid gap-3 lg:grid-cols-2">
					<section>
						<h4 className="text-xs font-semibold text-slate-200">
							Action choreography
						</h4>
						<div className="mt-2 space-y-2">
							{actionSequence.map((action) => (
								<div
									key={display(action.sequence)}
									className="rounded-lg border border-slate-800 p-2 text-[11px] text-slate-300"
								>
									<span className="font-mono text-cyan-200">
										#{display(action.sequence)} · {display(action.actor_role)}
									</span>{" "}
									{display(action.action_text)}
									<div className="mt-1 text-slate-500">
										{display(action.initial_state)} →{" "}
										{display(action.resulting_state)}
									</div>
								</div>
							))}
						</div>
					</section>
					<section>
						<h4 className="text-xs font-semibold text-slate-200">
							Structured shots
						</h4>
						<div className="mt-2 space-y-2">
							{shots.map((shot) => (
								<div
									key={display(shot.sequence)}
									className="rounded-lg border border-slate-800 p-2 text-[11px] text-slate-300"
								>
									<span className="font-mono text-fuchsia-200">
										#{display(shot.sequence)} · {display(shot.framing)} ·{" "}
										{display(shot.camera_motion)}
									</span>
									<div className="mt-1">
										{display(shot.subject)} — {display(shot.purpose)}
									</div>
								</div>
							))}
						</div>
					</section>
				</div>

				<section>
					<h4 className="text-xs font-semibold text-slate-200">
						Per-product task isolation
					</h4>
					<div className="mt-2 overflow-x-auto">
						<table className="min-w-full text-left text-[11px]">
							<thead className="text-slate-500">
								<tr>
									<th className="px-2 py-1">Task</th>
									<th className="px-2 py-1">State</th>
									<th className="px-2 py-1">Blocker</th>
									<th className="px-2 py-1">Next action</th>
									<th className="px-2 py-1">Authority hash</th>
								</tr>
							</thead>
							<tbody>
								{view.tasks.map((task) => (
									<tr key={task.task_id} className="border-t border-slate-800">
										<td className="px-2 py-1 font-mono text-slate-200">
											{task.task_type}
										</td>
										<td className="px-2 py-1">
											<StatusBadge value={task.status} />
										</td>
										<td className="px-2 py-1 font-mono text-rose-200">
											{task.blocker_code ?? task.error_code ?? "NONE"}
										</td>
										<td className="px-2 py-1 font-mono text-amber-200">
											{task.next_action ?? "NONE"}
										</td>
										<td className="max-w-[260px] break-all px-2 py-1 font-mono text-slate-500">
											{task.required_authority_sha256}
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
				</section>
			</div>
		</details>
	);
}

export default function ProductTreatmentFactoryPanel() {
	const [plans, setPlans] = useState<FactoryPlanProjection[]>([]);
	const [selectedPlan, setSelectedPlan] =
		useState<FactoryPlanProjection | null>(null);
	const [selectedPlanId, setSelectedPlanId] = useState("");
	const [loading, setLoading] = useState(true);
	const [busy, setBusy] = useState("");
	const [error, setError] = useState("");
	const [cohortMode, setCohortMode] = useState<"ALL_ACTIVE" | "EXPLICIT">(
		"ALL_ACTIVE",
	);
	const [productIds, setProductIds] = useState("");
	const [targetVideoCount, setTargetVideoCount] = useState(1);
	const [operatorId, setOperatorId] = useState("factory-production-operator");
	const [context, setContext] =
		useState<FactoryContextDefaults>(DEFAULT_CONTEXT);
	const [taxonomyFilter, setTaxonomyFilter] = useState("ALL");
	const [readinessFilter, setReadinessFilter] = useState("ALL");
	const [nextActionFilter, setNextActionFilter] = useState("ALL");

	const replacePlan = useCallback((plan: FactoryPlanProjection) => {
		setSelectedPlan(plan);
		setSelectedPlanId(plan.plan_id);
		setPlans((current) => [
			plan,
			...current.filter((item) => item.plan_id !== plan.plan_id),
		]);
	}, []);

	const loadPlanList = useCallback(async () => {
		setLoading(true);
		setError("");
		try {
			const response = await listFactoryPlans();
			setPlans(response.plans);
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		void loadPlanList();
	}, [loadPlanList]);

	const selectPlan = useCallback(
		async (planId: string) => {
			setSelectedPlanId(planId);
			if (!planId) {
				setSelectedPlan(null);
				return;
			}
			setBusy("select");
			setError("");
			try {
				replacePlan(await getFactoryPlan(planId));
			} catch (reason) {
				setSelectedPlan(null);
				setError(errorMessage(reason));
			} finally {
				setBusy("");
			}
		},
		[replacePlan],
	);

	const refreshSelected = useCallback(async () => {
		if (!selectedPlanId) {
			await loadPlanList();
			return;
		}
		setBusy("refresh");
		setError("");
		try {
			const [plan, response] = await Promise.all([
				getFactoryPlan(selectedPlanId),
				listFactoryPlans(),
			]);
			setPlans([
				plan,
				...response.plans.filter((item) => item.plan_id !== plan.plan_id),
			]);
			setSelectedPlan(plan);
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setBusy("");
		}
	}, [loadPlanList, selectedPlanId]);

	const createPlan = useCallback(async () => {
		if (!Number.isInteger(targetVideoCount) || targetVideoCount < 1 || targetVideoCount > 200) {
			setError("TARGET_VIDEO_COUNT_MUST_BE_BETWEEN_1_AND_200");
			return;
		}
		const explicitIds = parseProductIds(productIds);
		if (cohortMode === "EXPLICIT" && explicitIds.length === 0) {
			setError("EXPLICIT_PRODUCT_IDS_REQUIRED");
			return;
		}
		setBusy("create");
		setError("");
		try {
			const plan = await createFactoryPlan({
				products:
					cohortMode === "EXPLICIT"
						? explicitIds.map((productId) => ({
								product_id: productId,
								...context,
							}))
						: [],
				scan_all_active: cohortMode === "ALL_ACTIVE",
				target_video_count: targetVideoCount,
				defaults: context,
				created_by: operatorId.trim() || "factory-production-operator",
				provider_calls_enabled: false,
				media_generation_enabled: false,
			});
			replacePlan(plan);
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setBusy("");
		}
	}, [cohortMode, context, operatorId, productIds, replacePlan, targetVideoCount]);

	const preparePlan = useCallback(async () => {
		if (!selectedPlan) return;
		setBusy("prepare");
		setError("");
		try {
			replacePlan(
				await prepareFactoryPlan(selectedPlan.plan_id, {
					actor_id: operatorId.trim() || "factory-production-operator",
					max_tasks: 1000,
					materialize_copy_composition: true,
					materialize_treatment_candidates: true,
					provider_calls_enabled: false,
					media_generation_enabled: false,
				}),
			);
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setBusy("");
		}
	}, [operatorId, replacePlan, selectedPlan]);

	const controlPlan = useCallback(
		async (action: "pause" | "resume") => {
			if (!selectedPlan) return;
			setBusy(action);
			setError("");
			const body = {
				actor_id: operatorId.trim() || "factory-production-operator",
				reason:
					action === "pause"
						? "OPERATOR_PAUSED_FACTORY_PLAN"
						: "OPERATOR_RESUMED_FACTORY_PLAN",
			};
			try {
				replacePlan(
					action === "pause"
						? await pauseFactoryPlan(selectedPlan.plan_id, body)
						: await resumeFactoryPlan(selectedPlan.plan_id, body),
				);
			} catch (reason) {
				setError(errorMessage(reason));
			} finally {
				setBusy("");
			}
		},
		[operatorId, replacePlan, selectedPlan],
	);

	const productViews = useMemo(
		() => (selectedPlan ? buildProductViews(selectedPlan) : []),
		[selectedPlan],
	);
	const taxonomies = useMemo(
		() => Array.from(new Set(productViews.map((item) => item.taxonomy))).sort(),
		[productViews],
	);
	const nextActions = useMemo(
		() =>
			Array.from(
				new Set(productViews.flatMap((item) => item.nextActions)),
			).sort(),
		[productViews],
	);
	const filteredProducts = useMemo(
		() =>
			productViews.filter(
				(item) =>
					(taxonomyFilter === "ALL" || item.taxonomy === taxonomyFilter) &&
					(readinessFilter === "ALL" ||
						item.primaryStatus === readinessFilter) &&
					(nextActionFilter === "ALL" ||
						item.nextActions.includes(nextActionFilter)),
			),
		[productViews, taxonomyFilter, readinessFilter, nextActionFilter],
	);
	const visibleProducts = filteredProducts.slice(0, MAX_VISIBLE_PRODUCTS);
	const blockedCount = productViews.filter(
		(item) => item.primaryStatus !== "READY",
	).length;
	const capacitySummary = selectedPlan ? asRecord(selectedPlan.capacity_summary) : {};

	return (
		<section
			id="product-treatment-factory"
			data-testid="product-treatment-factory-panel"
			className="scroll-mt-4 rounded-2xl border border-teal-500/30 bg-slate-950/80 p-4 shadow-xl"
		>
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div>
					<div className="text-xs font-semibold uppercase tracking-[0.18em] text-teal-300">
						Universal Product-to-Treatment Factory
					</div>
					<h2 className="mt-1 text-lg font-semibold text-white">
						Readiness and zero-credit preparation
					</h2>
					<p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-400">
						Scan governed product authority, inspect exact blockers, and
						materialize review-required Copy or Treatment candidates. This
						surface never approves authority and never dispatches generation.
					</p>
				</div>
				<a
					href="/production-studio#product-treatment-factory"
					aria-label="Direct link to Product-to-Treatment Factory"
					className="rounded-lg border border-slate-700 px-2 py-1 text-[10px] font-semibold text-slate-300 hover:border-teal-500"
				>
					Direct link
				</a>
			</div>

			<div className="mt-3 grid gap-2 sm:grid-cols-3">
				<div className="rounded-lg border border-emerald-500/30 bg-emerald-950/20 p-2 text-[11px] text-emerald-200">
					Provider calls: <strong>FALSE</strong>
				</div>
				<div className="rounded-lg border border-emerald-500/30 bg-emerald-950/20 p-2 text-[11px] text-emerald-200">
					Media generation: <strong>FALSE</strong>
				</div>
				<div className="rounded-lg border border-emerald-500/30 bg-emerald-950/20 p-2 text-[11px] text-emerald-200">
					Credit spend: <strong>0</strong>
				</div>
			</div>

			<div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1.2fr)_minmax(300px,0.8fr)]">
				<div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
					<div className="flex flex-wrap items-center gap-4 text-xs">
						<label className="flex items-center gap-2">
							<input
								type="radio"
								name="factory-cohort-mode"
								checked={cohortMode === "ALL_ACTIVE"}
								onChange={() => setCohortMode("ALL_ACTIVE")}
							/>
							All active canonical products
						</label>
						<label className="flex items-center gap-2">
							<input
								type="radio"
								name="factory-cohort-mode"
								checked={cohortMode === "EXPLICIT"}
								onChange={() => setCohortMode("EXPLICIT")}
							/>
							Explicit product IDs
						</label>
					</div>
					{cohortMode === "EXPLICIT" ? (
						<textarea
							aria-label="Factory product IDs"
							value={productIds}
							onChange={(event) => setProductIds(event.target.value)}
							placeholder="One canonical product ID per line"
							className="mt-3 min-h-24 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 font-mono text-xs text-white outline-none focus:border-teal-500"
						/>
					) : (
						<div className="mt-3 rounded-lg border border-teal-500/20 bg-teal-950/20 p-2 text-[11px] text-teal-100">
							The backend resolves the current active catalog. No product ID is
							invented by the dashboard.
						</div>
					)}
					<label className="mt-3 block max-w-xs text-[10px] text-slate-400">
						Target video count (1–200)
						<input
							aria-label="Factory target video count"
							type="number"
							min={1}
							max={200}
							value={targetVideoCount}
							onChange={(event) => setTargetVideoCount(Number(event.target.value))}
							className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-1.5 text-xs text-white"
						/>
					</label>
					<div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
						<label className="text-[10px] text-slate-400">
							Format
							<select
								aria-label="Factory format"
								value={context.format}
								onChange={(event) =>
									setContext((current) => ({
										...current,
										format: event.target
											.value as FactoryContextDefaults["format"],
									}))
								}
								className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-1.5 text-xs text-white"
							>
								<option value="UGC">UGC</option>
								<option value="PGC">PGC</option>
								<option value="CINEMATIC">CINEMATIC</option>
							</select>
						</label>
						<label className="text-[10px] text-slate-400">
							Logical mode
							<select
								aria-label="Factory logical mode"
								value={context.logical_mode}
								onChange={(event) =>
									setContext((current) => ({
										...current,
										logical_mode: event.target
											.value as FactoryContextDefaults["logical_mode"],
									}))
								}
								className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-1.5 text-xs text-white"
							>
								<option value="T2V">T2V</option>
								<option value="I2V">I2V</option>
								<option value="F2V">F2V</option>
								<option value="HYBRID">HYBRID</option>
							</select>
						</label>
						<label className="text-[10px] text-slate-400">
							Generation
							<select
								aria-label="Factory generation mode"
								value={context.generation_mode}
								onChange={(event) =>
									setContext((current) => ({
										...current,
										generation_mode: event.target
											.value as FactoryContextDefaults["generation_mode"],
									}))
								}
								className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-1.5 text-xs text-white"
							>
								<option value="SINGLE">SINGLE</option>
								<option value="EXTEND">EXTEND</option>
							</select>
						</label>
						<label className="text-[10px] text-slate-400">
							Action index
							<input
								aria-label="Factory action index"
								type="number"
								min={0}
								value={context.selected_action_index}
								onChange={(event) =>
									setContext((current) => ({
										...current,
										selected_action_index: Math.max(
											0,
											Number(event.target.value) || 0,
										),
									}))
								}
								className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-1.5 text-xs text-white"
							/>
						</label>
					</div>
					<div className="mt-3 flex flex-wrap items-end gap-2">
						<label className="min-w-56 flex-1 text-[10px] text-slate-400">
							Operator ID
							<input
								aria-label="Factory operator ID"
								value={operatorId}
								onChange={(event) => setOperatorId(event.target.value)}
								className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-1.5 text-xs text-white"
							/>
						</label>
						<button
							type="button"
							data-testid="ptf-create-plan"
							disabled={
								Boolean(busy) ||
								(cohortMode === "EXPLICIT" &&
									parseProductIds(productIds).length === 0)
							}
							onClick={() => void createPlan()}
							className="rounded-lg bg-teal-600 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
						>
							{busy === "create" ? "Scanning…" : "Create readiness plan"}
						</button>
					</div>
				</div>

				<div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
					<label className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
						Factory plan
						<select
							aria-label="Select factory plan"
							data-testid="ptf-plan-select"
							value={selectedPlanId}
							onChange={(event) => void selectPlan(event.target.value)}
							className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-xs text-white"
						>
							<option value="">Select a plan</option>
							{plans.map((plan) => (
								<option key={plan.plan_id} value={plan.plan_id}>
									{plan.plan_id} · {plan.status} · {plan.product_count} products
								</option>
							))}
						</select>
					</label>
					<div className="mt-3 flex flex-wrap gap-2">
						<button
							type="button"
							data-testid="ptf-plan-refresh"
							disabled={Boolean(busy)}
							onClick={() => void refreshSelected()}
							className="rounded border border-slate-700 px-2 py-1 text-[11px] text-slate-200 disabled:opacity-50"
						>
							{busy === "refresh" ? "Refreshing…" : "Refresh"}
						</button>
						<button
							type="button"
							data-testid="ptf-prepare-plan"
							disabled={!selectedPlan || Boolean(busy)}
							onClick={() => void preparePlan()}
							className="rounded border border-teal-500/50 bg-teal-500/10 px-2 py-1 text-[11px] text-teal-200 disabled:opacity-50"
						>
							{busy === "prepare" ? "Preparing…" : "Prepare review drafts"}
						</button>
						{selectedPlan?.status === "PAUSED" ? (
							<button
								type="button"
								data-testid="ptf-resume-plan"
								disabled={Boolean(busy)}
								onClick={() => void controlPlan("resume")}
								className="rounded border border-emerald-500/50 px-2 py-1 text-[11px] text-emerald-200 disabled:opacity-50"
							>
								Resume
							</button>
						) : (
							<button
								type="button"
								data-testid="ptf-pause-plan"
								disabled={!selectedPlan || Boolean(busy)}
								onClick={() => void controlPlan("pause")}
								className="rounded border border-amber-500/50 px-2 py-1 text-[11px] text-amber-200 disabled:opacity-50"
							>
								Pause
							</button>
						)}
					</div>
				</div>
			</div>

			{loading || busy === "select" ? (
				<div
					data-testid="ptf-loading-state"
					className="mt-4 rounded-xl border border-sky-500/30 bg-sky-950/20 p-3 text-xs text-sky-200"
				>
					Loading governed factory plans…
				</div>
			) : null}

			{error ? (
				<div
					role="alert"
					data-testid="ptf-error-state"
					className="mt-4 rounded-xl border border-rose-500/40 bg-rose-950/30 p-3 text-xs text-rose-200"
				>
					Factory action stopped before unsafe execution.
					<div className="mt-1 break-all font-mono text-[10px]">{error}</div>
				</div>
			) : null}

			{!loading && !selectedPlan ? (
				<div
					data-testid="ptf-empty-state"
					className="mt-4 rounded-xl border border-slate-800 bg-slate-900/40 p-4 text-xs text-slate-400"
				>
					{plans.length
						? "Select an existing plan or create a new readiness plan."
						: "No factory plans exist. Scan all active products or provide explicit product IDs."}
				</div>
			) : null}

			{selectedPlan ? (
				<div data-testid="ptf-success-state" className="mt-4 space-y-3">
					<div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-900/40 p-3">
						<div>
							<div className="flex flex-wrap items-center gap-2">
								<span className="font-mono text-xs text-white">
									{selectedPlan.plan_id}
								</span>
								<StatusBadge value={selectedPlan.status} />
							</div>
							<div className="mt-1 text-[11px] text-slate-400">
								{selectedPlan.product_count} products ·{" "}
								{selectedPlan.failure_count} isolated scan failure
								{selectedPlan.failure_count === 1 ? "" : "s"}
							</div>
						</div>
						<div className="grid grid-cols-3 gap-2 text-center text-[10px]">
							<KeyValue
								label="Plan hash"
								value={selectedPlan.plan_identity_sha256}
								mono
							/>
							<KeyValue
								label="Cohort hash"
								value={selectedPlan.cohort_sha256}
								mono
							/>
							<KeyValue
								label="Context hash"
								value={selectedPlan.context_sha256}
								mono
							/>
						</div>
					</div>
					<div
						data-testid="ptf-capacity-summary"
						className="mt-3 grid gap-3 rounded-xl border border-teal-500/20 bg-teal-950/10 p-3 sm:grid-cols-2 lg:grid-cols-4"
					>
						<KeyValue
							label="Target videos"
							value={capacitySummary.target_video_count}
						/>
						<KeyValue
							label="Dialogue units required"
							value={capacitySummary.required_dialogues}
						/>
						<KeyValue
							label="Variation-group reuse cap"
							value={capacitySummary.variation_group_reuse_cap}
						/>
						<KeyValue
							label="Approved Copy Sets / required"
							value={`${display(capacitySummary.approved_copy_set_count)} / ${display(capacitySummary.required_copy_set_count)}`}
						/>
						<KeyValue label="Copy shortfall" value={capacitySummary.copy_shortfall} />
						<KeyValue
							label="Approved treatments / required"
							value={`${display(capacitySummary.approved_master_treatment_count)} / ${display(capacitySummary.required_treatment_count)}`}
						/>
						<KeyValue
							label="Treatment shortfall"
							value={capacitySummary.treatment_shortfall}
						/>
						<KeyValue
							label="Material proof"
							value={capacitySummary.unique_material_count ?? "REHEARSAL_REQUIRED"}
						/>
						<KeyValue
							label="Compiled payload proof"
							value={capacitySummary.unique_compiled_payload_count ?? "REHEARSAL_REQUIRED"}
						/>
					</div>

					{blockedCount > 0 ? (
						<div
							data-testid="ptf-blocked-state"
							className="rounded-xl border border-amber-500/40 bg-amber-950/20 p-3 text-xs text-amber-100"
						>
							{blockedCount} product{blockedCount === 1 ? "" : "s"} require
							review or additional authority. Eligible sibling products remain
							visible and isolated; the batch is not collapsed into one failure.
						</div>
					) : (
						<div className="rounded-xl border border-emerald-500/30 bg-emerald-950/20 p-3 text-xs text-emerald-200">
							Every product in this plan resolves READY for its requested
							context.
						</div>
					)}

					<div className="grid gap-2 rounded-xl border border-slate-800 bg-slate-900/40 p-3 sm:grid-cols-3">
						<label className="text-[10px] text-slate-400">
							Taxonomy
							<select
								aria-label="Filter factory taxonomy"
								value={taxonomyFilter}
								onChange={(event) => setTaxonomyFilter(event.target.value)}
								className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-1.5 text-xs text-white"
							>
								<option value="ALL">All taxonomies</option>
								{taxonomies.map((taxonomy) => (
									<option key={taxonomy} value={taxonomy}>
										{taxonomy}
									</option>
								))}
							</select>
						</label>
						<label className="text-[10px] text-slate-400">
							Readiness
							<select
								aria-label="Filter factory readiness"
								value={readinessFilter}
								onChange={(event) => setReadinessFilter(event.target.value)}
								className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-1.5 text-xs text-white"
							>
								<option value="ALL">All readiness states</option>
								{READINESS_STATES.map((status) => (
									<option key={status} value={status}>
										{status}
									</option>
								))}
							</select>
						</label>
						<label className="text-[10px] text-slate-400">
							Next action
							<select
								aria-label="Filter factory next action"
								value={nextActionFilter}
								onChange={(event) => setNextActionFilter(event.target.value)}
								className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-1.5 text-xs text-white"
							>
								<option value="ALL">All next actions</option>
								{nextActions.map((action) => (
									<option key={action} value={action}>
										{action}
									</option>
								))}
							</select>
						</label>
					</div>

					<div className="flex items-center justify-between text-[10px] text-slate-500">
						<span>
							{filteredProducts.length} matching product
							{filteredProducts.length === 1 ? "" : "s"}
						</span>
						{filteredProducts.length > MAX_VISIBLE_PRODUCTS ? (
							<span>
								Showing first {MAX_VISIBLE_PRODUCTS}; narrow the filters for the
								remaining products.
							</span>
						) : null}
					</div>
					<div className="space-y-2 [content-visibility:auto]">
						{visibleProducts.map((view) => (
							<ProductAuthorityCard key={view.productId} view={view} />
						))}
						{visibleProducts.length === 0 ? (
							<div className="rounded-xl border border-slate-800 p-3 text-xs text-slate-500">
								No product matches the current filters.
							</div>
						) : null}
					</div>
				</div>
			) : null}
		</section>
	);
}
