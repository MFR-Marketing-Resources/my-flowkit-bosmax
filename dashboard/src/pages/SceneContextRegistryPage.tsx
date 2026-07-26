import { useCallback, useEffect, useRef, useState } from "react";
import {
	getRegistryCleanupPlan,
	getRegistryCoverage,
	getRegistryReconciliation,
	getScenePromotionProductReview,
	getScenePromotionActivationEligibility,
	activateScenePromotion,
	activateScenePromotionBulk,
	getSceneContextClusterCoverage,
	getScenePromotionActivationHistory,
	type ClusterCoverageResponse,
	type ActivationHistoryResponse,
	type ActivationEligibilityResponse,
	type RegistryCleanupPlan,
	type RegistryCoverage,
	type RegistryReconciliation,
	type ScenePromotionCandidate,
	type ScenePromotionDecision,
	type ScenePromotionProductReview,
	submitScenePromotionBulkReview,
	submitScenePromotionReview,
} from "../api/creativeIntelligence";
import { useImageGenSettings } from "../api/imageGenSettings";
import { fetchProductCatalog } from "../api/products";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { Product } from "../types";

interface SceneProfile {
	scene_code: string;
	scene_name: string;
	background_prompt: string;
	route_fit: string[];
	usage_tags: string[];
	generated_asset_id?: string | null;
	image_generated: boolean;
}

interface ScenePoolResponse {
	scenes: SceneProfile[];
	count: number;
	generated_count: number;
	source: string;
	bridge_active: boolean;
}

type GenStage = { jobId: string; stage: string };
type SceneRegistryView = "review" | "quarantine" | "admin";

