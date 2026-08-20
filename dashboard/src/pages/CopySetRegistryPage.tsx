import { BookOpen, ChevronLeft, ChevronRight, Search, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
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
import { fetchProductDetail } from "../api/products";

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

// SINGLE AUTHORITY RULE (shared by Direct V2 Authoring + Authority Library):
// a blueprint may be activated ONLY when the backend projects the CURRENT
// authority as activatable. The persisted/historical status (PRODUCTION_VALID,
// V2_APPROVED) is lineage history and NEVER independently authorizes activation —
// treating a stale historical status as authority is exactly what produced the
// COPY_V2_EVIDENCE_STALE activation-409 the operator reported. The activation
// endpoint remains the final, fail-closed enforcement boundary; this only stops
// the UI from offering an impossible action.
function canActivateAuthority(blueprint: CopyBlueprintV2Record): boolean {
	return blueprint.current_authority_activation_allowed === true;
}

// A DRAFT is REVIEWABLE (eligible for the human approval workflow) when the
// backend projects the current authority as valid — i.e. the product truth is
// ready and the blueprint's lineage matches it, so only the explicit human
// approval step is outstanding. A DRAFT whose current authority is NOT valid is
// BLOCKED (stale/incomplete product truth): it cannot be approved as-is and must
// be revalidated/regrounded first. This never auto-approves — it only decides
// whether to route the operator into the (still fully-gated) approval workflow.
function isDraftReviewable(blueprint: CopyBlueprintV2Record): boolean {
	return blueprint.status === "DRAFT" && blueprint.current_authority_valid === true;
}

// Render the backend-projected current-authority reason in operator-friendly form
// without hiding the underlying authority code.
function authorityReasonLabel(reason?: string | null): string {
	if (!reason) return "Current production authority is not satisfied for this blueprint.";
	const friendly: Record<string, string> = {
		COPY_V2_EVIDENCE_STALE:
			"The approved copy no longer matches the current Product Truth / evidence lineage.",
		COPY_V2_TAXONOMY_AUTHORITY_STALE:
			"The product's canonical taxonomy authority advanced after this copy was approved.",
		STALE_AUTHORITY_LINEAGE:
			"This approval's Product Truth lineage is stale versus the current product authority.",
		EXPLICIT_HUMAN_APPROVAL_REQUIRED: "This blueprint has not been approved yet.",
		BLUEPRINT_NOT_PRODUCTION_VALID: "This blueprint is not in a production-approved state.",
		V2_PRODUCT_TRUTH_APPROVAL_REQUIRED: "The product's Product Truth is not approved yet.",
		V2_PRODUCT_TRUTH_TAXONOMY_DRIFT: "The product's canonical taxonomy drifted from the approved authority.",
		PRODUCT_IDENTITY_STALE: "The product identity in this copy no longer matches the approved product.",
	};
	return friendly[reason] ?? reason;
}

// A DRAFT's authority reason carries the always-present EXPLICIT_HUMAN_APPROVAL_REQUIRED
// note plus any genuine blocking codes. When surfacing WHY a draft is blocked, strip
// the redundant "not approved yet" note so the operator sees the real corrective cause.
function draftBlockedReason(blueprint: CopyBlueprintV2Record): string {
	const raw = (blueprint.current_authority_reason ?? "")
		.split(",")
		.map((code) => code.trim())
		.filter((code) => code && code !== "EXPLICIT_HUMAN_APPROVAL_REQUIRED");
	if (!raw.length) {
		return "The current Product Truth is not ready for this draft.";
	}
	return raw.map((code) => authorityReasonLabel(code)).join(" · ");
}

// Auto-anchor the evidence facts a chosen angle is already grounded in
// (angle.evidence_fact_ids), capped at the 1–5 the blueprint generator accepts.
// This removes the redundant manual fact-picking step — the same auto-map the
// shared CopywritingSourceSelector already performs — while keeping the facts
// fully adjustable for exception cases.
function anchorFactsFromAngle(angle: CopyAngleOptionV2 | undefined | null): string[] {
	return (angle?.evidence_fact_ids ?? []).slice(0, 5);
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
	isReviewTarget,
	onSelectReview,
}: {
	blueprint: CopyBlueprintV2Record;
	onRegenerate: (stageKey: string) => void;
	busy: boolean;
	allowRegenerate: boolean;
	isReviewTarget: boolean;
	onSelectReview: () => void;
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
			className={`rounded-xl border p-4 ${isReviewTarget ? "border-blue-500/50 bg-blue-500/5" : "border-slate-800 bg-slate-950/70"}`}
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
						{isReviewTarget ? (
							<span className="rounded-full bg-blue-500/20 px-2 py-0.5 text-[10px] font-bold uppercase text-blue-200" data-testid={`review-target-${blueprint.blueprint_id}`}>
								Reviewing
							</span>
						) : null}
					</div>
				</div>
				<div className="flex items-center gap-2">
					{/* RULE 3: an operator selects the EXACT blueprint to review; the
					    approval workflow acts on this selection, never blueprints[0]. */}
					{!isReviewTarget ? (
						<button
							type="button"
							data-testid={`select-review-${blueprint.blueprint_id}`}
							disabled={busy}
							onClick={onSelectReview}
							className="rounded border border-slate-600 px-2 py-1 text-[10px] font-bold uppercase text-slate-200 hover:bg-slate-800 disabled:opacity-40"
						>
							Select for review
						</button>
					) : null}
					<Badge tone={authorityStatus === "CURRENT · PRODUCTION_VALID" || authorityCurrent ? "success" : "warn"}>
						{authorityStatus}
					</Badge>
				</div>
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
	// Copy Authority is an inspection-first console: default to the authority
	// library, not the direct (advanced) generator.
	const [activeTab, setActiveTab] = useState<"GENERATOR" | "LIBRARY">("LIBRARY");

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
	// RULE 3: the operator acts on the EXACT blueprint they selected — never a
	// silent blueprints[0] substitution. This holds the explicitly selected review
	// target, set by: "Review & Approve"/"Revalidate" from the Library, a
	// blueprint_id deep-link, or a fresh generation.
	const [reviewBlueprintId, setReviewBlueprintId] = useState("");
	const reviewPanelRef = useRef<HTMLDivElement>(null);
	// RULE 3: a blueprint_id deep-link that cannot be resolved fails VISIBLY here;
	// it never silently falls back to another blueprint.
	const [deepLinkError, setDeepLinkError] = useState("");
	// Task B §4: global activation is an advanced, high-consequence action. Hold the
	// target blueprint here and require explicit confirmation before calling
	// activateFormulaBlueprint (which changes the sole V2 authority for all creator
	// lanes). Never auto-activate.
	const [pendingActivation, setPendingActivation] = useState<CopyBlueprintV2Record | null>(null);
	// Dedupes an in-flight by-id product resolution (cleared on settle) so the
	// deep-link fetch is not fired twice for the same product id.
	const productResolveRef = useRef("");

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
	// RULE 3: resolve the EXACT selected blueprint. Only when nothing is explicitly
	// selected (fresh authoring) does this fall back to the newest blueprint.
	const reviewTarget = useMemo(() => {
		if (reviewBlueprintId) {
			const selected = blueprints.find((b) => b.blueprint_id === reviewBlueprintId);
			if (selected) return selected;
		}
		return latestBlueprint;
	}, [blueprints, reviewBlueprintId, latestBlueprint]);
	const reviewableBlueprint = reviewTarget && reviewTarget.status !== "PRODUCTION_VALID" ? reviewTarget : null;
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

	// Resolve the ?product_id= deep-link to the EXACT product. Fast path: the product
	// is inside the loaded catalog window (useProductCatalog(50)). An out-of-window
	// product (e.g. beyond the first 50 — proven by canonical MWCB) resolves via the
	// deterministic by-id product-detail seam (fetchProductDetail) — NO full-catalog
	// eager load. An invalid product_id fails VISIBLY; another product is never
	// silently substituted (the resolved row's id must equal the requested id).
	useEffect(() => {
		const productId = searchParams.get("product_id");
		if (!productId || selectedProduct?.id === productId) return;
		const inWindow = products.find((item) => item.id === productId);
		if (inWindow) {
			setDeepLinkError("");
			setSelectedProduct(inWindow);
			return;
		}
		// Wait for the catalog window to finish loading before falling back to a
		// by-id fetch, so an in-window product uses the fast path.
		if (isLoadingProducts) return;
		if (productResolveRef.current === productId) return; // resolution already in flight
		productResolveRef.current = productId;
		let cancelled = false;
		void fetchProductDetail(productId)
			.then((detail) => {
				if (cancelled) return;
				if (detail && detail.id === productId) {
					setDeepLinkError("");
					setSelectedProduct(detail);
				} else {
					// Defensive: never substitute a different product than the one requested.
					setDeepLinkError(`Product ${productId} could not be resolved for this deep link.`);
				}
			})
			.catch(() => {
				if (!cancelled) {
					setDeepLinkError(
						`Product ${productId} was not found or could not be loaded. Check the link, or select a product above.`,
					);
				}
			})
			.finally(() => {
				if (productResolveRef.current === productId) productResolveRef.current = "";
			});
		return () => {
			cancelled = true;
		};
	}, [products, searchParams, selectedProduct?.id, isLoadingProducts]);

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
		setDeepLinkError("");
		// RULE 4: a product switch clears stale library UI + the prior selection so
		// the new product's blueprints are never hidden behind a stale filter and no
		// action can target a previous product's blueprint.
		setLibrarySearch("");
		setLibraryAngleFilter("ALL");
		setLibraryPage(1);
		setReviewBlueprintId("");
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

	// RULE 3: resolve a blueprint_id deep-link to the EXACT blueprint — select it
	// and route into the review workflow — or fail visibly. Never silently ignore
	// the parameter or substitute another blueprint. Runs once the product's
	// blueprints have loaded.
	useEffect(() => {
		const blueprintId = searchParams.get("blueprint_id");
		if (!blueprintId || !selectedProduct || !blueprints.length) return;
		if (reviewBlueprintId === blueprintId) return; // already resolved
		const found = blueprints.find((b) => b.blueprint_id === blueprintId);
		if (found) {
			setDeepLinkError("");
			setReviewBlueprintId(blueprintId);
			setActiveTab("LIBRARY");
		} else {
			setDeepLinkError(
				`Blueprint ${blueprintId} was not found for this product. It may have been superseded, or the link points to a different product.`,
			);
		}
	}, [blueprints, searchParams, selectedProduct, reviewBlueprintId]);

	// When a blueprint is picked for review, bring the approval panel into view — it
	// renders above the library cards, so a click on a lower card must scroll to it,
	// otherwise the panel updates off-screen and the action looks like it did nothing.
	useEffect(() => {
		if (reviewBlueprintId && activeTab === "LIBRARY") {
			reviewPanelRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
		}
	}, [reviewBlueprintId, activeTab]);

	const selectProduct = (product: Product | null) => {
		setSelectedProduct(product);
		// A manual selection resolves the product directly — mark it so the deep-link
		// by-id effect does not fire a redundant fetch while the URL updates.
		productResolveRef.current = product ? product.id : "";
		setSearchParams(product ? { product_id: product.id } : {});
		setBlueprints([]);
		setFormulaId("");
		setSelectedAngleId("");
		setAngles([]);
		setSelectedFactIds([]);
		setApprovalChecks(EMPTY_APPROVAL_CHECKS);
		setActivatedBlueprintId("");
		setReviewBlueprintId("");
		setDeepLinkError("");
		setLibrarySearch("");
		setLibraryAngleFilter("ALL");
		setLibraryPage(1);
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
			// The backend is the final authority. If the current authority changed
			// between page load and confirmation (e.g. COPY_V2_EVIDENCE_STALE), stay
			// fail-closed: surface the failure AND refresh the current-authority
			// projection so the card drops its now-impossible "Activate" affordance and
			// shows the truthful stale state. Never hide or downgrade the backend error.
			setError(errorMessage(reason));
			if (selectedProduct) {
				try {
					const refreshed = await listCopyRegisterBlueprints(selectedProduct.id);
					setBlueprints(refreshed.items ?? []);
					setActivatedBlueprintId(refreshed.activation?.active_blueprint_id ?? "");
				} catch {
					// Keep the original activation failure visible.
				}
			}
		} finally {
			setBusy(false);
		}
	};

	// Route the operator to review a specific existing blueprint (RULE 2 + RULE 3):
	// select that EXACT blueprint and open the Direct V2 Authoring review workflow.
	// This NEVER approves — the fully-gated human approval panel still applies.
	const reviewBlueprint = (blueprint: CopyBlueprintV2Record) => {
		setReviewBlueprintId(blueprint.blueprint_id);
		setDeepLinkError("");
		// Approval lives in the Authority Library tab now — stay here, do not bounce
		// the operator into the generation flow.
		setActiveTab("LIBRARY");
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
			// Auto-anchor the first angle and its grounded evidence facts so the
			// operator can go straight to generation — no manual fact mapping.
			const firstAngle = response.angles?.[0];
			setSelectedAngleId(firstAngle?.angle_id ?? "");
			setSelectedFactIds(anchorFactsFromAngle(firstAngle));
			setSuccess("Grounded angle options generated; evidence facts auto-anchored from the top angle.");
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
			// RULE 3: the freshly authored DRAFT becomes the EXPLICIT review target.
			setReviewBlueprintId(response.blueprint.blueprint_id);
			setApprovalChecks(EMPTY_APPROVAL_CHECKS);
			setSuccess(`New copy set ${response.blueprint.blueprint_id} created as DRAFT. Review is still required.`);
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setBusy(false);
		}
	};

	const handleRegenerate = async (blueprintId: string, stageKey: string) => {
		if (!blueprintId) return;
		setBusy(true);
		setError("");
		try {
			const response = await regenerateFormulaStage(blueprintId, stageKey);
			setBlueprints((current) => [response.blueprint, ...current.filter((item) => item.blueprint_id !== response.blueprint.blueprint_id)]);
			// Keep reviewing the same (now-regenerated) blueprint.
			setReviewBlueprintId(response.blueprint.blueprint_id);
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
			// Keep the approved blueprint as the explicit target so the operator can
			// proceed to activation on the exact blueprint they just approved.
			setReviewBlueprintId(response.blueprint.blueprint_id);
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
						<ShieldCheck size={20} />
						<span className="text-[10px] font-bold uppercase tracking-[0.2em]">Advanced</span>
					</div>
					<h1 className="mt-1 text-2xl font-bold text-slate-100" data-testid="copy-authority-title">Copy Authority</h1>
					<p className="mt-1 text-xs text-slate-400">
						Advanced V2 authority inspection, exception authoring and production activation.
					</p>
				</div>

				{/* Two Main Job Views: Copy Generator vs Generated Copy Library */}
				<div className="flex rounded-xl border border-slate-800 bg-slate-950 p-1">
					<button
						type="button"
						data-testid="tab-generator"
						onClick={() => setActiveTab("GENERATOR")}
						className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold transition-colors ${
							activeTab === "GENERATOR"
								? "bg-blue-600/30 text-blue-200 border border-blue-500/40"
								: "text-slate-400 hover:text-slate-200"
						}`}
					>
						<Sparkles size={14} />
						<span>1 · Generate copy</span>
					</button>

					<button
						type="button"
						data-testid="tab-library"
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
						<span>2 · Review, approve &amp; activate</span>
						{blueprints.length ? (
							<span className="rounded-full bg-blue-500/20 px-2 py-0.5 text-[10px] text-blue-300">
								{blueprints.length}
							</span>
						) : null}
					</button>
				</div>
			</header>

			{/* Task B §2: Copy Authority is the ADVANCED console. Normal campaign copy
			    belongs in Copywriting Landbank. Make that explicit and give a one-click
			    bridge that preserves the selected product. */}
			<div
				data-testid="copy-authority-advisory"
				className="flex flex-col gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
			>
				<p className="text-xs text-amber-100/90">
					Normal campaign copy should be created in <span className="font-semibold">Copywriting Landbank</span>.
					Use Copy Authority only for V2 authority inspection, exception authoring, revalidation, or explicit
					production activation.
				</p>
				<a
					href={`/creative/storyboard-landbank-v3${selectedProduct ? `?product_id=${encodeURIComponent(selectedProduct.id)}` : ""}`}
					data-testid="open-copywriting-landbank"
					className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-amber-400/40 bg-amber-500/15 px-3 py-1.5 text-xs font-semibold text-amber-100 hover:bg-amber-500/25"
				>
					<Sparkles size={14} />
					Open Copywriting Landbank
				</a>
			</div>

			{error ? <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100" data-testid="copy-registry-error">{error}</p> : null}
			{deepLinkError ? <p className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100" data-testid="copy-registry-deeplink-error">{deepLinkError}</p> : null}
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
						{angles.length ? <div className="mt-4 grid gap-2 md:grid-cols-2" data-testid="angle-options">{angles.map((angle) => <label key={angle.angle_id} className={`cursor-pointer rounded-lg border p-3 text-sm ${selectedAngleId === angle.angle_id ? "border-blue-400 bg-blue-500/10 text-blue-100" : "border-slate-800 text-slate-300"}`}><input type="radio" name="v2-angle" value={angle.angle_id} checked={selectedAngleId === angle.angle_id} onChange={() => { setSelectedAngleId(angle.angle_id); setSelectedFactIds(anchorFactsFromAngle(angle)); }} className="mr-2" />{angle.definition}</label>)}</div> : <p className="mt-3 text-xs text-slate-500">Press the button after selecting a formula.</p>}
					</Section>

					{/* Section 5: Evidence facts — auto-anchored from the selected angle.
					    The manual editor is tucked behind a collapsible so operators are
					    not forced to map facts one-by-one; adjusting stays available. */}
					<Section title="5. Evidence facts (auto-anchored)" helper="The evidence that grounds this copy is auto-selected from your chosen angle. Adjust only if you need to.">
						<p className="text-xs text-slate-300" data-testid="evidence-facts-summary">
							{selectedAngle
								? `${selectedFactIds.length} evidence fact${selectedFactIds.length === 1 ? "" : "s"} auto-anchored from this angle.`
								: "Select an angle above — its evidence facts anchor the copy automatically."}
						</p>
						<TechnicalDetails title="Adjust anchored facts" className="mt-2">
							<div className="space-y-2" data-testid="evidence-facts">
								{facts.map((fact) => <label key={fact.fact_id} className="flex cursor-pointer gap-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-sm text-slate-300"><input type="checkbox" checked={selectedFactIds.includes(fact.fact_id)} onChange={() => toggleFact(fact.fact_id)} disabled={!selectedFactIds.includes(fact.fact_id) && selectedFactIds.length >= 5} /><span className="flex-1"><span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase text-slate-400">{fact.fact_kind}</span><span className="mt-1 block">{fact.text}</span></span></label>)}
								{facts.length === 0 ? <p className="text-xs text-slate-500">Generate angle options to load approved evidence facts.</p> : null}
							</div>
							<p className="mt-3 text-xs text-slate-500">Selected {selectedFactIds.length}/5</p>
						</TechnicalDetails>
					</Section>

					{/* Section 6: Generate Blueprint */}
					<Section title="6. Generate the complete formula blueprint" helper="Requires a selected angle and at least one approved evidence fact.">
						<button type="button" data-testid="generate-new-formula-copy" disabled={busy || blueprintDisabledReasons.length > 0} onClick={() => void handleGenerateBlueprint()} className="rounded-xl border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40">{busy ? "Generating…" : "GENERATE NEW FORMULA COPY"}</button>
						<DisabledReasons reasons={blueprintDisabledReasons} testId="generate-blueprint-disabled-reasons" />
						<HelperText className="text-blue-300/80">This step makes one additional text-assist call; it does not spend video/image credits.</HelperText>
					</Section>

					{blueprints.length ? (
						<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4" data-testid="generator-handoff">
							<p className="text-sm text-emerald-100">{blueprints.length} copy blueprint{blueprints.length === 1 ? "" : "s"} for this product live in the Authority Library. Review, approve and activate them there.</p>
							<button type="button" data-testid="go-to-authority-library" onClick={() => { setActiveTab("LIBRARY"); setLibraryPage(1); }} className="mt-3 inline-flex items-center gap-2 rounded-xl border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100"><BookOpen size={14} />Go to Authority Library</button>
						</div>
					) : null}
				</>
			) : null}

			{/* Authority Library approval — review, approve and activate live HERE, not in the generator. */}
			{selectedProduct && activeTab === "LIBRARY" && reviewTarget ? (
				<div ref={reviewPanelRef} data-testid="review-approve-panel">
				<Section title="Review, approve, and activate" helper="Pick a blueprint from the library below, then approve or activate it here. Approved text is immutable.">
					<div className="mb-3 flex items-center justify-between gap-2">
						<p className="text-xs text-blue-200/90" data-testid="review-target-indicator">Reviewing <span className="font-mono">{reviewTarget.blueprint_id}</span> · rev {reviewTarget.revision} · {reviewTarget.status}</p>
						<button type="button" data-testid="close-review" onClick={() => setReviewBlueprintId("")} className="rounded-lg border border-slate-700 px-3 py-1 text-[10px] font-bold uppercase text-slate-300 hover:bg-slate-800">Back to list</button>
					</div>
					<div className="mb-4">
						<BlueprintCard blueprint={reviewTarget} onRegenerate={(stageKey) => void handleRegenerate(reviewTarget.blueprint_id, stageKey)} busy={busy} allowRegenerate={true} isReviewTarget={true} onSelectReview={() => {}} />
					</div>
							{reviewableBlueprint ? (
								isDraftReviewable(reviewableBlueprint) ? (
									<div className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4" data-testid="v2-approval-panel">
										<div className="flex items-center gap-2 text-sm font-semibold text-amber-100"><ShieldCheck size={16} />Explicit human approval</div>
										<FormField label="Reviewer" className="mt-3 max-w-sm"><input className={INPUT_CLASS} data-testid="v2-reviewer-input" value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></FormField>
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
										<DisabledReasons reasons={[...(!reviewer.trim() ? ["reviewer name required"] : []), ...(!approvalReady ? ["tick all 5 review checkboxes"] : [])]} testId="approve-disabled-reasons" />
									</div>
								) : (
									<div className="mt-4 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4" data-testid="v2-approval-blocked-panel">
										<div className="flex items-center gap-2 text-sm font-semibold text-amber-100"><ShieldCheck size={16} />Approval blocked</div>
										<HelperText tone="warn" className="mt-2">This draft cannot be approved as-is: {draftBlockedReason(reviewableBlueprint)}</HelperText>
										<HelperText className="mt-2 text-amber-200/80">Corrective path: regenerate a stage against the current Product Truth (below), or fix the product's Product Truth, then review again. Approval is never automatic.</HelperText>
									</div>
								)
							) : (
								<div className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
									<HelperText className="text-emerald-300/80">Approved copy is immutable. Activation never changes its approved text.</HelperText>
									{!canActivateAuthority(reviewTarget) ? <HelperText className="mt-2 text-amber-200/80">Activation disabled: {authorityReasonLabel(reviewTarget.current_authority_reason)}</HelperText> : null}
									<button type="button" data-testid="activate-v2-blueprint" disabled={busy || !canActivateAuthority(reviewTarget) || activatedBlueprintId === reviewTarget.blueprint_id} onClick={() => setPendingActivation(reviewTarget)} className="mt-3 rounded-xl border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40">{activatedBlueprintId === reviewTarget.blueprint_id ? "ACTIVE · 8 REQUIRED LANES" : busy ? "Activating…" : "ACTIVATE FOR VIDEO + POSTER LANES"}</button>
								</div>
							)}
				</Section>
				</div>
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
								// AUTHORITY RULE — identical to Direct V2 Authoring and the shared
								// CopywritingSourceSelector: activation is permitted ONLY when the
								// backend projects the CURRENT authority as activatable. Historical
								// status === "PRODUCTION_VALID" is lineage history, never current
								// production authority.
								const canActivate = canActivateAuthority(bp);
								const isDraft = bp.status === "DRAFT";
								const draftReviewable = isDraftReviewable(bp);
								// Historically approved (PRODUCTION_VALID / V2_APPROVED) but no longer
								// activatable against the current Product Truth => stale, needs revalidation.
								const isStale = !canActivate && !isDraft;
								const badge: { tone: BadgeTone; label: string } = isCurrent
									? canActivate
										? { tone: "success", label: "ACTIVE" }
										: { tone: "warn", label: "ACTIVE · STALE — REVALIDATION REQUIRED" }
									: canActivate
										? { tone: "info", label: bp.status }
										: draftReviewable
											? { tone: "info", label: "DRAFT · REVIEW REQUIRED" }
											: isDraft
												? { tone: "warn", label: "DRAFT · APPROVAL BLOCKED" }
												: { tone: "warn", label: "STALE — REVALIDATION REQUIRED" };
								// The single primary action for this card. RULE 2: a reviewable DRAFT
								// routes into the (fully-gated) human approval workflow; a blocked
								// DRAFT is non-actionable with a truthful reason; activation is offered
								// only when current authority allows it. Never a dead button that looks
								// actionable but does nothing.
								let cardLabel: string;
								let cardDisabled: boolean;
								let onCardAction: (() => void) | null = null;
								if (isCurrent && canActivate) {
									cardLabel = "Active in Creator";
									cardDisabled = true;
								} else if (canActivate) {
									cardLabel = "Activate Authority";
									cardDisabled = busy;
									onCardAction = () => setPendingActivation(bp);
								} else if (draftReviewable) {
									cardLabel = "Review & Approve";
									cardDisabled = busy;
									onCardAction = () => reviewBlueprint(bp);
								} else if (isDraft) {
									// A blocked draft is still openable — the panel shows the exact
									// blocker and lets the operator regenerate a stage against current
									// truth. Never a silent dead button.
									cardLabel = "Open blocked draft";
									cardDisabled = busy;
									onCardAction = () => reviewBlueprint(bp);
								} else {
									// Stale historical approval: open the panel to see the reason and
									// regenerate fresh copy (approved text is immutable).
									cardLabel = "Review / revalidate";
									cardDisabled = busy;
									onCardAction = () => reviewBlueprint(bp);
								}

								return (
									<div
										key={`${bp.blueprint_id}:${bp.revision}`}
										data-testid={`library-card-${bp.blueprint_id}`}
										className={`flex flex-col justify-between rounded-xl border p-4 transition-colors ${
											isCurrent && canActivate
												? "border-emerald-500/50 bg-emerald-500/10"
												: isStale
													? "border-amber-500/40 bg-amber-500/5"
													: draftReviewable
														? "border-blue-500/40 bg-blue-500/5"
														: "border-slate-800 bg-slate-950/70"
										}`}
									>
										<div className="space-y-3 text-xs">
											<div className="flex items-center justify-between gap-2">
												<span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] font-semibold uppercase text-slate-300">
													{bp.angle?.definition || "General Angle"}
												</span>
												<Badge tone={badge.tone}>{badge.label}</Badge>
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

											{/* Truthful stale / revalidation surface — the persisted approval
											    is history; current production authority is fail-closed. */}
											{isStale ? (
												<div
													className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-2"
													data-testid={`library-stale-${bp.blueprint_id}`}
												>
													<p className="text-[11px] font-semibold text-amber-100">
														{isCurrent
															? "Active authority is stale — revalidation required."
															: "Historical approval is stale — revalidation required."}
													</p>
													<p className="mt-1 text-[10px] text-amber-200/80">
														{authorityReasonLabel(bp.current_authority_reason)}
													</p>
													<button
														type="button"
														data-testid={`library-revalidate-${bp.blueprint_id}`}
														disabled={busy}
														onClick={() => reviewBlueprint(bp)}
														className="mt-2 rounded border border-amber-400/40 px-2 py-1 text-[10px] font-bold uppercase text-amber-100 hover:bg-amber-500/15 disabled:opacity-40"
													>
														Review / revalidate
													</button>
												</div>
											) : null}

											{/* Truthful blocked-draft surface — cannot be approved as-is; give
											    the authoritative reason and a corrective path (RULE 2). */}
											{isDraft && !draftReviewable ? (
												<div
													className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-2"
													data-testid={`library-blocked-${bp.blueprint_id}`}
												>
													<p className="text-[11px] font-semibold text-amber-100">
														Approval blocked — cannot be approved as-is.
													</p>
													<p className="mt-1 text-[10px] text-amber-200/80">
														{draftBlockedReason(bp)}
													</p>
													<button
														type="button"
														data-testid={`library-fix-draft-${bp.blueprint_id}`}
														disabled={busy}
														onClick={() => reviewBlueprint(bp)}
														className="mt-2 rounded border border-amber-400/40 px-2 py-1 text-[10px] font-bold uppercase text-amber-100 hover:bg-amber-500/15 disabled:opacity-40"
													>
														Open to revalidate / regenerate
													</button>
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
												data-testid={`library-activate-${bp.blueprint_id}`}
												disabled={cardDisabled}
												aria-disabled={cardDisabled}
												onClick={() => {
													if (cardDisabled || !onCardAction) return;
													onCardAction();
												}}
												className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors ${
													isCurrent && canActivate
														? "bg-emerald-500/20 text-emerald-300"
														: cardDisabled
															? "bg-slate-800 text-slate-500 cursor-not-allowed"
															: draftReviewable
																? "bg-amber-500 text-slate-950 hover:bg-amber-400"
																: "bg-blue-600 text-white hover:bg-blue-500"
												}`}
											>
												{cardLabel}
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
				<Section title="Copy Authority" helper="Select a product to begin.">
					<p className="text-sm text-slate-500">Select a Product Truth-approved product first.</p>
				</Section>
			)}

			{/* Task B §4: GLOBAL COPY AUTHORITY CHANGE confirmation. Activation makes the
			    selected V2 blueprint the sole copy authority for every creator lane. It is
			    an advanced, high-consequence action, so require explicit confirmation and
			    never auto-activate. It does NOT rewrite V3 Landbank copy and does NOT mutate
			    any immutable approval. */}
			{pendingActivation ? (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4" data-testid="activation-confirm-overlay">
					<div className="w-full max-w-lg rounded-2xl border border-blue-500/40 bg-slate-900 p-6 shadow-2xl">
						<div className="flex items-center gap-2 text-blue-200">
							<ShieldCheck size={18} />
							<span className="text-[11px] font-bold uppercase tracking-[0.18em]">Global copy authority change</span>
						</div>
						<h2 className="mt-2 text-lg font-bold text-slate-100">Activate this V2 blueprint as the live copy authority?</h2>
						<ul className="mt-3 space-y-1.5 text-xs text-slate-300">
							<li>• It becomes the <span className="font-semibold text-slate-100">active V2 authority</span> for all copy-required creator lanes (video + poster).</li>
							<li>• It does <span className="font-semibold text-slate-100">not</span> rewrite Copywriting Landbank (V3) copy.</li>
							<li>• It does <span className="font-semibold text-slate-100">not</span> mutate any immutable approval — approved text stays unchanged.</li>
							<li>• This is an advanced production operation. Normal campaign copy belongs in Copywriting Landbank.</li>
						</ul>
						<div className="mt-5 flex items-center justify-end gap-3">
							<button
								type="button"
								data-testid="activation-cancel"
								disabled={busy}
								onClick={() => setPendingActivation(null)}
								className="rounded-lg border border-slate-700 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-40"
							>
								Cancel
							</button>
							<button
								type="button"
								data-testid="activation-confirm"
								disabled={busy}
								onClick={() => {
									const target = pendingActivation;
									setPendingActivation(null);
									if (target) void handleActivate(target);
								}}
								className="rounded-lg border border-blue-500/40 bg-blue-600/30 px-4 py-2 text-xs font-bold uppercase text-blue-100 hover:bg-blue-600/50 disabled:opacity-40"
							>
								Confirm global activation
							</button>
						</div>
					</div>
				</div>
			) : null}
		</div>
	);
}
