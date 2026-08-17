import { BookOpen, ChevronLeft, ChevronRight, PenLine, Search, ShieldCheck, Sparkles } from "lucide-react";
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
import { Badge, type BadgeTone, FormField, HelperText, Section } from "../components/ui";
import { TechnicalDetails } from "../components/ui/TechnicalDetails";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { Product } from "../types";
import { useProductCatalog } from "../hooks/useProductCatalog";

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
	const message = error instanceof Error ? error.message : "Copy Register request failed.";
	const jsonStart = message.indexOf("{");
	if (jsonStart < 0) return message;
	try {
		const payload = JSON.parse(message.slice(jsonStart));
		const detail = payload?.detail;
		if (detail?.error && detail?.detail) return `${detail.error}: ${detail.detail}`;
	} catch {
		// Preserve original transport error
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

function extractHook(bp: CopyBlueprintV2Record): string {
	const proj = bp.derived_projection as { derived_copy?: { hook?: string } } | null | undefined;
	if (proj?.derived_copy?.hook) return proj.derived_copy.hook;
	const hookStage = bp.stages?.find(
		(s) =>
			s.semantic_role?.toUpperCase() === "HOOK" ||
			s.formula_stage_key?.toLowerCase().includes("hook"),
	);
	return hookStage?.authored_text || bp.stages?.[0]?.authored_text || "—";
}

function extractBody(bp: CopyBlueprintV2Record): string {
	const proj = bp.derived_projection as { derived_copy?: { body?: string } } | null | undefined;
	if (proj?.derived_copy?.body) return proj.derived_copy.body;
	const bodyStages = bp.stages?.filter(
		(s) =>
			s.semantic_role?.toUpperCase() !== "HOOK" &&
			s.semantic_role?.toUpperCase() !== "CTA" &&
			!s.formula_stage_key?.toLowerCase().includes("hook") &&
			!s.formula_stage_key?.toLowerCase().includes("cta"),
	);
	if (bodyStages?.length) {
		return bodyStages.map((s) => s.authored_text).join(" ");
	}
	if ((bp.stages?.length ?? 0) > 2) {
		return bp.stages.slice(1, -1).map((s) => s.authored_text).join(" ");
	}
	return bp.stages?.[1]?.authored_text || "";
}

function extractCta(bp: CopyBlueprintV2Record): string {
	const proj = bp.derived_projection as { derived_copy?: { cta?: string } } | null | undefined;
	if (proj?.derived_copy?.cta) return proj.derived_copy.cta;
	const ctaStage = bp.stages?.find(
		(s) =>
			s.semantic_role?.toUpperCase() === "CTA" ||
			s.formula_stage_key?.toLowerCase().includes("cta"),
	);
	if (ctaStage) return ctaStage.authored_text;
	if ((bp.stages?.length ?? 0) > 1) {
		return bp.stages[bp.stages.length - 1].authored_text;
	}
	return "—";
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
						<span className="font-semibold text-sm text-slate-200">
							{blueprint.angle?.definition || "Copy Blueprint"}
						</span>
						<span className="text-xs text-slate-500">
							{blueprint.formula_id} · {blueprint.estimated_word_count} words
						</span>
					</div>
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

			<div className="mt-3 space-y-2">
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
					</div>
				))}
			</div>

			<TechnicalDetails title="Technical details" className="mt-3">
				<div className="space-y-1 font-mono text-[11px]">
					<div>Blueprint ID: {blueprint.blueprint_id} · revision {blueprint.revision}</div>
					<div>Formula: {blueprint.formula_id} · {blueprint.formula_version}</div>
					<div>Objective: {blueprint.objective.definition}</div>
					<div>Formula valid: {formulaValid ? "YES" : "NO"}</div>
					<div>Evidence valid: {evidenceValid ? "YES" : "NO"}</div>
					<div>Bridge valid: {bridgeValid ? "YES" : "NO"}</div>
					{blueprint.current_authority_fingerprint ? (
						<div>Fingerprint: {blueprint.current_authority_fingerprint}</div>
					) : null}
				</div>
			</TechnicalDetails>
		</div>
	);
}