export default function SceneContextRegistryPage() {
	const imgGen = useImageGenSettings();
	const [activeView, setActiveView] = useState<SceneRegistryView>("review");
	const [reviewProducts, setReviewProducts] = useState<Product[]>([]);
	const [selectedReviewProduct, setSelectedReviewProduct] = useState<Product | null>(null);
	const [productReview, setProductReview] = useState<ScenePromotionProductReview | null>(null);
	const [reviewLoading, setReviewLoading] = useState(false);
	const [reviewError, setReviewError] = useState<string | null>(null);
	const [selectedCandidateIds, setSelectedCandidateIds] = useState<Set<string>>(new Set());
	const [reviewerNote, setReviewerNote] = useState("");
	const [reviewSubmitting, setReviewSubmitting] = useState(false);
	const [activationEligibility, setActivationEligibility] = useState<ActivationEligibilityResponse | null>(null);
	const [activationCandidate, setActivationCandidate] = useState<ScenePromotionCandidate | null>(null);
	const [activationNote, setActivationNote] = useState("");
	const [activatedBy, setActivatedBy] = useState("");
	const [activationSubmitting, setActivationSubmitting] = useState(false);
	const [bulkActivationOpen, setBulkActivationOpen] = useState(false);
	const [clusterCoverage, setClusterCoverage] = useState<ClusterCoverageResponse | null>(null);
	const [activationHistory, setActivationHistory] = useState<ActivationHistoryResponse | null>(null);
	const productReviewRequestId = useRef(0);
	const [pool, setPool] = useState<ScenePoolResponse | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [successMsg, setSuccessMsg] = useState<string | null>(null);
	const [generating, setGenerating] = useState<Record<string, GenStage>>({});
	const [coverage, setCoverage] = useState<RegistryCoverage | null>(null);
	const [recon, setRecon] = useState<RegistryReconciliation | null>(null);
	const [cleanup, setCleanup] = useState<RegistryCleanupPlan | null>(null);

	const [aspect, setAspect] = useState<string>("9:16");
	const [count, setCount] = useState<number>(1);
	const [imageModel, setImageModel] = useState<string>("Nano Banana 2");

	// Create Scene — manual add + AI auto-generate (mirror of avatar registry).
	const [manualScene, setManualScene] = useState({
		scene_name: "",
		background_prompt: "",
		usage_tags: "",
	});
	const [isAddingManual, setIsAddingManual] = useState(false);
	const [autoBrief, setAutoBrief] = useState("");
	const [isAutoGenerating, setIsAutoGenerating] = useState(false);
	const [deletingCode, setDeletingCode] = useState<string | null>(null);
	const [sceneSearch, setSceneSearch] = useState("");

	const refresh = useCallback(async () => {
		setLoading(true);
		try {
			const response = await fetch("/api/workspace/scene-context-registry/pool");
			const data = await response.json();
			if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
			setPool(data);
			void getSceneContextClusterCoverage().then(setClusterCoverage).catch(() => {});
			void getScenePromotionActivationHistory().then(setActivationHistory).catch(() => {});
			getRegistryCoverage()
				.then(setCoverage)
				.catch(() => {});
			getRegistryReconciliation()
				.then(setRecon)
				.catch(() => {});
			getRegistryCleanupPlan()
				.then(setCleanup)
				.catch(() => {});
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to load scene pool.");
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		void fetchProductCatalog(250, "GENERATION")
			.then((response) => setReviewProducts(response.items ?? []))
			.catch((err: unknown) =>
				setReviewError(err instanceof Error ? err.message : "Failed to load products."),
			);
	}, []);

	useEffect(() => {
		if (activeView === "admin") void refresh();
	}, [activeView, refresh]);

	const loadProductReview = useCallback(async (product: Product) => {
		const requestId = ++productReviewRequestId.current;
		setReviewLoading(true);
		setReviewError(null);
		try {
			const [review, eligibility] = await Promise.all([getScenePromotionProductReview(product.id), getScenePromotionActivationEligibility(product.id)]);
			if (requestId !== productReviewRequestId.current) return;
			setProductReview(review);
			setActivationEligibility(eligibility);
			setSelectedCandidateIds(new Set());
		} catch (err) {
			if (requestId !== productReviewRequestId.current) return;
			setProductReview(null);
			setActivationEligibility(null);
			setReviewError(err instanceof Error ? err.message : "Failed to load product scene review.");
		} finally {
			if (requestId === productReviewRequestId.current) setReviewLoading(false);
		}
	}, []);

	const selectReviewProduct = (product: Product | null) => {
		const productChanged = selectedReviewProduct?.id !== product?.id;
		productReviewRequestId.current += 1;
		setSelectedReviewProduct(product);
		setProductReview(null);
		setActivationEligibility(null);
		setSelectedCandidateIds(new Set());
		setReviewError(null);
		setActivationCandidate(null);
		setBulkActivationOpen(false);
		setActivationNote("");
		if (productChanged || product === null) setReviewerNote("");
		if (product) void loadProductReview(product);
	};

	const eligibleCandidates = productReview?.candidates.filter((candidate) => {
		const eligibility = activationEligibility?.candidates.find((item) => item.source_template_id === candidate.source_template_id && item.candidate_fingerprint === candidate.candidate_fingerprint);
		return eligibility?.activation_eligible && eligibility.activation_status === "ELIGIBLE_FOR_CONTROLLED_PROMOTION";
	}) ?? [];
	const submitBulkActivation = async () => {
		if (!selectedReviewProduct || !activatedBy.trim() || activationSubmitting) return;
		const selected = eligibleCandidates.filter((candidate) => selectedCandidateIds.has(candidate.source_template_id));
		if (!selected.length) return;
		setActivationSubmitting(true); setReviewError(null);
		try {
			const result = await activateScenePromotionBulk({ reviewed_via_product_id: selectedReviewProduct.id, items: selected.map(({ source_template_id, candidate_fingerprint }) => ({ source_template_id, candidate_fingerprint })), confirmation: "PROMOTE_TO_ACTIVE_REGISTRY", activated_by: activatedBy.trim(), activation_note: activationNote.trim() || null });
			setSuccessMsg(`${result.registry_mutations} registry mutation(s): ${result.items.map((item) => item.scene_code).join(", ")}`);
			setSelectedCandidateIds(new Set()); setBulkActivationOpen(false); setActivationNote(""); await refreshSelectedProductReview(); if (activeView === "admin") await refresh();
		} catch (err) { setReviewError(err instanceof Error ? err.message : "Bulk activation failed."); }
		finally { setActivationSubmitting(false); }
	};

	const submitActivation = async () => {
		if (!selectedReviewProduct || !activationCandidate || !activatedBy.trim() || activationSubmitting) return;
		setActivationSubmitting(true); setReviewError(null);
		try {
			const result = await activateScenePromotion({ reviewed_via_product_id: selectedReviewProduct.id, source_template_id: activationCandidate.source_template_id, candidate_fingerprint: activationCandidate.candidate_fingerprint, confirmation: "PROMOTE_TO_ACTIVE_REGISTRY", activated_by: activatedBy.trim(), activation_note: activationNote.trim() || null });
			setSuccessMsg(`${result.scene_code}: ACTIVE IN REGISTRY · NOT GENERATED${result.idempotent ? " (idempotent)" : ""}`);
			setActivationCandidate(null); setActivationNote(""); await refreshSelectedProductReview(); if (activeView === "admin") await refresh();
		} catch (err) { setReviewError(err instanceof Error ? err.message : "Activation failed."); }
		finally { setActivationSubmitting(false); }
	};

	const refreshSelectedProductReview = async () => {
		if (selectedReviewProduct) await loadProductReview(selectedReviewProduct);
	};

	const submitReview = async (
		candidate: ScenePromotionCandidate,
		decision: Exclude<ScenePromotionDecision, "STALE_REVIEW_REQUIRED">,
	) => {
		if (!selectedReviewProduct || !productReview || productReview.review_required || candidate.stale_review_required) return;
		setReviewSubmitting(true);
		setReviewError(null);
		try {
			await submitScenePromotionReview({
				reviewed_via_product_id: selectedReviewProduct.id,
				source_template_id: candidate.source_template_id,
				candidate_fingerprint: candidate.candidate_fingerprint,
				decision,
				reviewer_note: reviewerNote.trim() || null,
			});
			await refreshSelectedProductReview();
		} catch (err) {
			setReviewError(err instanceof Error ? err.message : "Review submission failed.");
		} finally {
			setReviewSubmitting(false);
		}
	};

	const submitSelectedReviews = async (
		decision: Exclude<ScenePromotionDecision, "STALE_REVIEW_REQUIRED">,
	) => {
		if (!selectedReviewProduct || !productReview || productReview.review_required) return;
		const selected = productReview.candidates.filter((candidate) =>
			selectedCandidateIds.has(candidate.source_template_id),
		);
		if (!selected.length || selected.some((candidate) => candidate.stale_review_required)) return;
		setReviewSubmitting(true);
		setReviewError(null);
		try {
			await submitScenePromotionBulkReview({
				reviewed_via_product_id: selectedReviewProduct.id,
				items: selected.map((candidate) => ({
					source_template_id: candidate.source_template_id,
					candidate_fingerprint: candidate.candidate_fingerprint,
					decision,
					reviewer_note: reviewerNote.trim() || null,
				})),
			});
			await refreshSelectedProductReview();
		} catch (err) {
			setReviewError(err instanceof Error ? err.message : "Bulk review submission failed.");
		} finally {
			setReviewSubmitting(false);
		}
	};

	const toggleCandidateSelection = (candidate: ScenePromotionCandidate) => {
		if (candidate.stale_review_required || productReview?.review_required || !eligibleCandidates.some((item) => item.source_template_id === candidate.source_template_id)) return;
		setSelectedCandidateIds((current) => {
			const next = new Set(current);
			if (next.has(candidate.source_template_id)) next.delete(candidate.source_template_id);
			else if (next.size < 25) next.add(candidate.source_template_id);
			return next;
		});
	};

	const pollGenerationJob = async (sceneCode: string, jobId: string) => {
		for (let attempt = 0; attempt < 150; attempt++) {
			await new Promise((resolve) => setTimeout(resolve, 4000));
			try {
				const response = await fetch(`/api/flow/generate-job/${jobId}`);
				if (!response.ok) continue;
				const job = await response.json();
				setGenerating((prev) =>
					prev[sceneCode]
						? { ...prev, [sceneCode]: { jobId, stage: job.stage || job.status } }
						: prev,
				);
				if (job.status === "DONE" && job.media_id) {
					const registerResponse = await fetch(
						"/api/workspace/scene-context-registry/register-generated",
						{
							method: "POST",
							headers: { "Content-Type": "application/json" },
							body: JSON.stringify({ scene_code: sceneCode, media_id: job.media_id }),
						},
					);
					const registerData = await registerResponse.json();
					if (!registerResponse.ok) {
						throw new Error(registerData?.detail || `HTTP ${registerResponse.status}`);
					}
					setSuccessMsg(
						`${sceneCode}: imej scene siap dan didaftarkan (${registerData.asset_id}) — kini boleh dipilih di IMG Fastlane + I2V.`,
					);
					setGenerating((prev) => {
						const next = { ...prev };
						delete next[sceneCode];
						return next;
					});
					await refresh();
					return;
				}
				if (job.status === "FAILED" || job.status === "REJECTED") {
					throw new Error(`${sceneCode}: generation ${job.status} — ${job.error || "unknown"}`);
				}
			} catch (err) {
				setError(err instanceof Error ? err.message : "Scene generation polling failed.");
				setGenerating((prev) => {
					const next = { ...prev };
					delete next[sceneCode];
					return next;
				});
				return;
			}
		}
		setError(`${sceneCode}: generation timed out — semak Video Jobs / Library.`);
		setGenerating((prev) => {
			const next = { ...prev };
			delete next[sceneCode];
			return next;
		});
	};

	const handleAddManualScene = async () => {
		if (!manualScene.scene_name.trim() || !manualScene.background_prompt.trim()) {
			setError("scene_name dan background_prompt wajib diisi.");
			return;
		}
		setIsAddingManual(true);
		setError(null);
		setSuccessMsg(null);
		try {
			const response = await fetch(
				"/api/workspace/scene-context-registry/add-manual",
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({
						scene_name: manualScene.scene_name.trim(),
						background_prompt: manualScene.background_prompt.trim(),
						usage_tags: manualScene.usage_tags.trim() || undefined,
					}),
				},
			);
			const data = await response.json();
			if (!response.ok) {
				const detail = String(data?.detail || `HTTP ${response.status}`);
				if (response.status === 409 && detail.startsWith("SCENE_REDUNDANT")) {
					throw new Error("Scene serupa sudah wujud");
				}
				throw new Error(detail);
			}
			setSuccessMsg(`Scene ${data.scene_code} ditambah`);
			setManualScene({ scene_name: "", background_prompt: "", usage_tags: "" });
			await refresh();
			// One press = scene + a generated empty-plate background image in the
			// Library (immediately selectable in Fastlane/I2V), not just a text row.
			// Image gen is FREE, so chain straight into the IMG lane; failures degrade
			// gracefully (scene stays, image can be retried from the card).
			await handleGenerateImage(
				{
					scene_code: data.scene_code,
					scene_name: data.scene_name,
				} as SceneProfile,
				true,
			);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Manual scene add failed.");
		} finally {
			setIsAddingManual(false);
		}
	};

	const handleAutoGenerateScene = async () => {
		setIsAutoGenerating(true);
		setError(null);
		setSuccessMsg(null);
		try {
			const body: Record<string, unknown> = {};
			if (autoBrief.trim()) body.brief = autoBrief.trim();
			const response = await fetch(
				"/api/workspace/scene-context-registry/auto-generate",
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify(body),
				},
			);
			const data = await response.json();
			if (!response.ok) {
				const detail = String(data?.detail || `HTTP ${response.status}`);
				if (response.status === 503) {
					throw new Error(
						"AI text provider belum diset. Set di AI Provider Settings (lane text_assist) dahulu.",
					);
				}
				if (response.status === 409) {
					throw new Error(
						"AI hasilkan scene yang serupa sedia ada — cuba brief lain.",
					);
				}
				if (response.status === 502) {
					throw new Error("Penjanaan AI gagal / respons tak sah.");
				}
				throw new Error(detail);
			}
			setSuccessMsg(`Scene ${data.scene_code} dijana`);
			setAutoBrief("");
			await refresh();
			// Auto-chain into the free IMG lane so the new scene arrives with a
			// generated background image in the Library, not just a text row.
			await handleGenerateImage(
				{
					scene_code: data.scene_code,
					scene_name: data.scene_name,
				} as SceneProfile,
				true,
			);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "AI scene auto-generate failed.",
			);
		} finally {
			setIsAutoGenerating(false);
		}
	};

	const handleDeleteScene = async (scene: SceneProfile) => {
		const confirmed = window.confirm(
			`Padam scene "${scene.scene_name}" (${scene.scene_code}) dari registry?\n\n` +
				"Profil dibuang dari pool dan imej background-nya (jika ada) diarkibkan " +
				"(boleh pulih semula dari Creative Library). Tiada kesan pada video/kredit.",
		);
		if (!confirmed) return;
		setDeletingCode(scene.scene_code);
		setError(null);
		setSuccessMsg(null);
		try {
			const response = await fetch(
				`/api/workspace/scene-context-registry/${encodeURIComponent(scene.scene_code)}`,
				{ method: "DELETE" },
			);
			const data = await response.json();
			if (!response.ok) {
				throw new Error(data?.detail || `HTTP ${response.status}`);
			}
			setSuccessMsg(
				`Scene ${scene.scene_code} dipadam (baki ${data.remaining} scene).`,
			);
			await refresh();
		} catch (err) {
			setError(err instanceof Error ? err.message : "Gagal padam scene.");
		} finally {
			setDeletingCode(null);
		}
	};

	const handleGenerateImage = async (
		scene: SceneProfile,
		skipConfirm = false,
	) => {
		if (!skipConfirm) {
			const confirmed = window.confirm(
				`Generate imej background untuk "${scene.scene_name}" (${scene.scene_code})?\n\n` +
					"Ini akan hantar 1 job IMG ke Google Flow (imej PERCUMA — hanya video yang " +
					"dicaj kredit). Imej scene siap akan disimpan kekal sebagai " +
					"SCENE_CONTEXT_REFERENCE dan terus boleh dipilih di IMG Fastlane + I2V.",
			);
			if (!confirmed) return;
		}
		setError(null);
		setSuccessMsg(null);
		try {
			const response = await fetch(
				"/api/workspace/scene-context-registry/generate-image",
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({
						scene_code: scene.scene_code,
						confirm_credit_burn: true,
						aspect,
						count,
						image_model: imageModel,
					}),
				},
			);
			const data = await response.json();
			if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
			setGenerating((prev) => ({
				...prev,
				[scene.scene_code]: { jobId: data.job_id, stage: "SUBMITTED" },
			}));
			void pollGenerationJob(scene.scene_code, data.job_id);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Scene image generation failed.");
		}
	};

	return (
		<div className="mx-auto max-w-6xl space-y-6 p-6">
			<header className="space-y-1">
				<div className="flex items-center gap-2">
					<a href="/operator" className="text-xs text-slate-400 hover:text-slate-200">
						← Operator
					</a>
				</div>
				<div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-emerald-400/80">
					Product-first scene context governance
				</div>
				<h1 className="text-2xl font-bold text-slate-100">Scene Context Registry</h1>
				<p className="text-sm text-slate-400">
					Review product-scoped scene promotion candidates before any future registry work.
					Approval is review-only and never activates, syncs, or generates a scene.
				</p>
				{activeView === "admin" && pool && (
					<p className="text-xs text-slate-500">
						{pool.count} scene · {pool.generated_count} sudah ada imej ·
						{pool.bridge_active ? " bridge aktif" : " seed repo"}
					</p>
				)}
			</header>

			<div role="tablist" aria-label="Scene context views" className="flex flex-wrap gap-2 border-b border-slate-800 pb-3">
				{([
					["review", "PRODUCT SCENE REVIEW"],
					["quarantine", "PROMOTION QUARANTINE"],
					["admin", "ACTIVE REGISTRY / ADMIN"],
				] as const).map(([view, label]) => (
					<button
						key={view}
						type="button"
						role="tab"
						aria-selected={activeView === view}
						onClick={() => setActiveView(view)}
						className={`rounded-lg border px-3 py-2 text-xs font-semibold ${activeView === view ? "border-emerald-400/50 bg-emerald-500/10 text-emerald-100" : "border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-100"}`}
					>
						{label}
					</button>
				))}
			</div>

			{(activeView === "review" || activeView === "quarantine") && (
				<section className="space-y-4" data-testid="scene-promotion-owner-review">
					<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
						<div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
							Registered generation-capable product
						</div>
						<SearchableProductSelect
							products={reviewProducts}
							selectedProduct={selectedReviewProduct}
							onSelect={selectReviewProduct}
						/>
					</div>

					{reviewError && (
						<div role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-200">
							{reviewError}
						</div>
					)}
					{reviewLoading && <div className="text-sm text-slate-400">Loading product scene review…</div>}
					{!selectedReviewProduct && !reviewLoading && (
						<div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 text-sm text-slate-400">
							Select a registered product to load its read-only suitability and promotion review.
						</div>
					)}
					{productReview && (
						<>
							<div className="grid gap-3 rounded-2xl border border-slate-800 bg-slate-900/50 p-4 sm:grid-cols-2 lg:grid-cols-4">
								<div><div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Product</div><div className="text-sm font-semibold text-slate-100">{productReview.product_name || selectedReviewProduct?.product_display_name}</div></div>
								<div><div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Category</div><div className="text-sm text-slate-200">{productReview.category || "Uncategorised"}</div></div>
								<div><div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Canonical cluster</div><div className="text-sm text-slate-200">{productReview.cluster || "REVIEW REQUIRED"}</div><div className="text-[10px] text-slate-500">{productReview.cluster_source}</div></div>
								<div><div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Review inventory</div><div className="text-sm text-slate-200">{productReview.candidate_count} candidates · {productReview.quarantine_count} quarantined</div></div>
							</div>
							<div className="flex flex-wrap gap-2 text-[11px] text-slate-300">
								{Object.entries(productReview.decision_counts).map(([decision, count]) => <span key={decision} className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1">{decision}: {count}</span>)}
							</div>
							{productReview.review_required ? (
								<div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-100">
									<strong>PRODUCT CATEGORY REVIEW REQUIRED.</strong> {productReview.message || "Correct the product category before reviewing promotion candidates."} Review actions are fail-closed.
								</div>
							) : activeView === "quarantine" ? (
								<div data-testid="promotion-quarantine" className="space-y-3">
									<h2 className="text-sm font-semibold text-slate-100">Promotion Quarantine</h2>
									{productReview.quarantine.length === 0 ? <p className="text-sm text-slate-400">No quarantined templates for this product cluster.</p> : productReview.quarantine.map((item) => (
										<div key={item.source_template_id} className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-slate-300">
											<div className="font-mono text-xs text-amber-200">{item.source_template_id}</div>
											<div className="mt-1"><strong>Quarantine reason:</strong> {item.reason}</div>
											<div className="mt-1 text-xs text-slate-400">{item.source_category || "Unknown source category"} · {item.setting || "No setting"}</div>
										</div>
									))}
								</div>
							) : (
								<div className="space-y-4" data-testid="product-scene-review-candidates">
									<div className="flex flex-col gap-3 rounded-xl border border-slate-800 bg-slate-900/40 p-3 sm:flex-row sm:items-end">
										<label className="min-w-0 flex-1 text-xs text-slate-300">Reviewer note (optional, max 2000 characters)<textarea value={reviewerNote} maxLength={2000} onChange={(event) => setReviewerNote(event.target.value)} rows={2} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-xs text-slate-100" /></label>
										<div className="flex gap-2"><button type="button" disabled={!selectedCandidateIds.size || reviewSubmitting} onClick={() => void submitSelectedReviews("APPROVED_FOR_FUTURE_PROMOTION")} className="rounded-lg border border-emerald-500/40 px-3 py-2 text-xs text-emerald-100 disabled:opacity-40">Approve selected</button><button type="button" disabled={!selectedCandidateIds.size || reviewSubmitting} onClick={() => void submitSelectedReviews("REJECTED")} className="rounded-lg border border-red-500/40 px-3 py-2 text-xs text-red-100 disabled:opacity-40">Reject selected</button><button type="button" disabled={!selectedCandidateIds.size || activationSubmitting} onClick={() => setBulkActivationOpen(true)} className="rounded-lg border border-cyan-500/40 px-3 py-2 text-xs text-cyan-100 disabled:opacity-40">Promote Selected ({selectedCandidateIds.size})</button></div>
									</div>
									{productReview.candidates.map((candidate) => {
										const actionsDisabled = candidate.stale_review_required || reviewSubmitting;
										const activation = activationEligibility?.candidates.find((item) => item.source_template_id === candidate.source_template_id && item.candidate_fingerprint === candidate.candidate_fingerprint);
										return <article key={candidate.source_template_id} className="space-y-3 rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
											<div className="flex items-start justify-between gap-3"><label className="flex items-start gap-2 text-sm font-semibold text-slate-100"><input aria-label={`Select ${candidate.source_template_id}`} type="checkbox" checked={selectedCandidateIds.has(candidate.source_template_id)} disabled={actionsDisabled} onChange={() => toggleCandidateSelection(candidate)} /> <span>{candidate.proposed_scene_name}<span className="mt-1 block font-mono text-[10px] font-normal text-slate-500">{candidate.source_template_id} → {candidate.proposed_scene_code}</span></span></label><span className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-300">{candidate.decision}</span></div>
											<div className="grid gap-2 text-xs text-slate-300 sm:grid-cols-2"><div><strong>Source category:</strong> {candidate.source_category || "Unknown"}</div><div><strong>Setting:</strong> {candidate.setting || "—"}</div><div><strong>Background:</strong> {candidate.background_prompt}</div><div><strong>Safety:</strong> {candidate.safety_block}</div><div><strong>Usage tags:</strong> {candidate.usage_tags}</div><div><strong>Reviewed:</strong> {candidate.reviewed_at || "Not yet reviewed"}</div></div>
											<div className="text-xs text-slate-400"><strong>PromptV1:</strong><p className="mt-1 whitespace-pre-wrap">{candidate.prompt_v1}</p><p className="mt-2"><strong>Reviewer note:</strong> {candidate.reviewer_note || "—"}</p></div>
											{candidate.stale_review_required ? <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-100"><span>Candidate content changed after the prior decision. Refresh before taking a new action; the older fingerprint is not reused.</span><button type="button" onClick={() => void refreshSelectedProductReview()} className="rounded border border-amber-400/50 px-2 py-1">Refresh candidate</button></div> : <div className="flex flex-wrap gap-2"><button type="button" disabled={actionsDisabled} onClick={() => void submitReview(candidate, "APPROVED_FOR_FUTURE_PROMOTION")} className="rounded-lg border border-emerald-500/40 px-3 py-1.5 text-xs text-emerald-100 disabled:opacity-40">Approve for future promotion</button><button type="button" disabled={actionsDisabled} onClick={() => void submitReview(candidate, "REJECTED")} className="rounded-lg border border-red-500/40 px-3 py-1.5 text-xs text-red-100 disabled:opacity-40">Reject</button><button type="button" disabled={actionsDisabled} onClick={() => void submitReview(candidate, "PENDING")} className="rounded-lg border border-slate-600 px-3 py-1.5 text-xs text-slate-200 disabled:opacity-40">Reset to pending</button></div>}
											{candidate.decision === "APPROVED_FOR_FUTURE_PROMOTION" && <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-xs font-semibold text-emerald-100">APPROVED FOR FUTURE PROMOTION · NOT ACTIVE IN REGISTRY</div>}
											<div className="text-[10px] text-slate-500">Activation status: {activation?.activation_status || "NOT_APPROVED"}{activation?.existing_scene_code ? ` · SceneCode: ${activation.existing_scene_code}` : ""}{activation?.activation_blocker ? ` · ${activation.activation_blocker}` : ""}</div>
											{activation?.activation_eligible && activation.activation_status === "ELIGIBLE_FOR_CONTROLLED_PROMOTION" && <button type="button" onClick={() => setActivationCandidate(candidate)} className="rounded-lg border border-cyan-500/40 px-3 py-1.5 text-xs text-cyan-100">Promote to Active Registry</button>}
										</article>;
									})}
								</div>
							)}
						</>
					)}
				</section>
			)}

			{activeView === "admin" && <>
				<div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-emerald-400/80">
					Live Scene / Context Authority Pool
				</div>

			{coverage && (
				<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
					<div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Scene Pool
							</div>
							<div className="mt-1 text-lg font-bold text-slate-100">
								{coverage.scene.pool_total}
							</div>
							<div className="text-[11px] text-slate-400">
								{coverage.scene.bridge_active ? "synced bridge CSV" : "repo seed"} ·{" "}
								{coverage.scene.prompt_total} scene prompts
							</div>
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Scene-Prompt Coverage
							</div>
							<div className="mt-1 text-lg font-bold text-slate-100">
								{coverage.scene.clusters_covered.length}/{coverage.cluster_total}{" "}
								clusters
							</div>
							<div className="text-[11px] text-slate-400">
								{coverage.product_total} products
							</div>
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Coverage Gaps
							</div>
							<div
								className={`mt-1 text-sm font-semibold ${coverage.scene.clusters_missing.length ? "text-amber-400" : "text-emerald-400"}`}
							>
								{coverage.scene.clusters_missing.length
									? `Missing: ${coverage.scene.clusters_missing.join(", ")}`
									: "Full 12/12 clusters"}
							</div>
						</div>
					</div>
					<div className="mt-3 text-[11px] text-slate-500">
						Used by scene reference lanes (IMG Fastlane · I2V scene/style) and
						Creative Intelligence context. Read-only — editing here changes the live
						pool those lanes resolve against.
					</div>
				</div>
			)}

			{recon && (
				<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
					<div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300">
						Registry Reconciliation
					</div>
					<div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Pool
							</div>
							<div className="mt-1 text-lg font-bold text-slate-100">
								{recon.scene.pool_total}
							</div>
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Scene Prompts
							</div>
							<div className="mt-1 text-lg font-bold text-emerald-400">
								{recon.scene.prompt_template_total}
							</div>
							<div className="text-[10px] text-slate-500">templates</div>
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Referenced
							</div>
							<div className="mt-1 text-lg font-bold text-sky-400">
								{recon.scene.referenced_by_selection}
							</div>
							<div className="text-[10px] text-slate-500">saved selections</div>
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Review candidates
							</div>
							<div className="mt-1 text-lg font-bold text-amber-400">
								{recon.scene.review_candidate_count}
							</div>
							<div className="text-[10px] text-slate-500">pool plates</div>
						</div>
					</div>
					<div className="mt-2 text-[11px] text-slate-500">
						Pool ↔ prompt:{" "}
						{recon.scene.pool_to_prompt_mapping === "NOT_DIRECTLY_MAPPED"
							? "not directly mapped (separate id spaces)"
							: recon.scene.pool_to_prompt_mapping}
						. Scene plates also feed the IMG/I2V reference lane.
					</div>
					<div className="mt-2 text-[11px] text-slate-500">{recon.disclaimer}</div>
				</div>
			)}
			{cleanup && (
				<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
					<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300">
						Archive / Delete Planning
					</div>
					<div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-300/90">
						Read-only dry-run · No records are changed · Owner approval required before
						any real archive/delete.
					</div>
					<div className="flex flex-wrap gap-2">
						{(
							[
								"KEEP_ACTIVE",
								"BLOCKED_REFERENCED",
								"REVIEW_CANDIDATE",
								"BLOCKED_UNKNOWN_MAPPING",
								"FUTURE_ARCHIVE_ELIGIBLE",
							] as const
						).map((k) => (
							<span
								key={k}
								className="rounded-lg border border-slate-800 bg-slate-950/60 px-2.5 py-1 text-[10px] text-slate-300"
							>
								{k}:{" "}
								<span className="font-bold text-slate-100">
									{cleanup.scene.classification_counts[k] ?? 0}
								</span>
							</span>
						))}
					</div>
					{cleanup.scene.candidates_sample.length > 0 && (
						<div className="mt-3 space-y-1">
							{cleanup.scene.candidates_sample.slice(0, 4).map((c) => (
								<div key={c.id} className="text-[11px] text-slate-500">
									<span className="font-mono text-slate-400">{c.id}</span> —{" "}
									{c.classification}: {c.reason}
								</div>
							))}
						</div>
					)}
					<div className="mt-2 text-[11px] text-slate-500">
						Future-archive eligible: {cleanup.future_archive_eligible_total} — owner
						approval still required.
					</div>
					<div className="mt-2 rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-[11px] text-emerald-300/90">
						<span className="font-semibold">
							Registry Modernization (Phases A–E) complete.
						</span>{" "}
						{cleanup.future_archive_eligible_total === 0
							? "No records are currently eligible for archive or delete."
							: `${cleanup.future_archive_eligible_total} record(s) flagged for future review — none auto-eligible.`}{" "}
						Any future archive/delete requires owner approval and a
						zero-reference dry-run proof.
					</div>
				</div>
			)}
			{/* Image-gen settings (shared SSOT) */}
			<div className="flex flex-wrap items-end gap-4 rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
				<label className="text-[11px] text-slate-300">
					<span className="mb-1 block font-semibold uppercase tracking-[0.14em] text-slate-500">
						Aspect
					</span>
					<select
						value={aspect}
						onChange={(e) => setAspect(e.target.value)}
						className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
					>
						{imgGen.aspect_options.map((a) => (
							<option key={a} value={a}>
								{a}
							</option>
						))}
					</select>
				</label>
				<label className="text-[11px] text-slate-300">
					<span className="mb-1 block font-semibold uppercase tracking-[0.14em] text-slate-500">
						Count
					</span>
					<input
						type="number"
						min="1"
						max="4"
						value={count}
						onChange={(e) => setCount(Math.max(1, Math.min(4, parseInt(e.target.value) || 1)))}
						className="w-16 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
					/>
				</label>
				<label className="text-[11px] text-slate-300">
					<span className="mb-1 block font-semibold uppercase tracking-[0.14em] text-slate-500">
						Image Model
					</span>
					<select
						value={imageModel}
						onChange={(e) => setImageModel(e.target.value)}
						className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
					>
						{imgGen.models.map((m) => (
							<option key={m.label} value={m.label}>
								{m.label}
								{m.pending ? " (id pending)" : ""}
							</option>
						))}
					</select>
				</label>
			</div>

			{error && (
				<div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-200">
					{error}
				</div>
			)}
			{successMsg && (
				<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200">
					{successMsg}
				</div>
			)}

			{/* Create Scene — manual add + AI auto-generate */}
			<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
				<div className="mb-3">
					<h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
						Create Scene
					</h2>
					<p className="mt-1 text-xs text-slate-400">
						Tambah scene tunggal secara manual, atau biar AI jana satu scene
						baharu (bukan duplikat) terus ke pool.
					</p>
				</div>
				<div className="grid gap-4 md:grid-cols-2">
					{/* A) Manual add */}
					<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
						<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
							Manual add
						</div>
						<label className="block text-[10px] text-slate-400">
							<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
								Scene name
							</span>
							<input
								value={manualScene.scene_name}
								onChange={(e) =>
									setManualScene((s) => ({ ...s, scene_name: e.target.value }))
								}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
							/>
						</label>
						<label className="mt-3 block text-[10px] text-slate-400">
							<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
								Background prompt
							</span>
							<textarea
								value={manualScene.background_prompt}
								onChange={(e) =>
									setManualScene((s) => ({
										...s,
										background_prompt: e.target.value,
									}))
								}
								rows={3}
								placeholder="Background: ..."
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
							/>
						</label>
						<label className="mt-3 block text-[10px] text-slate-400">
							<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
								Usage tags (optional)
							</span>
							<input
								value={manualScene.usage_tags}
								onChange={(e) =>
									setManualScene((s) => ({ ...s, usage_tags: e.target.value }))
								}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
							/>
						</label>
						<button
							type="button"
							disabled={isAddingManual}
							onClick={() => void handleAddManualScene()}
							className="mt-3 w-full rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-sm font-semibold text-blue-100 hover:bg-blue-500/20 disabled:opacity-50"
						>
							{isAddingManual ? "Menambah..." : "+ Tambah Scene"}
						</button>
					</div>

					{/* B) AI auto-generate */}
					<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
						<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
							AI auto-generate
						</div>
						<label className="block text-[10px] text-slate-400">
							<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
								Brief
							</span>
							<textarea
								value={autoBrief}
								onChange={(e) => setAutoBrief(e.target.value)}
								rows={3}
								placeholder="Ringkasan: cth 'dapur moden cerah untuk demo produk penjagaan kulit'"
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
							/>
						</label>
						<button
							type="button"
							disabled={isAutoGenerating}
							onClick={() => void handleAutoGenerateScene()}
							className="mt-3 w-full rounded-xl border border-purple-500/30 bg-purple-500/10 px-4 py-2 text-sm font-semibold text-purple-100 hover:bg-purple-500/20 disabled:opacity-50"
						>
							{isAutoGenerating
								? "Menjana scene..."
								: "🤖 Auto-generate Scene"}
						</button>
						<div className="mt-2 text-[10px] text-slate-500">
							Guna lane text_assist (AI Provider Settings). Boleh ambil masa
							beberapa saat.
						</div>
					</div>
				</div>
			</section>

			<div className="mb-2">
				<input
					value={sceneSearch}
					onChange={(e) => setSceneSearch(e.target.value)}
					placeholder="Cari scene (nama, kod, tag)…"
					className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 md:w-96"
				/>
			</div>

			{loading ? (
				<div className="text-sm text-slate-400">Loading scene contexts…</div>
			) : (
				<div className="grid gap-4 md:grid-cols-2">
					{(pool?.scenes ?? [])
						.filter((scene) => {
							const q = sceneSearch.trim().toLowerCase();
							if (!q) return true;
							return [
								scene.scene_name,
								scene.scene_code,
								scene.usage_tags.join(" "),
								scene.route_fit.join(" "),
							]
								.join(" ")
								.toLowerCase()
								.includes(q);
						})
						.map((scene) => {
						const gen = generating[scene.scene_code];
						return (
							<div
								key={scene.scene_code}
								className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 space-y-3"
							>
								<div className="flex items-start justify-between gap-2">
									<div>
										<h3 className="text-sm font-semibold text-slate-100">
											{scene.scene_name}
										</h3>
										<div className="font-mono text-[10px] text-slate-500">
											{scene.scene_code}
										</div>
									</div>
									{scene.image_generated ? (
										<span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-200">
											IMAGE READY
										</span>
									) : (
										<span className="rounded-full border border-slate-600 bg-slate-950 px-2 py-0.5 text-[10px] text-slate-400">
											TEXT ONLY
										</span>
									)}
								</div>
								<p className="text-[11px] leading-relaxed text-slate-400">
									{scene.background_prompt}
								</p>
								<div className="flex flex-wrap gap-1">
									{scene.usage_tags.map((t) => (
										<span
											key={t}
											className="rounded-md border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[9px] text-slate-400"
										>
											{t}
										</span>
									))}
								</div>
								<div className="flex items-center justify-between gap-2 pt-1">
									<span className="text-[9px] text-slate-600">
										{scene.route_fit.join(" · ")}
									</span>
									<div className="flex items-center gap-2">
									{gen ? (
										<span className="text-[11px] text-blue-300">
											Generating… {gen.stage}
										</span>
									) : scene.image_generated ? (
										<button
											type="button"
											onClick={() => handleGenerateImage(scene)}
											className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-[11px] font-semibold text-slate-300 hover:border-blue-500 hover:text-white"
										>
											Regenerate
										</button>
									) : (
										<button
											type="button"
											onClick={() => handleGenerateImage(scene)}
											className="rounded-lg border border-blue-500/50 bg-blue-500/10 px-3 py-1 text-[11px] font-semibold text-blue-200 hover:bg-blue-500/20"
										>
											Generate scene image
										</button>
									)}
										<button
											type="button"
											onClick={() => void handleDeleteScene(scene)}
											disabled={deletingCode === scene.scene_code}
											className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-1 text-[11px] font-semibold text-red-200 hover:bg-red-500/20 disabled:opacity-40 disabled:cursor-not-allowed"
										>
											{deletingCode === scene.scene_code ? "..." : "Delete"}
										</button>
									</div>
								</div>
							</div>
						);
					})}
				</div>
			)}
			</>}
			{activeView === "admin" && clusterCoverage && <section aria-label="Cluster coverage" className="mb-4 rounded-xl border border-slate-800 p-4"><div className="text-sm font-semibold">Cluster coverage · {clusterCoverage.active_scene_total} active · {clusterCoverage.classified_scene_total} classified · {clusterCoverage.review_required_scene_total} review required · {clusterCoverage.shared_scene_total} shared</div><div className="mt-2 grid gap-2 sm:grid-cols-2">{clusterCoverage.per_cluster.map((row) => <div key={row.cluster} className="text-xs">{row.cluster}: {row.eligible_active_scene_count} active · {row.gap_to_target ? `GAP ${row.gap_to_target}` : "TARGET MET"}</div>)}</div>{activationHistory && <div className="mt-3 text-xs"><strong>Activation History</strong>{activationHistory.events.map((event) => <div key={event.activation_id}>{event.activated_at} · {event.scene_code} · {event.activated_by} · {event.activation_note || "—"}</div>)}</div>}</section>}
			{bulkActivationOpen && <div role="dialog" aria-modal="true" aria-label="Confirm selected promotion" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/80 p-4"><div className="w-full max-w-lg rounded-2xl border border-cyan-500/30 bg-slate-900 p-5 text-sm text-slate-100"><h2 className="text-lg font-semibold">Promote Selected ({selectedCandidateIds.size})</h2><p className="mt-2 text-xs text-amber-100">This atomic action adds registry rows. No media is generated.</p><label className="mt-3 block text-xs">Activated by<input aria-label="Activated by" value={activatedBy} onChange={(event) => setActivatedBy(event.target.value)} className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2" /></label><div className="mt-4 flex justify-end gap-2"><button type="button" onClick={() => setBulkActivationOpen(false)}>Cancel</button><button type="button" disabled={!activatedBy.trim() || activationSubmitting} onClick={() => void submitBulkActivation()}>Confirm selected promotion</button></div></div></div>}
			{activationCandidate && <div role="dialog" aria-modal="true" aria-label="Confirm controlled promotion" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/80 p-4">
				<div className="w-full max-w-lg rounded-2xl border border-cyan-500/30 bg-slate-900 p-5 text-sm text-slate-100 shadow-2xl">
					<h2 className="text-lg font-semibold">Promote to Active Registry</h2><p className="mt-2 text-slate-300">{selectedReviewProduct?.product_display_name} · {activationCandidate.source_template_id} · {productReview?.cluster || "REVIEW REQUIRED"}</p>
					<p className="mt-2 text-xs text-amber-100">This adds an active registry row. It does not generate an image or video.</p>
					<label className="mt-3 block text-xs">Activated by<input aria-label="Activated by" value={activatedBy} onChange={(event) => setActivatedBy(event.target.value)} className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2" /></label>
					<label className="mt-3 block text-xs">Activation note (optional)<textarea aria-label="Activation note" value={activationNote} onChange={(event) => setActivationNote(event.target.value)} className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2" /></label>
					<div className="mt-4 flex justify-end gap-2"><button type="button" onClick={() => setActivationCandidate(null)} className="rounded border border-slate-600 px-3 py-2">Cancel</button><button type="button" disabled={!activatedBy.trim() || activationSubmitting} onClick={() => void submitActivation()} className="rounded border border-cyan-500/50 bg-cyan-500/10 px-3 py-2 disabled:opacity-40">{activationSubmitting ? "Promoting…" : "Confirm promotion"}</button></div>
				</div>
			</div>}
		</div>
	);
}
