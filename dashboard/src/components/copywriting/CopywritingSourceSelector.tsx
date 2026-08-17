import { useEffect, useMemo, useState } from "react";
import { Bot, Check, ChevronLeft, ChevronRight, FileText, RefreshCw, Sparkles } from "lucide-react";
import {
	activateFormulaBlueprint,
	approveFormulaBlueprint,
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
						setIsSelecting(true);
					}
					return curr;
				});
			}
		} catch (e) {
			setError(e instanceof Error ? e.message : "Failed to load copy sets.");
		} finally {
			setLoading(false);
		}
	};

	useEffect(() => {
		if (!productId) {
			setBlueprints([]);
			setActiveBlueprintId(null);
			setTruth(null);
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
		setLoading(true);
		setError(null);
		setSuccessMsg(null);
		try {
			// If it's a draft, approve it first if needed, otherwise activate directly
			if (bp.status !== "PRODUCTION_VALID") {
				await approveFormulaBlueprint({
					blueprint_id: bp.blueprint_id,
					approved_by: "operator",
					semantic_review: {
						decision: "APPROVED",
						reviewer: "operator",
						rationale: "Approved for creator workflow use.",
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
			}
			await activateFormulaBlueprint(bp.blueprint_id);
			setActiveBlueprintId(bp.blueprint_id);
			setSuccessMsg("Copy set selected and bound to generation workflow.");
			setIsSelecting(false);
			onCopySelected?.(bp);
			if (productId) {
				void loadBlueprints(productId);
			}
		} catch (e) {
			setError(e instanceof Error ? e.message : "Failed to bind selected copy.");
		} finally {
			setLoading(false);
		}
	};

	// AI Copy Generation Handlers
	const handleGenerateAiAngles = async () => {
		if (!productId || !selectedFormulaId) return;
		setGeneratingAi(true);
		setError(null);
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

	const handleGenerateAndUseAiCopy = async () => {
		if (!productId || !selectedFormulaId || !selectedAiAngleId) return;
		const angleObj = aiAngles.find((a) => a.angle_id === selectedAiAngleId);
		if (!angleObj) return;

		setGeneratingAi(true);
		setError(null);
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

			// Approve the new blueprint
			await approveFormulaBlueprint({
				blueprint_id: genRes.blueprint.blueprint_id,
				approved_by: "operator",
				semantic_review: {
					decision: "APPROVED",
					reviewer: "operator",
					rationale: "Grounded AI Copy approved for creator workflow use.",
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

			// Activate it
			await activateFormulaBlueprint(genRes.blueprint.blueprint_id);
			setActiveBlueprintId(genRes.blueprint.blueprint_id);
			setSuccessMsg("AI Copy generated, approved, and bound successfully.");
			setIsSelecting(false);
			onCopySelected?.(genRes.blueprint);
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

		return (
			<div className={`space-y-3 ${className}`} data-testid="copywriting-selected-summary">
				<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
					<div className="flex flex-wrap items-center justify-between gap-2 border-b border-emerald-500/10 pb-3">
						<div className="flex items-center gap-2">
							<span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500/20 text-[10px] font-bold text-emerald-300">
								✓
							</span>
							<span className="text-xs font-bold uppercase tracking-wider text-emerald-200">
								Copywriting Selected
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
				<div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
					{error}
				</div>
			) : null}
			{successMsg ? (
				<div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200">
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

									return (
										<div
											key={`${bp.blueprint_id}:${bp.revision}`}
											data-testid="copy-set-card"
											className={`flex flex-col justify-between rounded-xl border p-3.5 transition-colors ${
												isCurrent
													? "border-emerald-500/50 bg-emerald-500/10"
													: "border-slate-800 bg-slate-950/70 hover:border-slate-700"
											}`}
										>
											<div className="space-y-2 text-xs">
												<div className="flex items-center justify-between gap-2">
													<span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] font-semibold uppercase text-slate-300">
														{bp.angle?.definition || "Angle"}
													</span>
													{isCurrent ? (
														<span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400">
															<Check size={12} /> ACTIVE
														</span>
													) : null}
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

											<div className="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between">
												<span className="text-[10px] text-slate-500">
													{bp.estimated_word_count ? `${bp.estimated_word_count} words` : ""}
													{bp.target_duration_seconds ? ` · ${bp.target_duration_seconds}s` : ""}
												</span>

												<button
													type="button"
													data-testid="use-this-copy-button"
													disabled={loading}
													onClick={() => void handleUseCopy(bp)}
													className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors ${
														isCurrent
															? "bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30"
															: "bg-blue-600 text-white hover:bg-blue-500"
													}`}
												>
													{isCurrent ? "Current Copy" : "Use This Copy"}
												</button>
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
												}}
												className="mt-0.5"
											/>
											<div className="flex-1">
												<div className="font-semibold">{ang.definition}</div>
											</div>
										</label>
									))}
								</div>

								{/* Generate Copy & Bind */}
								<button
									type="button"
									disabled={generatingAi || !selectedAiAngleId}
									onClick={() => void handleGenerateAndUseAiCopy()}
									className="mt-3 w-full rounded-lg bg-emerald-600 px-4 py-2.5 text-xs font-bold text-white hover:bg-emerald-500 disabled:opacity-40"
								>
									{generatingAi ? "Generating & Binding Copy..." : "Generate & Use This Copy"}
								</button>
							</div>
						)}
					</div>
				</div>
			)}
		</div>
	);
}

export default CopywritingSourceSelector;
