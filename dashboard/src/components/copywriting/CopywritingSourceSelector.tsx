import { useEffect, useMemo, useState } from "react";
import { Bot, Check, ChevronLeft, ChevronRight, FileText, RefreshCw, Sparkles, ExternalLink, ShieldAlert } from "lucide-react";
import {
	activateFormulaBlueprint,
	fetchCopyRegisterFormulas,
	fetchCopyRegisterProviderStatus,
	fetchCopyRegisterTruth,
	generateCopyRegisterAngles,
	generateFormulaCopyBlueprint,
	listCopyRegisterBlueprints,
	type CopyAngleOptionV2,
	type CopyBlueprintV2Record,
	type CopyFormulaV2,
	type CopyTruthProofV2,
	type TextAssistLaneStatusV2,
} from "../../api/copyRegisterV2";
import { TechnicalDetails } from "../ui/TechnicalDetails";

export interface CopywritingSourceSelectorProps {
	productId?: string | null;
	productName?: string | null;
	lane?: string;
	onCopySelected?: (blueprint: CopyBlueprintV2Record) => void;
	className?: string;
}

type CopySource = "REGISTER" | "AI_ASSISTANT";

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

export function CopywritingSourceSelector({
	productId,
	productName: _productName,
	lane: _lane,
	onCopySelected,
	className = "",
}: CopywritingSourceSelectorProps) {
	const [activeSource, setActiveSource] = useState<CopySource>("REGISTER");
	const [isSelecting, setIsSelecting] = useState(false);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [successMsg, setSuccessMsg] = useState<string | null>(null);

	// Blueprints & selection
	const [blueprints, setBlueprints] = useState<CopyBlueprintV2Record[]>([]);
	const [activeBlueprintId, setActiveBlueprintId] = useState<string | null>(null);
	const [selectedAngle, setSelectedAngle] = useState<string>("ALL");

	// Pagination
	const [page, setPage] = useState(1);
	const PAGE_SIZE = 4;

	// AI Assist states
	const [formulas, setFormulas] = useState<CopyFormulaV2[]>([]);
	const [selectedFormulaId, setSelectedFormulaId] = useState("");
	const [_truth, setTruth] = useState<CopyTruthProofV2 | null>(null);
	const [aiAngles, setAiAngles] = useState<CopyAngleOptionV2[]>([]);
	const [selectedAiAngleId, setSelectedAiAngleId] = useState("");
	const [selectedFactIds, setSelectedFactIds] = useState<string[]>([]);
	const [_textAssistStatus, setTextAssistStatus] = useState<TextAssistLaneStatusV2 | null>(null);
	const [generatingAi, setGeneratingAi] = useState(false);
	const [generatedDraftBlueprint, setGeneratedDraftBlueprint] = useState<CopyBlueprintV2Record | null>(null);

	const loadBlueprints = async (pId: string) => {
		setLoading(true);
		setError(null);
		try {
			const res = await listCopyRegisterBlueprints(pId);
			const items = res.items || [];
			setBlueprints(items);
			const activeId = res.activation?.active_blueprint_id || null;
			if (activeId) {
				setActiveBlueprintId(activeId);
				setIsSelecting(false);
			} else {
				setActiveBlueprintId((curr) => {
					if (!curr && items.length > 0) {
						// Only auto-focus if already active, do not force draft
						return null;
					}
					return curr;
				});
			}
		} catch (e) {
			setError(e instanceof Error ? e.message : "Failed to load copy blueprints.");
		} finally {
			setLoading(false);
		}
	};

	useEffect(() => {
		if (!productId) {
			setBlueprints([]);
			setActiveBlueprintId(null);
			setIsSelecting(false);
			setGeneratedDraftBlueprint(null);
			return;
		}
		void loadBlueprints(productId);
		void fetchCopyRegisterFormulas().then((r) => setFormulas(r.formulas || [])).catch(() => {});
		void fetchCopyRegisterProviderStatus().then(setTextAssistStatus).catch(() => {});
		void fetchCopyRegisterTruth(productId).then(setTruth).catch(() => {});
	}, [productId]);

	const activeBlueprint = useMemo(() => {
		if (!activeBlueprintId) return null;
		return blueprints.find((b) => b.blueprint_id === activeBlueprintId) || null;
	}, [blueprints, activeBlueprintId]);

	// Extract unique angles from blueprints
	const availableAngles = useMemo(() => {
		const map = new Map<string, string>();
		for (const b of blueprints) {
			if (b.angle?.angle_id && b.angle?.definition) {
				map.set(b.angle.angle_id, b.angle.definition);
			}
		}
		return Array.from(map.entries()).map(([id, def]) => ({ id, definition: def }));
	}, [blueprints]);

	// Filter blueprints by selected angle
	const filteredBlueprints = useMemo(() => {
		if (selectedAngle === "ALL") return blueprints;
		return blueprints.filter((b) => b.angle?.angle_id === selectedAngle || b.angle?.definition === selectedAngle);
	}, [blueprints, selectedAngle]);

	const totalPages = Math.max(1, Math.ceil(filteredBlueprints.length / PAGE_SIZE));
	const paginatedBlueprints = useMemo(() => {
		const start = (page - 1) * PAGE_SIZE;
		return filteredBlueprints.slice(start, start + PAGE_SIZE);
	}, [filteredBlueprints, page]);

	const handleUseCopy = async (bp: CopyBlueprintV2Record) => {
		// Strict Governance Rule: Activation must be based on CURRENT authority, not merely historical status
		const canActivate = bp.current_authority_activation_allowed === true;
		if (!canActivate) {
			if (bp.status === "PRODUCTION_VALID" || bp.status === "V2_APPROVED") {
				setError("This copy set is historically approved but its Product Truth authority is stale. Please revalidate in Copy Register.");
			} else {
				setError("This copy set is in DRAFT status. Please review and approve it in the Copy Register before using.");
			}
			return;
		}

		setLoading(true);
		setError(null);
		setSuccessMsg(null);
		try {
			await activateFormulaBlueprint(bp.blueprint_id);
			setActiveBlueprintId(bp.blueprint_id);
			setSuccessMsg("Copy set activated for this product across creator lanes.");
			setIsSelecting(false);
			onCopySelected?.(bp);
			if (productId) {
				void loadBlueprints(productId);
			}
		} catch (e) {
			setError(e instanceof Error ? e.message : "Failed to activate selected copy.");
		} finally {
			setLoading(false);
		}
	};

	// AI Copy Generation Handlers
	const handleGenerateAiAngles = async () => {
		if (!productId || !selectedFormulaId) return;
		setGeneratingAi(true);
		setError(null);
		setGeneratedDraftBlueprint(null);
		try {
			const res = await generateCopyRegisterAngles({
				product_id: productId,
				formula_id: selectedFormulaId,
				objective: "conversion",
			});
			setAiAngles(res.angles || []);
			if (res.angles?.length) {
				setSelectedAiAngleId(res.angles[0].angle_id);
				setSelectedFactIds(res.angles[0].evidence_fact_ids || []);
			}
		} catch (e) {
			setError(e instanceof Error ? e.message : "Failed to generate AI angles.");
		} finally {
			setGeneratingAi(false);
		}
	};

	const handleGenerateAiCopy = async () => {
		if (!productId || !selectedFormulaId || !selectedAiAngleId) return;
		const angleObj = aiAngles.find((a) => a.angle_id === selectedAiAngleId);
		if (!angleObj) return;

		setGeneratingAi(true);
		setError(null);
		setGeneratedDraftBlueprint(null);
		try {
			const genRes = await generateFormulaCopyBlueprint({
				product_id: productId,
				formula_id: selectedFormulaId,
				objective_id: "conversion",
				objective_definition: "Help a qualified buyer choose a grounded next step.",
				angle_id: angleObj.angle_id,
				angle_definition: angleObj.definition,
				evidence_fact_ids: selectedFactIds.length ? selectedFactIds : angleObj.evidence_fact_ids || [],
			});

			// Strict Governance Rule: Generated copy remains in DRAFT state. DO NOT auto-approve. DO NOT auto-activate.
			setGeneratedDraftBlueprint(genRes.blueprint);
			setSuccessMsg("Draft copy generated. Review and approve it in the Copy Register before activating for production.");

			// Refresh blueprints list so the new draft appears in the registry
			if (productId) {
				void loadBlueprints(productId);
			}
		} catch (e) {
			setError(e instanceof Error ? e.message : "Failed to generate AI copy.");
		} finally {
			setGeneratingAi(false);
		}
	};

	if (!productId) {
		return (
			<div className={`rounded-xl border border-slate-800 bg-slate-900/30 p-4 text-xs text-slate-500 ${className}`}>
				Select a product in Step 1 to choose or generate copywriting.
			</div>
		);
	}

	// Active concise summary view (when not in selecting/changing mode)
	if (!isSelecting && activeBlueprint) {
		const hook = extractHook(activeBlueprint);
		const body = extractBody(activeBlueprint);
		const cta = extractCta(activeBlueprint);
		const angleText = activeBlueprint.angle?.definition || "General Angle";
		// Truthful CURRENT-ACTIVE state: an activation record is historical. If the
		// product's current authority no longer permits this blueprint (Product Truth
		// advanced after activation) it must NOT be presented as a clean, production-
		// ready selection. The activation binding still points here, but it is stale.
		const activeIsCurrent = activeBlueprint.current_authority_activation_allowed === true;

		return (
			<div className={`space-y-3 ${className}`} data-testid="copywriting-selected-summary">
				<div className={`rounded-xl border p-4 ${activeIsCurrent ? "border-emerald-500/30 bg-emerald-500/5" : "border-amber-500/40 bg-amber-500/5"}`}>
					<div className={`flex flex-wrap items-center justify-between gap-2 border-b pb-3 ${activeIsCurrent ? "border-emerald-500/10" : "border-amber-500/20"}`}>
						<div className="flex items-center gap-2">
							<span className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${activeIsCurrent ? "bg-emerald-500/20 text-emerald-300" : "bg-amber-500/20 text-amber-300"}`}>
								{activeIsCurrent ? "✓" : "!"}
							</span>
							<span className={`text-xs font-bold uppercase tracking-wider ${activeIsCurrent ? "text-emerald-200" : "text-amber-200"}`}>
								{activeIsCurrent ? "Copywriting Selected" : "Active Copy — Revalidation Required"}
							</span>
							<span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] font-medium text-slate-300">
								{activeSource === "REGISTER" ? "Copy Register" : "AI Copy Assistant"}
							</span>
						</div>
						<button
							type="button"
							data-testid="change-copy-button"
							onClick={() => {
								setIsSelecting(true);
								setPage(1);
							}}
							className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1 text-xs font-medium text-slate-200 hover:border-slate-500 hover:text-white"
						>
							Change Copy
						</button>
					</div>

					{!activeIsCurrent ? (
						<div
							className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-[11px] text-amber-100"
							data-testid="copy-active-stale-warning"
						>
							<p className="font-semibold">This active copy is stale — its Product Truth authority is no longer current.</p>
							<p className="mt-1 text-amber-200/80">
								The product's approved Product Truth advanced after this copy was activated. Regenerate and re-approve it in the Copy Register before the next production run.
							</p>
							<a
								href={`/creative/copy-registry?product_id=${encodeURIComponent(productId || "")}&blueprint_id=${encodeURIComponent(activeBlueprint.blueprint_id)}`}
								target="_blank"
								rel="noreferrer"
								data-testid="active-stale-revalidate-link"
								className="mt-2 inline-flex items-center gap-1 font-semibold text-amber-200 hover:text-amber-100"
							>
								<span>Revalidate in Copy Register</span>
								<ExternalLink size={12} />
							</a>
						</div>
					) : null}

					<div className="mt-3 space-y-2 text-xs">
						<div>
							<span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Angle:</span>
							<p className="font-medium text-slate-200">{angleText}</p>
						</div>
						<div>
							<span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Hook:</span>
							<p className="italic text-emerald-100">"{hook}"</p>
						</div>
						{body ? (
							<div>
								<span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Body:</span>
								<p className="line-clamp-2 text-slate-300">{body}</p>
							</div>
						) : null}
						{cta && cta !== "—" ? (
							<div>
								<span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">CTA:</span>
								<p className="font-semibold text-blue-200">{cta}</p>
							</div>
						) : null}
					</div>
				</div>

				<TechnicalDetails title="Technical details">
					<div className="space-y-1 font-mono text-[11px]">
						<div>Blueprint ID: {activeBlueprint.blueprint_id}</div>
						<div>Revision: r{activeBlueprint.revision}</div>
						<div>Formula: {activeBlueprint.formula_id} · {activeBlueprint.formula_version}</div>
						<div>Status: {activeBlueprint.status}</div>
						<div>Authority Scope: Product-global across all copy-required creator lanes</div>
						{activeBlueprint.current_authority_fingerprint ? (
							<div>Fingerprint: {activeBlueprint.current_authority_fingerprint}</div>
						) : null}
					</div>
				</TechnicalDetails>
			</div>
		);
	}

	// Interactive Selection Mode
	return (
		<div className={`space-y-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4 ${className}`} data-testid="copywriting-source-selector">
			{/* Source Tab Chooser */}
			<div className="flex items-center justify-between border-b border-slate-800 pb-3">
				<div className="flex items-center gap-2">
					<button
						type="button"
						data-testid="copy-source-register"
						onClick={() => {
							setActiveSource("REGISTER");
							setPage(1);
						}}
						className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
							activeSource === "REGISTER"
								? "border border-blue-500/40 bg-blue-600/20 text-blue-100"
								: "border border-slate-800 bg-slate-950 text-slate-400 hover:text-slate-200"
						}`}
					>
						<FileText size={14} />
						<span>Copy Register</span>
						{blueprints.length ? (
							<span className="rounded-full bg-blue-500/20 px-1.5 py-0.2 text-[10px] text-blue-300">
								{blueprints.length}
							</span>
						) : null}
					</button>

					<button
						type="button"
						data-testid="copy-source-ai"
						onClick={() => setActiveSource("AI_ASSISTANT")}
						className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
							activeSource === "AI_ASSISTANT"
								? "border border-violet-500/40 bg-violet-600/20 text-violet-100"
								: "border border-slate-800 bg-slate-950 text-slate-400 hover:text-slate-200"
						}`}
					>
						<Sparkles size={14} />
						<span>AI Copy Assistant</span>
					</button>
				</div>

				{activeBlueprint ? (
					<button
						type="button"
						onClick={() => setIsSelecting(false)}
						className="text-xs text-slate-400 hover:text-slate-200"
					>
						Cancel
					</button>
				) : null}
			</div>

			{error ? (
				<div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200" data-testid="copy-selector-error">
					{error}
				</div>
			) : null}
			{successMsg ? (
				<div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200" data-testid="copy-selector-success">
					{successMsg}
				</div>
			) : null}

			{/* VIEW 1: COPY REGISTER */}
			{activeSource === "REGISTER" && (
				<div className="space-y-4" data-testid="copy-register-picker">
					{/* Step A: Angle Selection */}
					<div className="space-y-1.5">
						<label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
							1. Filter by Angle
						</label>
						<div className="flex flex-wrap gap-1.5">
							<button
								type="button"
								data-testid="angle-filter-all"
								onClick={() => {
									setSelectedAngle("ALL");
									setPage(1);
								}}
								className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
									selectedAngle === "ALL"
										? "border-blue-400 bg-blue-500/20 text-blue-100"
										: "border-slate-800 bg-slate-950 text-slate-400 hover:border-slate-700 hover:text-slate-200"
								}`}
							>
								All Angles ({blueprints.length})
							</button>
							{availableAngles.map((ang) => (
								<button
									key={ang.id}
									type="button"
									data-testid={`angle-filter-${ang.id}`}
									onClick={() => {
										setSelectedAngle(ang.id);
										setPage(1);
									}}
									className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
										selectedAngle === ang.id
											? "border-blue-400 bg-blue-500/20 text-blue-100"
											: "border-slate-800 bg-slate-950 text-slate-400 hover:border-slate-700 hover:text-slate-200"
									}`}
								>
									{ang.definition}
								</button>
							))}
						</div>
					</div>

					{/* Step B: Eligible Copy Sets */}
					<div className="space-y-2">
						<div className="flex items-center justify-between">
							<label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
								2. Select Copy Set ({filteredBlueprints.length} available)
							</label>
							{totalPages > 1 && (
								<div className="flex items-center gap-2 text-xs text-slate-400">
									<span>
										Page {page} of {totalPages}
									</span>
									<div className="flex items-center gap-1">
										<button
											type="button"
											disabled={page <= 1}
											onClick={() => setPage((p) => Math.max(1, p - 1))}
											className="rounded border border-slate-800 p-1 hover:bg-slate-800 disabled:opacity-30"
										>
											<ChevronLeft size={14} />
										</button>
										<button
											type="button"
											disabled={page >= totalPages}
											onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
											className="rounded border border-slate-800 p-1 hover:bg-slate-800 disabled:opacity-30"
										>
											<ChevronRight size={14} />
										</button>
									</div>
								</div>
							)}
						</div>

						{loading ? (
							<div className="py-8 text-center text-xs text-slate-500">
								<RefreshCw className="mx-auto mb-2 animate-spin" size={18} />
								Loading copy sets...
							</div>
						) : paginatedBlueprints.length === 0 ? (
							<div className="rounded-xl border border-dashed border-slate-800 p-6 text-center text-xs text-slate-500">
								<p>No copy sets found for this angle.</p>
								<p className="mt-1">
									Switch to "AI Copy Assistant" above or visit the Copy Register to generate new copy.
								</p>
							</div>
						) : (
							<div className="grid gap-3 sm:grid-cols-2">
								{paginatedBlueprints.map((bp) => {
									const hook = extractHook(bp);
									const body = extractBody(bp);
									const cta = extractCta(bp);
									const isCurrent = bp.blueprint_id === activeBlueprintId;
									const canActivate = bp.current_authority_activation_allowed === true;
									const isStaleHistorical = (bp.status === "PRODUCTION_VALID" || bp.status === "V2_APPROVED") && !canActivate;

									return (
										<div
											key={`${bp.blueprint_id}:${bp.revision}`}
											data-testid="copy-set-card"
											className={`flex flex-col justify-between rounded-xl border p-3.5 transition-colors ${
												isCurrent
													? "border-emerald-500/50 bg-emerald-500/10"
													: canActivate
														? "border-slate-800 bg-slate-950/70 hover:border-slate-700"
														: isStaleHistorical
															? "border-amber-500/30 bg-amber-500/5"
															: "border-slate-800/80 bg-slate-950/40"
											}`}
										>
											<div className="space-y-2 text-xs">
												<div className="flex items-center justify-between gap-2">
													<span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] font-semibold uppercase text-slate-300">
														{bp.angle?.definition || "Angle"}
													</span>
													{isCurrent ? (
														<span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400" data-testid="copy-status-active">
															<Check size={12} /> ACTIVE
														</span>
													) : canActivate ? (
														<span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[9px] font-bold text-emerald-300" data-testid="copy-status-approved">
															APPROVED
														</span>
													) : isStaleHistorical ? (
														<span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[9px] font-bold text-amber-300" data-testid="copy-status-stale">
															STALE — REVALIDATION REQUIRED
														</span>
													) : (
														<span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[9px] font-bold text-amber-300" data-testid="copy-status-needs-approval">
															NEEDS APPROVAL
														</span>
													)}
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
														<p className="line-clamp-2 text-slate-300">{body}</p>
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

											<div className="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between gap-2">
												<span className="text-[10px] text-slate-500">
													{bp.estimated_word_count ? `${bp.estimated_word_count} words` : ""}
													{bp.target_duration_seconds ? ` · ${bp.target_duration_seconds}s` : ""}
												</span>

												{isCurrent ? (
													<button
														type="button"
														disabled
														className="rounded-lg bg-emerald-500/20 px-3 py-1.5 text-xs font-bold text-emerald-300 cursor-default"
													>
														Active Copy
													</button>
												) : canActivate ? (
													<button
														type="button"
														data-testid="use-this-copy-button"
														disabled={loading}
														onClick={() => void handleUseCopy(bp)}
														className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-40"
													>
														Use This Copy
													</button>
												) : isStaleHistorical ? (
													<a
														href={`/creative/copy-registry?product_id=${encodeURIComponent(productId || "")}&blueprint_id=${encodeURIComponent(bp.blueprint_id)}`}
														target="_blank"
														rel="noreferrer"
														data-testid="review-in-copy-register-link"
														className="inline-flex items-center gap-1 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/20"
													>
														<span>Revalidate in Copy Register</span>
														<ExternalLink size={12} />
													</a>
												) : (
													<a
														href={`/creative/copy-registry?product_id=${encodeURIComponent(productId || "")}&blueprint_id=${encodeURIComponent(bp.blueprint_id)}`}
														target="_blank"
														rel="noreferrer"
														data-testid="review-in-copy-register-link"
														className="inline-flex items-center gap-1 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/20"
													>
														<span>Review in Copy Register</span>
														<ExternalLink size={12} />
													</a>
												)}
											</div>
										</div>
									);
								})}
							</div>
						)}
					</div>
				</div>
			)}

			{/* VIEW 2: AI COPY ASSISTANT */}
			{activeSource === "AI_ASSISTANT" && (
				<div className="space-y-4" data-testid="ai-copy-assistant-panel">
					<div className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-4 space-y-4">
						<div className="flex items-center gap-2 text-xs font-semibold text-violet-200">
							<Bot size={16} />
							<span>Grounded AI Copy Assistant</span>
						</div>

						{/* Formula */}
						<div className="space-y-1">
							<label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
								1. Select Copy Strategy / Formula
							</label>
							<select
								value={selectedFormulaId}
								onChange={(e) => {
									setSelectedFormulaId(e.target.value);
									setAiAngles([]);
									setSelectedAiAngleId("");
									setGeneratedDraftBlueprint(null);
								}}
								className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200"
							>
								<option value="">Choose formula...</option>
								{formulas.map((f) => (
									<option key={f.formula_id} value={f.formula_id}>
										{f.display_name}
									</option>
								))}
							</select>
						</div>

						{/* Generate Angles Button */}
						{selectedFormulaId && aiAngles.length === 0 && (
							<button
								type="button"
								disabled={generatingAi}
								onClick={() => void handleGenerateAiAngles()}
								className="w-full rounded-lg border border-violet-500/40 bg-violet-600/30 px-3 py-2 text-xs font-bold text-violet-100 hover:bg-violet-600/50 disabled:opacity-40"
							>
								{generatingAi ? "Generating grounded angles..." : "Generate Angle Options"}
							</button>
						)}

						{/* Angles List */}
						{aiAngles.length > 0 && (
							<div className="space-y-2">
								<label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
									2. Select Angle
								</label>
								<div className="space-y-1.5">
									{aiAngles.map((ang) => (
										<label
											key={ang.angle_id}
											className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 text-xs transition-colors ${
												selectedAiAngleId === ang.angle_id
													? "border-violet-400 bg-violet-500/20 text-violet-100"
													: "border-slate-800 bg-slate-950/60 text-slate-300 hover:border-slate-700"
											}`}
										>
											<input
												type="radio"
												name="ai-angle"
												checked={selectedAiAngleId === ang.angle_id}
												onChange={() => {
													setSelectedAiAngleId(ang.angle_id);
													setSelectedFactIds(ang.evidence_fact_ids || []);
													setGeneratedDraftBlueprint(null);
												}}
												className="mt-0.5"
											/>
											<div className="flex-1">
												<div className="font-semibold">{ang.definition}</div>
											</div>
										</label>
									))}
								</div>

								{/* Generate Copy Draft Button */}
								<button
									type="button"
									disabled={generatingAi || !selectedAiAngleId}
									onClick={() => void handleGenerateAiCopy()}
									className="mt-3 w-full rounded-lg bg-violet-600 px-4 py-2.5 text-xs font-bold text-white hover:bg-violet-500 disabled:opacity-40"
									data-testid="generate-ai-copy-button"
								>
									{generatingAi ? "Generating Grounded Copy..." : "Generate AI Copy Draft"}
								</button>
							</div>
						)}

						{/* Display Generated Draft with Review Notice */}
						{generatedDraftBlueprint && (
							<div className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 space-y-3" data-testid="ai-generated-draft-preview">
								<div className="flex items-center gap-2 text-xs font-bold text-amber-200">
									<ShieldAlert size={16} />
									<span>Draft Copy Generated (Governance Review Required)</span>
								</div>
								<p className="text-[11px] text-amber-100/90">
									Under BOSMAX V2 governance, AI-generated copy cannot be auto-approved or activated directly. Review and approve this copy in the Copy Register before activating.
								</p>

								<div className="rounded-lg border border-slate-800 bg-slate-950 p-3 text-xs space-y-1.5">
									<div>
										<span className="text-[9px] font-bold uppercase tracking-wider text-slate-500">Hook:</span>
										<p className="font-medium text-slate-100">"{extractHook(generatedDraftBlueprint)}"</p>
									</div>
									<div>
										<span className="text-[9px] font-bold uppercase tracking-wider text-slate-500">Body:</span>
										<p className="line-clamp-2 text-slate-300">{extractBody(generatedDraftBlueprint)}</p>
									</div>
									<div>
										<span className="text-[9px] font-bold uppercase tracking-wider text-slate-500">CTA:</span>
										<p className="font-semibold text-blue-200">{extractCta(generatedDraftBlueprint)}</p>
									</div>
								</div>

								<div className="pt-1">
									<a
										href={`/creative/copy-registry?product_id=${encodeURIComponent(productId || "")}&blueprint_id=${encodeURIComponent(generatedDraftBlueprint.blueprint_id)}`}
										target="_blank"
										rel="noreferrer"
										data-testid="open-ai-draft-in-register"
										className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-4 py-2 text-xs font-bold text-white hover:bg-amber-500"
									>
										<span>Open in Copy Register to Review & Approve</span>
										<ExternalLink size={13} />
									</a>
								</div>
							</div>
						)}
					</div>
				</div>
			)}
		</div>
	);
}

export default CopywritingSourceSelector;
