import { PenLine, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
	approveFormulaBlueprint,
	activateFormulaBlueprint,
	fetchCopyRegisterFormulas,
	fetchCopyRegisterProviderStatus,
	fetchCopyRegisterTruth,
	generateCopyRegisterAngles,
	generateFormulaCopyBlueprint,
	listCopyRegisterBlueprints,
	regenerateFormulaStage,
	type CopyAngleOptionV2,
	type CopyBlueprintV2Record,
	type CopyFormulaV2,
	type CopyTruthProofV2,
	type TextAssistLaneStatusV2,
} from "../api/copyRegisterV2";
import { fetchProductCatalog } from "../api/products";
import { Badge, type BadgeTone, FormField, HelperText, Section } from "../components/ui";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { Product } from "../types";

const INPUT_CLASS =
	"mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200";

const EMPTY_APPROVAL_CHECKS = {
	semantic: false,
	provenance: false,
	safety: false,
	bridge: false,
	duration: false,
};

function errorMessage(error: unknown): string {
	const message = error instanceof Error ? error.message : "Copy Register V2 request failed.";
	const jsonStart = message.indexOf("{");
	if (jsonStart < 0) return message;
	try {
		const payload = JSON.parse(message.slice(jsonStart));
		const detail = payload?.detail;
		if (detail?.error && detail?.detail) return `${detail.error}: ${detail.detail}`;
	} catch {
		// Preserve the original transport error when the body is not JSON.
	}
	return message;
}

function DisabledReasons({
	reasons,
	testId,
}: {
	reasons: string[];
	testId: string;
}) {
	if (!reasons.length) return null;
	return (
		<div data-testid={testId}>
			<HelperText tone="warn">Disabled: {reasons.join(" · ")}</HelperText>
		</div>
	);
}

function truthTone(truth: CopyTruthProofV2 | null): BadgeTone {
	return truth?.ready_for_copy ? "success" : "warn";
}

function BlueprintCard({
	blueprint,
	onRegenerate,
	busy,
	allowRegenerate,
}: {
	blueprint: CopyBlueprintV2Record;
	onRegenerate: (stageKey: string) => void;
	busy: boolean;
	allowRegenerate: boolean;
}) {
	const authorityStatus = blueprint.current_authority_status ?? (
		blueprint.status === "DRAFT" ? "DRAFT" : "STALE_AUTHORITY_LINEAGE"
	);
	const authorityCurrent = blueprint.current_authority_valid === true;
	const formulaValid = blueprint.stages.every(
		(stage, index) => stage.order === index && stage.validation.valid,
	);
	const evidenceValid = blueprint.stages.every(
		(stage) => !stage.claim_bearing || stage.fact_refs.length > 0,
	);
	const bridgeValid = blueprint.stages.every(
		(stage, index) =>
			Boolean(stage.bridge.entry && stage.bridge.exit) &&
			(index === 0 || blueprint.stages[index - 1].bridge.exit === stage.bridge.entry),
	);

	return (
		<div
			className="rounded-xl border border-slate-800 bg-slate-950/70 p-4"
			data-testid="v2-blueprint-card"
		>
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div>
					<div className="flex flex-wrap items-center gap-2">
						<span className="font-mono text-xs text-blue-200">{blueprint.blueprint_id}</span>
						<span className="text-xs text-slate-500">revision {blueprint.revision}</span>
					</div>
					<p className="mt-1 text-xs text-slate-400">
						{blueprint.formula_id} · {blueprint.formula_version}
					</p>
				</div>
				<Badge tone={authorityStatus === "CURRENT · PRODUCTION_VALID" || authorityCurrent ? "success" : "warn"}>
					{authorityStatus}
				</Badge>
			</div>
			{blueprint.current_authority_reason ? (
				<p className="mt-2 text-xs text-amber-200" data-testid="v2-authority-reason">
					Authority check: {blueprint.current_authority_reason}
				</p>
			) : null}
			<div className="mt-4 grid gap-3 md:grid-cols-2">
				<div>
					<p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Objective</p>
					<p className="mt-1 text-sm text-slate-200">{blueprint.objective.definition}</p>
				</div>
				<div>
					<p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Selected angle</p>
					<p className="mt-1 text-sm text-slate-200">{blueprint.angle.definition}</p>
				</div>
			</div>
			<div className="mt-4 space-y-2">
				<p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
					Ordered formula stages (source of truth)
				</p>
				{blueprint.stages.map((stage) => (
					<div
						key={stage.stage_key}
						className="rounded-lg border border-slate-800 bg-slate-900/80 p-3"
						data-testid={`v2-stage-${stage.formula_stage_key}`}
					>
						<div className="flex items-center justify-between gap-2">
							<span className="text-[10px] font-bold uppercase text-blue-200">
								{stage.order + 1}. {stage.formula_stage_key}
							</span>
							{allowRegenerate && blueprint.status !== "PRODUCTION_VALID" ? (
								<button
									type="button"
									data-testid={`regenerate-v2-stage-${stage.formula_stage_key}`}
									disabled={busy}
									onClick={() => onRegenerate(stage.stage_key)}
									className="rounded border border-violet-500/40 px-2 py-1 text-[10px] font-bold uppercase text-violet-200 disabled:opacity-40"
								>
									Regenerate revision
								</button>
							) : null}
						</div>
						<p className="mt-2 text-sm leading-6 text-slate-200">{stage.authored_text}</p>
						<div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-slate-500">
							<span>{stage.claim_bearing ? "evidence-backed" : "non-claim CTA"}</span>
							{stage.fact_refs.map((ref) => (
								<span key={ref.fact_id} className="rounded bg-slate-800 px-1.5 py-0.5 font-mono">
									{ref.fact_id}
								</span>
							))}
						</div>
					</div>
				))}
			</div>
			<div className="mt-4 grid gap-2 rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-xs text-slate-300 sm:grid-cols-2">
				<span>{formulaValid ? "✓" : "✕"} Formula order and stage validation</span>
				<span>{evidenceValid ? "✓" : "✕"} Stable evidence lineage</span>
				<span>{bridgeValid ? "✓" : "✕"} Bridge continuity</span>
				<span>
					Duration readiness: {blueprint.estimated_word_count} words
					{blueprint.target_duration_seconds
						? ` / ${blueprint.target_duration_seconds}s`
						: " · reviewer confirmation required"}
				</span>
			</div>
		</div>
	);
}