export default function CopySetRegistryPage() {
	const [searchParams, setSearchParams] = useSearchParams();
	const { products, isLoadingProducts, productsError } = useProductCatalog(50);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [activeTab, setActiveTab] = useState<"GENERATOR" | "LIBRARY">("GENERATOR");

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

	// Library view search & filter & pagination
	const [librarySearch, setLibrarySearch] = useState("");
	const [libraryAngleFilter, setLibraryAngleFilter] = useState("ALL");
	const [libraryPage, setLibraryPage] = useState(1);
	const LIBRARY_PAGE_SIZE = 4;

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
			setSuccess(`New copy set ${response.blueprint.blueprint_id} created as DRAFT. Review is still required.`);
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
			setSuccess(`Stage regenerated as revision ${response.new_revision}; parent remains immutable.`);
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
					rationale: "Reviewed against displayed Product Truth and safety gates.",
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
			setSuccess("Explicit approval recorded. Blueprint is now PRODUCTION_VALID.");
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setBusy(false);
		}
	};

	// Library filtering & pagination
	const libraryAngles = useMemo(() => {
		const map = new Map<string, string>();
		for (const b of blueprints) {
			if (b.angle?.angle_id && b.angle?.definition) {
				map.set(b.angle.angle_id, b.angle.definition);
			}
		}
		return Array.from(map.entries()).map(([id, def]) => ({ id, definition: def }));
	}, [blueprints]);

	const filteredLibraryBlueprints = useMemo(() => {
		return blueprints.filter((b) => {
			if (libraryAngleFilter !== "ALL" && b.angle?.angle_id !== libraryAngleFilter && b.angle?.definition !== libraryAngleFilter) {
				return false;
			}
			if (librarySearch.trim()) {
				const q = librarySearch.toLowerCase();
				const hook = extractHook(b).toLowerCase();
				const body = extractBody(b).toLowerCase();
				const angle = (b.angle?.definition || "").toLowerCase();
				if (!hook.includes(q) && !body.includes(q) && !angle.includes(q)) {
					return false;
				}
			}
			return true;
		});
	}, [blueprints, libraryAngleFilter, librarySearch]);

	const libraryTotalPages = Math.max(1, Math.ceil(filteredLibraryBlueprints.length / LIBRARY_PAGE_SIZE));
	const paginatedLibraryBlueprints = useMemo(() => {
		const start = (libraryPage - 1) * LIBRARY_PAGE_SIZE;
		return filteredLibraryBlueprints.slice(start, start + LIBRARY_PAGE_SIZE);
	}, [filteredLibraryBlueprints, libraryPage]);

	return (
		<div className="mx-auto max-w-6xl space-y-6 p-4 md:p-8" data-testid="copy-set-registry-page">
			<header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-5">
				<div>
					<div className="flex items-center gap-2 text-blue-300">
						<PenLine size={20} />
						<span className="text-[10px] font-bold uppercase tracking-[0.2em]">Creative Hub</span>
					</div>
					<h1 className="mt-1 text-2xl font-bold text-slate-100">Copy Register</h1>
					<p className="mt-1 text-xs text-slate-400">
						Guided copywriting generator & approved copy library for video and image production.
					</p>
				</div>

				{/* Two Main Job Views: Copy Generator vs Generated Copy Library */}
				<div className="flex rounded-xl border border-slate-800 bg-slate-950 p-1">
					<button
						type="button"
						onClick={() => setActiveTab("GENERATOR")}
						className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold transition-colors ${
							activeTab === "GENERATOR"
								? "bg-blue-600/30 text-blue-200 border border-blue-500/40"
								: "text-slate-400 hover:text-slate-200"
						}`}
					>
						<Sparkles size={14} />
						<span>Copy Generator</span>
					</button>

					<button
						type="button"
						onClick={() => {
							setActiveTab("LIBRARY");
							setLibraryPage(1);
						}}
						className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold transition-colors ${
							activeTab === "LIBRARY"
								? "bg-blue-600/30 text-blue-200 border border-blue-500/40"
								: "text-slate-400 hover:text-slate-200"
						}`}
					>
						<BookOpen size={14} />
						<span>Copy Library</span>
						{blueprints.length ? (
							<span className="rounded-full bg-blue-500/20 px-2 py-0.5 text-[10px] text-blue-300">
								{blueprints.length}
							</span>
						) : null}
					</button>
				</div>
			</header>

			{error ? <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100" data-testid="copy-registry-error">{error}</p> : null}
			{success ? <p className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100" data-testid="copy-registry-success">{success}</p> : null}

			{/* Section 1: Always Select Product */}
			<Section title="1. Select product" helper="Choose a registered product to generate or manage its copywriting.">
				<div className="max-w-xl">
					<SearchableProductSelect
						products={products}
						selectedProduct={selectedProduct}
						onSelect={selectProduct}
						isLoadingProducts={isLoadingProducts}
						productsError={productsError}
						showReadinessBadge={false}
					/>
				</div>
			</Section>

			{selectedProduct && activeTab === "GENERATOR" ? (
				<>
					{/* Section 2: Product Truth proof */}
					<Section
						title="2. Product Truth proof"
						helper="Read-only upstream authority; claims and angles are grounded in this product's approved facts."
						action={truth ? <Badge tone={truthTone(truth)}>{truth.ready_for_copy ? "APPROVED · READY" : "BLOCKED"}</Badge> : null}
					>
						{truth ? (
							<div className="space-y-3 text-xs text-slate-300" data-testid="product-truth-proof">
								<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
									<div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3" data-testid="canonical-taxonomy-proof">
										<p className="font-bold uppercase tracking-wider text-blue-200">Product Taxonomy</p>
										<p className="mt-2"><span className="text-slate-500">Category: </span>{truth.product.category || "—"}</p>
										<p><span className="text-slate-500">Type: </span>{truth.product.product_type || "—"}</p>
										<p><span className="text-slate-500">Subcategory: </span>{truth.product.subcategory || "—"}</p>
									</div>
									<div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
										<p className="font-bold uppercase tracking-wider text-blue-200">Copywriting Cluster</p>
										<p className="mt-2 text-sm text-slate-100">{truth.product.canonical_copy_cluster || truth.product.cluster || "—"}</p>
										<p className="mt-1 text-[10px] text-slate-500">Taxonomy cluster authority.</p>
									</div>
									<div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
										<p className="font-bold uppercase tracking-wider text-blue-200">Allowed Claims</p>
										<p className="mt-2 text-xs text-slate-100">
											{truth.product_truth.allowed_claims.join(" · ") || "Standard product claims"}
										</p>
									</div>
								</div>

								{truth.blockers.length ? (
									<HelperText tone="warn">Blockers: {truth.blockers.join("; ")}</HelperText>
								) : (
									<HelperText className="text-emerald-300/80">Product Truth lineage and claim gate are ready for formula copy.</HelperText>
								)}

								<TechnicalDetails title="Technical details">
									<div className="space-y-1 font-mono text-[11px]">
										{truth.authority?.authority_fingerprint ? (
											<div>Authority fingerprint: {truth.authority.authority_fingerprint}</div>
										) : null}
										{truth.product_truth.snapshot ? (
											<div>Snapshot: {truth.product_truth.snapshot.snapshot_id} · v{truth.product_truth.snapshot.version} · {truth.product_truth.snapshot.digest.slice(0, 16)}…</div>
										) : null}
										<div>Persona: {JSON.stringify(truth.product_truth.persona)}</div>
									</div>
								</TechnicalDetails>
							</div>
						) : <p className="text-sm text-slate-400">Loading Product Truth…</p>}
					</Section>

					{/* Section 3: Choose formula */}
					<Section title="3. Choose explicit formula" helper="Select the marketing copy framework.">
						<div className="max-w-xl">
							<label className="text-xs font-semibold text-slate-300" htmlFor="v2-formula-picker">Copy Formula</label>
							<select id="v2-formula-picker" data-testid="v2-formula-picker" value={formulaId} onChange={(event) => { setFormulaId(event.target.value); setAngles([]); setSelectedAngleId(""); }} className={INPUT_CLASS}>
								<option value="">Select formula — required</option>
								{formulas.map((formula) => <option key={formula.formula_id} value={formula.formula_id}>{formula.display_name} · {formula.formula_id}</option>)}
							</select>
							{formulaId ? <HelperText className="text-emerald-300/80">{formulas.find((formula) => formula.formula_id === formulaId)?.formula_version}</HelperText> : <HelperText tone="warn">No default formula is allowed.</HelperText>}
						</div>
					</Section>

					{/* Section 4: Generate Angles */}
					<Section title="4. Generate grounded angle options" helper="Derived from approved Product Truth facts." action={<Badge tone={textAssistReady ? "success" : "warn"}>Text Assist · {textAssistStatus?.status ?? "UNAVAILABLE"}</Badge>}>
						<button type="button" data-testid="generate-angle-options" disabled={busy || angleDisabledReasons.length > 0} onClick={() => void handleGenerateAngles()} className="rounded-xl border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40">{busy ? "Generating…" : "Generate Angle Options"}</button>
						<DisabledReasons reasons={angleDisabledReasons} testId="generate-angle-disabled-reasons" />
						{angles.length ? <div className="mt-4 grid gap-2 md:grid-cols-2" data-testid="angle-options">{angles.map((angle) => <label key={angle.angle_id} className={`cursor-pointer rounded-lg border p-3 text-sm ${selectedAngleId === angle.angle_id ? "border-blue-400 bg-blue-500/10 text-blue-100" : "border-slate-800 text-slate-300"}`}><input type="radio" name="v2-angle" value={angle.angle_id} checked={selectedAngleId === angle.angle_id} onChange={() => setSelectedAngleId(angle.angle_id)} className="mr-2" />{angle.definition}</label>)}</div> : <p className="mt-3 text-xs text-slate-500">Press the button after selecting a formula.</p>}
					</Section>

					{/* Section 5: Select Facts */}
					<Section title="5. Select evidence-backed USP facts" helper="Select 1 to 5 facts to anchor the copy.">
						<div className="space-y-2" data-testid="evidence-facts">
							{facts.map((fact) => <label key={fact.fact_id} className="flex cursor-pointer gap-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-sm text-slate-300"><input type="checkbox" checked={selectedFactIds.includes(fact.fact_id)} onChange={() => toggleFact(fact.fact_id)} disabled={!selectedFactIds.includes(fact.fact_id) && selectedFactIds.length >= 5} /><span className="flex-1"><span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase text-slate-400">{fact.fact_kind}</span><span className="mt-1 block">{fact.text}</span></span></label>)}
							{facts.length === 0 ? <p className="text-xs text-slate-500">Generate angle options to load approved evidence facts.</p> : null}
						</div>
						<p className="mt-3 text-xs text-slate-500">Selected {selectedFactIds.length}/5</p>
					</Section>

					{/* Section 6: Generate Blueprint */}
					<Section title="6. Generate the complete formula blueprint" helper="Requires a selected angle and at least one approved evidence fact.">
						<button type="button" data-testid="generate-new-formula-copy" disabled={busy || blueprintDisabledReasons.length > 0} onClick={() => void handleGenerateBlueprint()} className="rounded-xl border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40">{busy ? "Generating…" : "GENERATE NEW FORMULA COPY"}</button>
						<DisabledReasons reasons={blueprintDisabledReasons} testId="generate-blueprint-disabled-reasons" />
						<HelperText className="text-blue-300/80">This step makes one additional text-assist call; it does not spend video/image credits.</HelperText>
					</Section>

					{/* Section 7: Review & Approve */}
					{latestBlueprint ? (
						<Section title="7. Review, approve, and activate" helper="Approved text is immutable. Activation atomically makes this blueprint authoritative for all required lanes.">
							<div className="space-y-3">
								{blueprints.map((item, index) => (
									<BlueprintCard key={`${item.blueprint_id}:${item.revision}`} blueprint={item} onRegenerate={(stageKey) => void handleRegenerate(stageKey)} busy={busy} allowRegenerate={index === 0} />
								))}
							</div>
							{reviewableBlueprint ? (
								<div className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4" data-testid="v2-approval-panel">
									<div className="flex items-center gap-2 text-sm font-semibold text-amber-100"><ShieldCheck size={16} />Explicit human approval</div>
									<FormField label="Reviewer" className="mt-3 max-w-sm"><input className={INPUT_CLASS} value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></FormField>
									<div className="mt-3 grid gap-2 text-xs text-slate-300 sm:grid-cols-2">
										{[
											["semantic", "I reviewed every authored stage against Product Truth."],
											["provenance", "Product Truth and evidence lineage match the selected product."],
											["safety", "Allowed claims and warnings were reviewed; no unsafe claim was added."],
											["bridge", "Formula order and bridge continuity are coherent."],
											["duration", "Word count and target-lane duration readiness were reviewed."],
										].map(([key, label]) => (
											<label key={key} className="flex cursor-pointer items-start gap-2 rounded border border-slate-800 p-2">
												<input type="checkbox" data-testid={`approval-check-${key}`} checked={approvalChecks[key as keyof typeof approvalChecks]} onChange={(event) => setApprovalChecks((current) => ({ ...current, [key]: event.target.checked }))} />
												<span>{label}</span>
											</label>
										))}
									</div>
									<button type="button" data-testid="approve-v2-blueprint" disabled={busy || !reviewer.trim() || !approvalReady} onClick={() => void handleApprove()} className="mt-4 rounded-xl border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40">{busy ? "Approving…" : "Approve → PRODUCTION_VALID"}</button>
								</div>
							) : (
								<div className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
									<HelperText className="text-emerald-300/80">Approved copy is immutable. Activation never changes its approved text.</HelperText>
									{latestBlueprint.current_authority_activation_allowed === false ? <HelperText className="mt-2 text-amber-200/80">Activation disabled: {latestBlueprint.current_authority_reason ?? "current authority validation is not satisfied"}.</HelperText> : null}
									<button type="button" data-testid="activate-v2-blueprint" disabled={busy || latestBlueprint.current_authority_activation_allowed !== true || activatedBlueprintId === latestBlueprint.blueprint_id} onClick={() => void handleActivate(latestBlueprint)} className="mt-3 rounded-xl border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40">{activatedBlueprintId === latestBlueprint.blueprint_id ? "ACTIVE · 8 REQUIRED LANES" : busy ? "Activating…" : "ACTIVATE FOR VIDEO + POSTER LANES"}</button>
								</div>
							)}
						</Section>
					) : (
						<Section title="7. Review, approve, and activate" helper="Your new formula blueprint will appear here after generation.">
							<p className="text-sm text-slate-500">No copy blueprint yet.</p>
						</Section>
					)}
				</>
			) : null}

			{/* VIEW 2: GENERATED COPY LIBRARY */}
			{selectedProduct && activeTab === "LIBRARY" ? (
				<div className="space-y-4" data-testid="copy-library-view">
					<div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
						{/* Search */}
						<div className="relative flex-1 min-w-[200px]">
							<Search className="absolute left-3 top-2.5 text-slate-500" size={15} />
							<input
								type="text"
								placeholder="Search copy by hook, body or angle..."
								value={librarySearch}
								onChange={(e) => {
									setLibrarySearch(e.target.value);
									setLibraryPage(1);
								}}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 pl-9 pr-3 py-1.5 text-xs text-slate-200"
							/>
						</div>

						{/* Angle Filter */}
						<div className="flex items-center gap-2">
							<span className="text-xs text-slate-400">Angle:</span>
							<select
								value={libraryAngleFilter}
								onChange={(e) => {
									setLibraryAngleFilter(e.target.value);
									setLibraryPage(1);
								}}
								className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs text-slate-200"
							>
								<option value="ALL">All Angles ({blueprints.length})</option>
								{libraryAngles.map((a) => (
									<option key={a.id} value={a.id}>
										{a.definition}
									</option>
								))}
							</select>
						</div>
					</div>

					{/* Library Cards */}
					{paginatedLibraryBlueprints.length === 0 ? (
						<div className="rounded-xl border border-dashed border-slate-800 p-8 text-center text-xs text-slate-500">
							<p>No copy sets found matching your filter.</p>
							<button
								type="button"
								onClick={() => setActiveTab("GENERATOR")}
								className="mt-3 rounded-lg bg-blue-600/20 border border-blue-500/40 px-3 py-1.5 text-xs font-semibold text-blue-200"
							>
								Generate New Copy
							</button>
						</div>
					) : (
						<div className="grid gap-4 sm:grid-cols-2">
							{paginatedLibraryBlueprints.map((bp) => {
								const hook = extractHook(bp);
								const body = extractBody(bp);
								const cta = extractCta(bp);
								const isCurrent = bp.blueprint_id === activatedBlueprintId;

								return (
									<div
										key={`${bp.blueprint_id}:${bp.revision}`}
										className={`flex flex-col justify-between rounded-xl border p-4 transition-colors ${
											isCurrent
												? "border-emerald-500/50 bg-emerald-500/10"
												: "border-slate-800 bg-slate-950/70"
										}`}
									>
										<div className="space-y-3 text-xs">
											<div className="flex items-center justify-between gap-2">
												<span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] font-semibold uppercase text-slate-300">
													{bp.angle?.definition || "General Angle"}
												</span>
												<Badge tone={isCurrent ? "success" : bp.status === "PRODUCTION_VALID" ? "info" : "warn"}>
													{isCurrent ? "ACTIVE" : bp.status}
												</Badge>
											</div>

											<div>
												<span className="text-[9px] font-bold uppercase tracking-wider text-slate-500">
													Hook
												</span>
												<p className="font-medium text-slate-100">"{hook}"</p>
											</div>

											{body ? (
												<div>
													<span className="text-[9px] font-bold uppercase tracking-wider text-slate-500">
														Body
													</span>
													<p className="line-clamp-3 text-slate-300">{body}</p>
												</div>
											) : null}

											{cta && cta !== "—" ? (
												<div>
													<span className="text-[9px] font-bold uppercase tracking-wider text-slate-500">
														CTA
													</span>
													<p className="font-semibold text-blue-200">{cta}</p>
												</div>
											) : null}
										</div>

										<div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between">
											<span className="text-[10px] text-slate-500">
												{bp.estimated_word_count ? `${bp.estimated_word_count} words` : ""}
												{bp.target_duration_seconds ? ` · ${bp.target_duration_seconds}s` : ""}
											</span>

											<button
												type="button"
												disabled={busy || isCurrent || bp.status !== "PRODUCTION_VALID"}
												onClick={() => void handleActivate(bp)}
												className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors ${
													isCurrent
														? "bg-emerald-500/20 text-emerald-300"
														: bp.status !== "PRODUCTION_VALID"
															? "bg-slate-800 text-slate-500 cursor-not-allowed"
															: "bg-blue-600 text-white hover:bg-blue-500"
												}`}
											>
												{isCurrent ? "Active in Creator" : bp.status !== "PRODUCTION_VALID" ? "Approval Required" : "Activate Authority"}
											</button>
										</div>
									</div>
								);
							})}
						</div>
					)}

					{/* Pagination Controls */}
					{libraryTotalPages > 1 && (
						<div className="flex items-center justify-between border-t border-slate-800 pt-3 text-xs text-slate-400">
							<span>
								Showing page {libraryPage} of {libraryTotalPages} ({filteredLibraryBlueprints.length} total)
							</span>
							<div className="flex items-center gap-2">
								<button
									type="button"
									disabled={libraryPage <= 1}
									onClick={() => setLibraryPage((p) => Math.max(1, p - 1))}
									className="flex items-center gap-1 rounded-lg border border-slate-800 px-3 py-1 hover:bg-slate-800 disabled:opacity-30"
								>
									<ChevronLeft size={14} /> Previous
								</button>
								<button
									type="button"
									disabled={libraryPage >= libraryTotalPages}
									onClick={() => setLibraryPage((p) => Math.min(libraryTotalPages, p + 1))}
									className="flex items-center gap-1 rounded-lg border border-slate-800 px-3 py-1 hover:bg-slate-800 disabled:opacity-30"
								>
									Next <ChevronRight size={14} />
								</button>
							</div>
						</div>
					)}
				</div>
			) : null}

			{!selectedProduct && (
				<Section title="Copy Register" helper="Select a product to begin.">
					<p className="text-sm text-slate-500">Select a Product Truth-approved product first.</p>
				</Section>
			)}
		</div>
	);
}