export default function CopySetRegistryPage() {
	const [searchParams, setSearchParams] = useSearchParams();
	const [products, setProducts] = useState<Product[]>([]);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [truth, setTruth] = useState<CopyTruthProofV2 | null>(null);
	const [formulas, setFormulas] = useState<CopyFormulaV2[]>([]);
	const [textAssistStatus, setTextAssistStatus] = useState<TextAssistLaneStatusV2 | null>(null);
	const [formulaId, setFormulaId] = useState("");
	const [angles, setAngles] = useState<CopyAngleOptionV2[]>([]);
	const [selectedAngleId, setSelectedAngleId] = useState("");
	const [facts, setFacts] = useState<CopyTruthProofV2["facts"]>([]);
	const [selectedFactIds, setSelectedFactIds] = useState<string[]>([]);
	const [blueprints, setBlueprints] = useState<CopyBlueprintV2Record[]>([]);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [success, setSuccess] = useState("");
	const [reviewer, setReviewer] = useState("operator");
	const [approvalChecks, setApprovalChecks] = useState(EMPTY_APPROVAL_CHECKS);
	const [activatedBlueprintId, setActivatedBlueprintId] = useState("");

	const selectedAngle = useMemo(
		() => angles.find((angle) => angle.angle_id === selectedAngleId) ?? null,
		[angles, selectedAngleId],
	);
	const latestBlueprint = blueprints[0] ?? null;
	const reviewableBlueprint = latestBlueprint?.status !== "PRODUCTION_VALID" ? latestBlueprint : null;
	const approvalReady = Object.values(approvalChecks).every(Boolean);
	const textAssistReady = textAssistStatus?.configured === true && textAssistStatus.status === "READY";
	const angleDisabledReasons = [
		...(!truth?.ready_for_copy ? ["Product Truth not ready"] : []),
		...(!formulaId ? ["formula required"] : []),
		...(!textAssistReady ? ["Text Assist provider not configured"] : []),
	];
	const blueprintDisabledReasons = [
		...(!truth?.ready_for_copy ? ["Product Truth not ready"] : []),
		...(!formulaId ? ["formula required"] : []),
		...(!selectedAngle ? ["angle required"] : []),
		...(selectedFactIds.length < 1 || selectedFactIds.length > 5
			? ["select 1–5 evidence facts"]
			: []),
		...(!textAssistReady ? ["Text Assist provider not configured"] : []),
	];

	useEffect(() => {
		void fetchProductCatalog(500)
			.then((response) => setProducts(response.items ?? []))
			.catch((reason) => setError(errorMessage(reason)));
		void fetchCopyRegisterFormulas()
			.then((response) => setFormulas(response.formulas ?? []))
			.catch((reason) => setError(errorMessage(reason)));
		void fetchCopyRegisterProviderStatus()
			.then(setTextAssistStatus)
			.catch((reason) => {
				setTextAssistStatus(null);
				setError(errorMessage(reason));
			});
	}, []);

	useEffect(() => {
		const productId = searchParams.get("product_id");
		if (!productId || !products.length) return;
		const product = products.find((item) => item.id === productId);
		if (product && product.id !== selectedProduct?.id) setSelectedProduct(product);
	}, [products, searchParams, selectedProduct?.id]);

	useEffect(() => {
		if (!selectedProduct) {
			setTruth(null);
			setBlueprints([]);
			setAngles([]);
			setFacts([]);
			setSelectedFactIds([]);
			return;
		}
		setError("");
		setSuccess("");
		void Promise.all([
			fetchCopyRegisterTruth(selectedProduct.id),
			listCopyRegisterBlueprints(selectedProduct.id),
		])
			.then(([truthResponse, blueprintResponse]) => {
				setTruth(truthResponse);
				setFacts(truthResponse.facts);
				setBlueprints(blueprintResponse.items ?? []);
				setActivatedBlueprintId(blueprintResponse.activation?.active_blueprint_id ?? "");
			})
			.catch((reason) => setError(errorMessage(reason)));
	}, [selectedProduct]);

	const selectProduct = (product: Product | null) => {
		setSelectedProduct(product);
		setSearchParams(product ? { product_id: product.id } : {});
		setFormulaId("");
		setSelectedAngleId("");
		setAngles([]);
		setSelectedFactIds([]);
		setApprovalChecks(EMPTY_APPROVAL_CHECKS);
		setActivatedBlueprintId("");
	};

	const handleActivate = async (blueprint: CopyBlueprintV2Record) => {
		setBusy(true);
		setError("");
		setSuccess("");
		try {
			const response = await activateFormulaBlueprint(blueprint.blueprint_id);
			setActivatedBlueprintId(blueprint.blueprint_id);
			setSuccess(
				`V2 blueprint activated as the sole authority for all ${response.required_lane_count} copy-required lanes.`,
			);
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setBusy(false);
		}
	};

	const handleGenerateAngles = async () => {
		if (!selectedProduct || !formulaId) return;
		setBusy(true);
		setError("");
		setSuccess("");
		try {
			const response = await generateCopyRegisterAngles({
				product_id: selectedProduct.id,
				formula_id: formulaId,
				objective: "conversion",
			});
			setAngles(response.angles);
			setFacts(response.facts);
			setSelectedAngleId("");
			setSelectedFactIds([]);
			setSuccess("Grounded angle options generated from the approved Product Truth.");
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setBusy(false);
		}
	};

	const toggleFact = (factId: string) => {
		setSelectedFactIds((current) => {
			if (current.includes(factId)) return current.filter((item) => item !== factId);
			if (current.length >= 5) return current;
			return [...current, factId];
		});
	};

	const handleGenerateBlueprint = async () => {
		if (!selectedProduct || !selectedAngle || !formulaId || selectedFactIds.length === 0) return;
		setBusy(true);
		setError("");
		setSuccess("");
		try {
			const response = await generateFormulaCopyBlueprint({
				product_id: selectedProduct.id,
				formula_id: formulaId,
				objective_id: "conversion",
				objective_definition: "Help a qualified buyer choose a grounded next step.",
				angle_id: selectedAngle.angle_id,
				angle_definition: selectedAngle.definition,
				evidence_fact_ids: selectedFactIds,
			});
			setBlueprints((current) => [response.blueprint, ...current.filter((item) => item.blueprint_id !== response.blueprint.blueprint_id)]);
			setApprovalChecks(EMPTY_APPROVAL_CHECKS);
			setSuccess(`New V2 blueprint ${response.blueprint.blueprint_id} created as DRAFT. Review is still required.`);
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setBusy(false);
		}
	};

	const handleRegenerate = async (stageKey: string) => {
		if (!reviewableBlueprint) return;
		setBusy(true);
		setError("");
		try {
			const response = await regenerateFormulaStage(reviewableBlueprint.blueprint_id, stageKey);
			setBlueprints((current) => [response.blueprint, ...current.filter((item) => item.blueprint_id !== response.blueprint.blueprint_id)]);
			setApprovalChecks(EMPTY_APPROVAL_CHECKS);
			setSuccess(`Stage regenerated as revision ${response.new_revision}; the approved parent remains immutable.`);
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setBusy(false);
		}
	};

	const handleApprove = async () => {
		if (!reviewableBlueprint || !reviewer.trim() || !approvalReady) return;
		setBusy(true);
		setError("");
		try {
			const response = await approveFormulaBlueprint({
				blueprint_id: reviewableBlueprint.blueprint_id,
				approved_by: reviewer.trim(),
				semantic_review: {
					decision: "APPROVED",
					reviewer: reviewer.trim(),
					rationale: "Reviewed against the displayed Product Truth, evidence lineage, formula continuity and safety gates.",
					reviewed_at: new Date().toISOString(),
				},
				readiness_proof: {
					readiness_validated: true,
					provenance_validated: true,
					safety_validated: true,
					bridge_validated: true,
					duration_validated: true,
				},
			});
			setBlueprints((current) => [response.blueprint, ...current.filter((item) => !(item.blueprint_id === response.blueprint.blueprint_id && item.revision === response.blueprint.revision))]);
			setApprovalChecks(EMPTY_APPROVAL_CHECKS);
			setSuccess("Explicit approval recorded. This blueprint is now V2 PRODUCTION_VALID.");
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setBusy(false);
		}
	};

	return (
		<div className="mx-auto max-w-6xl space-y-6 p-4 md:p-8" data-testid="copy-set-registry-page">
			<header>
				<div className="flex items-center gap-2 text-blue-300">
					<PenLine size={20} />
					<span className="text-[10px] font-bold uppercase tracking-[0.2em]">Creative</span>
				</div>
				<h1 className="mt-1 text-2xl font-bold text-slate-100">Copy Register V2</h1>
				<p className="mt-2 max-w-3xl text-sm text-slate-400">
					Create one formula-native, evidence-backed blueprint. This workflow has its own V2
					persistence and does not read, write, migrate, or reuse historical CopySet records.
				</p>
			</header>

			{error ? <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100" data-testid="copy-registry-error">{error}</p> : null}
			{success ? <p className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100" data-testid="copy-registry-success">{success}</p> : null}

			<Section title="1. Select product" helper="Only a product with a current approved Product Truth snapshot can continue.">
				<div className="max-w-xl">
					<SearchableProductSelect
						products={products}
						selectedProduct={selectedProduct}
						onSelect={selectProduct}
						showReadinessBadge={false}
					/>
				</div>
			</Section>

			{selectedProduct ? (
				<>
					<Section
						title="2. Product Truth proof"
						helper="Read-only upstream authority; V2 records carry its snapshot ID and digest."
						action={truth ? <Badge tone={truthTone(truth)}>{truth.ready_for_copy ? "APPROVED · READY" : "BLOCKED"}</Badge> : null}
					>
						{truth ? (
							<div className="space-y-3 text-xs text-slate-300" data-testid="product-truth-proof">
								<div className="grid gap-3 sm:grid-cols-2">
									<div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3" data-testid="canonical-taxonomy-proof">
										<p className="font-bold uppercase tracking-wider text-blue-200">Canonical Taxonomy</p>
										<p className="mt-2"><span className="text-slate-500">Category: </span>{truth.product.category || "—"}</p>
										<p><span className="text-slate-500">Subcategory: </span>{truth.product.subcategory || "—"}</p>
										<p><span className="text-slate-500">Type: </span>{truth.product.product_type || "—"}</p>
										<p><span className="text-slate-500">Product type code: </span><span className="font-mono">{truth.product.product_type_code || "—"}</span></p>
									</div>
									<div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
										<p className="font-bold uppercase tracking-wider text-blue-200">Canonical Copy Cluster</p>
										<p className="mt-2 text-sm text-slate-100">{truth.product.canonical_copy_cluster || truth.product.cluster || "—"}</p>
										<p className="mt-1 text-[10px] text-slate-500">Copywriting taxonomy authority; never sourced from product.silo.</p>
									</div>
									<div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
										<p className="font-bold uppercase tracking-wider text-blue-200">BOSMAX Family</p>
										<p className="mt-2 text-sm text-slate-100">{truth.product.product_family || "—"}</p>
										<p className="mt-1 text-[10px] text-slate-500">{truth.product.product_family_reason || "Independently derived family dimension."}</p>
									</div>
									<div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
										<p className="font-bold uppercase tracking-wider text-amber-200">Visual/Internal Silo</p>
										<p className="mt-2 text-sm text-slate-100">{truth.product.visual_internal_silo || "—"}</p>
										<p className="mt-1 text-[10px] text-amber-200/70">{truth.product.visual_internal_silo_status || "NOT_SET"} · not a Copy Register cluster authority.</p>
									</div>
								</div>
								{truth.authority?.authority_fingerprint ? <p><span className="text-slate-500">Taxonomy/strategy authority fingerprint: </span><span className="font-mono">{truth.authority.authority_fingerprint}</span></p> : null}
								{truth.product_truth.snapshot ? <p><span className="text-slate-500">Approved Product Truth snapshot: </span><span className="font-mono">{truth.product_truth.snapshot.snapshot_id}</span> · v{truth.product_truth.snapshot.version} · digest <span className="font-mono">{truth.product_truth.snapshot.digest.slice(0, 16)}…</span></p> : null}
								<p><span className="text-slate-500">Avatar/persona: </span>{JSON.stringify(truth.product_truth.persona) || "—"}</p>
								<p><span className="text-slate-500">Allowed claims: </span>{truth.product_truth.allowed_claims.join(" · ") || "—"}</p>
								{truth.blockers.length ? <HelperText tone="warn">Blockers: {truth.blockers.join("; ")}</HelperText> : <HelperText className="text-emerald-300/80">Product Truth lineage and claim gate are ready for formula copy.</HelperText>}
							</div>
						) : <p className="text-sm text-slate-400">Loading Product Truth…</p>}
					</Section>

					<Section title="3. Choose explicit formula" helper="Formula is mandatory. V2 never selects HSO or another default silently.">
						<div className="max-w-xl">
							<label className="text-xs font-semibold text-slate-300" htmlFor="v2-formula-picker">Repository formula</label>
							<select id="v2-formula-picker" data-testid="v2-formula-picker" value={formulaId} onChange={(event) => { setFormulaId(event.target.value); setAngles([]); setSelectedAngleId(""); }} className={INPUT_CLASS}>
								<option value="">Select formula — required</option>
								{formulas.map((formula) => <option key={formula.formula_id} value={formula.formula_id}>{formula.display_name} · {formula.formula_id}</option>)}
							</select>
							{formulaId ? <HelperText className="text-emerald-300/80">{formulas.find((formula) => formula.formula_id === formulaId)?.formula_version}</HelperText> : <HelperText tone="warn">No default formula is allowed.</HelperText>}
						</div>
					</Section>

					<Section title="4. Generate grounded angle options" helper="This is an explicit authoring action; options are derived from Product Truth facts." action={<Badge tone={textAssistReady ? "success" : "warn"}>Text Assist · {textAssistStatus?.status ?? "UNAVAILABLE"}</Badge>}>
						<button type="button" data-testid="generate-angle-options" disabled={busy || angleDisabledReasons.length > 0} onClick={() => void handleGenerateAngles()} className="rounded-xl border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40">{busy ? "Generating…" : "Generate Angle Options"}</button>
						<DisabledReasons reasons={angleDisabledReasons} testId="generate-angle-disabled-reasons" />
						{textAssistReady ? <HelperText>Provider: {textAssistStatus?.provider_id ?? "configured"} · model: {textAssistStatus?.model_id ?? "configured"}. No API key is displayed.</HelperText> : null}
						{angles.length ? <div className="mt-4 grid gap-2 md:grid-cols-2" data-testid="angle-options">{angles.map((angle) => <label key={angle.angle_id} className={`cursor-pointer rounded-lg border p-3 text-sm ${selectedAngleId === angle.angle_id ? "border-blue-400 bg-blue-500/10 text-blue-100" : "border-slate-800 text-slate-300"}`}><input type="radio" name="v2-angle" value={angle.angle_id} checked={selectedAngleId === angle.angle_id} onChange={() => setSelectedAngleId(angle.angle_id)} className="mr-2" />{angle.definition}<span className="mt-1 block text-[10px] text-slate-500">{angle.evidence_fact_ids.join(", ")}</span></label>)}</div> : <p className="mt-3 text-xs text-slate-500">Press the button after selecting a formula.</p>}
					</Section>

					<Section title="5. Select evidence-backed USP facts" helper="Maximum five facts. Every claim-bearing stage will carry stable snapshot/fact/digest references.">
						<div className="space-y-2" data-testid="evidence-facts">
							{facts.map((fact) => <label key={fact.fact_id} className="flex cursor-pointer gap-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-sm text-slate-300"><input type="checkbox" checked={selectedFactIds.includes(fact.fact_id)} onChange={() => toggleFact(fact.fact_id)} disabled={!selectedFactIds.includes(fact.fact_id) && selectedFactIds.length >= 5} /><span><span className="font-mono text-[10px] text-blue-200">{fact.fact_id}</span><span className="ml-2 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase text-slate-500">{fact.fact_kind}</span><span className="mt-1 block">{fact.text}</span></span></label>)}
							{facts.length === 0 ? <p className="text-xs text-slate-500">Generate angle options to load approved evidence facts.</p> : null}
						</div>
						<p className="mt-3 text-xs text-slate-500">Selected {selectedFactIds.length}/5</p>
					</Section>

					<Section title="6. Generate the complete formula blueprint" helper="Requires a selected angle and at least one approved evidence fact.">
						<button type="button" data-testid="generate-new-formula-copy" disabled={busy || blueprintDisabledReasons.length > 0} onClick={() => void handleGenerateBlueprint()} className="rounded-xl border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40">{busy ? "Generating…" : "GENERATE NEW FORMULA COPY"}</button>
						<DisabledReasons reasons={blueprintDisabledReasons} testId="generate-blueprint-disabled-reasons" />
						<HelperText className="text-blue-300/80">This step makes one additional text-assist call; it does not spend video/image credits.</HelperText>
					</Section>

					{latestBlueprint ? <Section title="7. Review, approve, and activate" helper="Approved text is immutable. Activation atomically makes this blueprint authoritative for all required lanes."><div className="space-y-3">{blueprints.map((item, index) => <BlueprintCard key={`${item.blueprint_id}:${item.revision}`} blueprint={item} onRegenerate={(stageKey) => void handleRegenerate(stageKey)} busy={busy} allowRegenerate={index === 0} />)}</div>{reviewableBlueprint ? <div className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4" data-testid="v2-approval-panel"><div className="flex items-center gap-2 text-sm font-semibold text-amber-100"><ShieldCheck size={16} />Explicit human approval</div><FormField label="Reviewer" className="mt-3 max-w-sm"><input className={INPUT_CLASS} value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></FormField><div className="mt-3 grid gap-2 text-xs text-slate-300 sm:grid-cols-2">{[
						["semantic", "I reviewed every authored stage against Product Truth."],
						["provenance", "Product Truth and evidence lineage match the selected product."],
						["safety", "Allowed claims and warnings were reviewed; no unsafe claim was added."],
						["bridge", "Formula order and bridge continuity are coherent."],
						["duration", "Word count and target-lane duration readiness were reviewed."],
					].map(([key, label]) => <label key={key} className="flex cursor-pointer items-start gap-2 rounded border border-slate-800 p-2"><input type="checkbox" data-testid={`approval-check-${key}`} checked={approvalChecks[key as keyof typeof approvalChecks]} onChange={(event) => setApprovalChecks((current) => ({ ...current, [key]: event.target.checked }))} /><span>{label}</span></label>)}</div><button type="button" data-testid="approve-v2-blueprint" disabled={busy || !reviewer.trim() || !approvalReady} onClick={() => void handleApprove()} className="mt-4 rounded-xl border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40">{busy ? "Approving…" : "Approve → PRODUCTION_VALID"}</button></div> : <div className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4"><HelperText className="text-emerald-300/80">V2 PRODUCTION_VALID is immutable. Activation never changes its approved text.</HelperText>{latestBlueprint.current_authority_activation_allowed === false ? <HelperText className="mt-2 text-amber-200/80">Activation disabled: {latestBlueprint.current_authority_reason ?? "current authority validation is not satisfied"}.</HelperText> : null}<button type="button" data-testid="activate-v2-blueprint" disabled={busy || latestBlueprint.current_authority_activation_allowed !== true || activatedBlueprintId === latestBlueprint.blueprint_id} onClick={() => void handleActivate(latestBlueprint)} className="mt-3 rounded-xl border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40">{activatedBlueprintId === latestBlueprint.blueprint_id ? "ACTIVE · 8 REQUIRED LANES" : busy ? "Activating…" : "ACTIVATE FOR VIDEO + POSTER LANES"}</button></div>}</Section> : <Section title="7. Review, approve, and activate" helper="Your new formula blueprint will appear here after generation."><p className="text-sm text-slate-500">No V2 blueprint yet.</p></Section>}
				</>
			) : <Section title="Copy Register V2" helper="Select a product to begin the guarded workflow."><p className="text-sm text-slate-500">Select a Product Truth-approved product first.</p></Section>}
		</div>
	);
}
