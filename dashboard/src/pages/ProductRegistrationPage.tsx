import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getAPI, postAPI } from "../api/client";
import AIFormPack from "../components/product-registration/AIFormPack";
import BulkFastMossConvertTab from "../components/product-registration/BulkFastMossConvertTab";
import ProductKnowledgeIntakeForm from "../components/product-registration/ProductKnowledgeIntakeForm";
import ProductKnowledgeResultPanel from "../components/product-registration/ProductKnowledgeResultPanel";
import RegistrationReviewDraftPanel from "../components/product-registration/RegistrationReviewDraftPanel";
import type {
	ProductKnowledgeCompleteResponse,
	RegistrationReviewDraft,
} from "../types";

type ActiveTab = "single" | "bulk";

const PAGE_SIZE_DRAFTS = 10;

export default function ProductRegistrationPage() {
	const [searchParams, setSearchParams] = useSearchParams();
	const [activeTab, setActiveTab] = useState<ActiveTab>(
		searchParams.get("tab") === "bulk" ? "bulk" : "single",
	);
	const [result, setResult] = useState<ProductKnowledgeCompleteResponse | null>(
		null,
	);
	const [reviewDraft, setReviewDraft] =
		useState<RegistrationReviewDraft | null>(null);
	const [savedDrafts, setSavedDrafts] = useState<RegistrationReviewDraft[]>([]);
	const [currentPageDrafts, setCurrentPageDrafts] = useState(1);
	const [isProcessing, setIsProcessing] = useState(false);
	const [isLoadingDrafts, setIsLoadingDrafts] = useState(false);

	const fetchDrafts = useCallback(async () => {
		setIsLoadingDrafts(true);
		try {
			const drafts = await getAPI<RegistrationReviewDraft[]>(
				"/api/product-registration/review-drafts",
			);
			setSavedDrafts(drafts);
		} catch (err) {
			console.error("Failed to fetch drafts:", err);
		} finally {
			setIsLoadingDrafts(false);
		}
	}, []);

	useEffect(() => {
		void fetchDrafts();
	}, [fetchDrafts]);

	const handleComplete = (data: ProductKnowledgeCompleteResponse) => {
		setResult(data);
		setReviewDraft(null); // Clear draft if new result comes in
	};

	const handleCreateDraft = async () => {
		if (!result) return;
		setIsProcessing(true);
		try {
			const draft = await postAPI<RegistrationReviewDraft>(
				"/api/product-registration/review-draft",
				result,
			);
			// Persist the draft immediately
			const saved = await postAPI<RegistrationReviewDraft>(
				"/api/product-registration/review-drafts",
				draft,
			);
			setReviewDraft(saved);
			fetchDrafts();
			// Smooth scroll to draft
			setTimeout(() => {
				document
					.getElementById("review-draft-section")
					?.scrollIntoView({ behavior: "smooth" });
			}, 100);
		} catch (err) {
			console.error("Failed to create review draft:", err);
			alert("Failed to create review draft. See console for details.");
		} finally {
			setIsProcessing(false);
		}
	};

	const handleOpenDraftById = async (draftId: string) => {
		try {
			const draft = await getAPI<RegistrationReviewDraft>(
				`/api/product-registration/review-drafts/${draftId}`,
			);
			handleSelectDraft(draft);
		} catch (err) {
			console.error("Failed to load draft:", err);
		}
	};

	const handleDeleteDraft = async (draftId: string) => {
		if (!window.confirm("Delete this draft permanently?")) return;
		try {
			await fetch(`/api/product-registration/review-drafts/${draftId}`, {
				method: "DELETE",
			});
			if (reviewDraft?.review_draft_id === draftId) setReviewDraft(null);
			fetchDrafts();
		} catch (err) {
			console.error("Failed to delete draft:", err);
		}
	};

	const handleSelectDraft = (draft: RegistrationReviewDraft) => {
		setReviewDraft(draft);
		setResult(null);
		setActiveTab("single");
		setSearchParams({});
		setTimeout(() => {
			document
				.getElementById("review-draft-section")
				?.scrollIntoView({ behavior: "smooth" });
		}, 100);
	};

	const totalPagesDrafts = Math.ceil(savedDrafts.length / PAGE_SIZE_DRAFTS);
	const safePageDrafts = Math.min(
		Math.max(1, currentPageDrafts),
		totalPagesDrafts || 1,
	);
	const paginatedDrafts = savedDrafts.slice(
		(safePageDrafts - 1) * PAGE_SIZE_DRAFTS,
		safePageDrafts * PAGE_SIZE_DRAFTS,
	);

	return (
		<div className="flex h-full flex-col bg-slate-950 px-4 py-4 md:px-8 md:py-8 overflow-y-auto">
			<div className="mb-6 flex flex-col gap-4 lg:mb-8 lg:flex-row lg:items-center lg:justify-between">
				<div>
					<h2 className="text-xl font-bold tracking-tight text-white md:text-2xl">
						Smart Product Registration
					</h2>
					<p className="text-sm italic text-slate-400">
						Transforming messy product knowledge into structured Product
						Intelligence.
					</p>
				</div>
				<div className="flex items-center gap-3">
					<div className="px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-[10px] font-bold uppercase tracking-widest">
						Phase 4: Controlled Registration Authority
					</div>
					{activeTab === "single" && (
						<button
							type="button"
							onClick={() => {
								setActiveTab("bulk");
								setSearchParams("tab=bulk");
							}}
							className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-[11px] font-bold uppercase tracking-widest transition-all shadow-lg shadow-indigo-600/20"
						>
							<svg
								aria-hidden="true"
								className="w-3.5 h-3.5 shrink-0"
								fill="none"
								viewBox="0 0 24 24"
								stroke="currentColor"
								strokeWidth={2}
							>
								<path
									strokeLinecap="round"
									strokeLinejoin="round"
									d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
								/>
							</svg>
							Open Bulk FastMoss Convert
						</button>
					)}
				</div>
			</div>

			<div
				data-testid="product-intelligence-bridge"
				className="mb-6 rounded-xl border border-sky-500/30 bg-sky-500/5 p-4"
			>
				<div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
					<div className="space-y-1">
						<div className="text-sm font-bold text-sky-100">
							Product Truth &amp; AI Fill Missing (Product Intelligence)
						</div>
						<p className="max-w-2xl text-xs leading-relaxed text-slate-400">
							Registration captures raw evidence. To review, enrich, and approve{" "}
							<span className="font-semibold text-slate-200">Product Truth</span>{" "}
							(Product Knowledge, Benefits, Usage, Ingredients, Warnings, Target
							Customer), open the Product Intelligence panel for the product —{" "}
							<span className="font-semibold text-amber-200">Recompute</span> is
							deterministic (no AI), and{" "}
							<span className="font-semibold text-sky-200">AI Fill Missing</span>{" "}
							uses DeepSeek to propose review-only draft values for empty fields.
							Manual and imported products use the same panel.
						</p>
					</div>
					<Link
						to="/products?tab=INTELLIGENCE"
						data-testid="open-product-intelligence-link"
						className="shrink-0 rounded-lg border border-sky-400/40 bg-sky-500/15 px-4 py-2 text-center text-[11px] font-bold uppercase tracking-widest text-sky-100 hover:bg-sky-500/25"
					>
						Open Product Intelligence / AI Fill Missing
					</Link>
				</div>
				<p className="mt-2 text-[10px] text-slate-500">
					Workflow: <span className="text-slate-300">Copy Intelligence</span> = avatar
					/ copy context review · <span className="text-slate-300">Smart Registration
					/ Product Intelligence</span> = Product Truth review &amp; enrichment ·{" "}
					<span className="text-slate-300">Copy Registry</span> = approved / generated
					copy output library. Nothing here auto-approves Product Truth or routes raw
					seed data to generation.
				</p>
			</div>

			<div className="mb-6 flex gap-1 rounded-xl bg-slate-900/60 border border-slate-800 p-1 w-fit">
				<button
					type="button"
					onClick={() => {
						setActiveTab("single");
						setSearchParams({});
					}}
					className={`px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-widest transition-all ${
						activeTab === "single"
							? "bg-indigo-600 text-white shadow-lg shadow-indigo-600/20"
							: "text-slate-400 hover:text-white"
					}`}
				>
					Single Product
				</button>
				<button
					type="button"
					onClick={() => {
						setActiveTab("bulk");
						setSearchParams("tab=bulk");
					}}
					className={`px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-widest transition-all ${
						activeTab === "bulk"
							? "bg-indigo-600 text-white shadow-lg shadow-indigo-600/20"
							: "text-slate-400 hover:text-white"
					}`}
				>
					Bulk FastMoss Convert
				</button>
			</div>

			{activeTab === "bulk" && (
				<BulkFastMossConvertTab onOpenDraft={handleOpenDraftById} />
			)}

			{activeTab === "single" && (
				<div className="grid grid-cols-1 lg:grid-cols-[1fr_400px] gap-8">
					<div className="space-y-8 pb-20">
						{!reviewDraft && (
							<>
								<AIFormPack
									onComplete={handleComplete}
									setIsProcessing={setIsProcessing}
									isProcessing={isProcessing}
								/>

								<section className="rounded-3xl border border-slate-800 bg-slate-900/40 p-6 shadow-2xl backdrop-blur-sm">
									<div className="mb-6">
										<h3 className="text-lg font-semibold text-white">
											Product Knowledge Intake
										</h3>
										<p className="text-xs text-slate-500 mt-1">
											Paste any text, ingredients, or benefits. The system will
											extract facts and suggest a profile.
										</p>
									</div>
									<ProductKnowledgeIntakeForm
										onComplete={handleComplete}
										setIsProcessing={setIsProcessing}
										isProcessing={isProcessing}
									/>
								</section>
							</>
						)}

						{result && !reviewDraft && (
							<section className="rounded-3xl border border-slate-800 bg-slate-900/40 p-6 shadow-2xl backdrop-blur-sm animate-in fade-in slide-in-from-bottom-4 duration-700">
								<div className="mb-6 flex items-center justify-between">
									<div>
										<h3 className="text-lg font-semibold text-white">
											Intelligence Extraction Report
										</h3>
										<p className="text-xs text-slate-500 mt-1">
											Status:{" "}
											<span
												className={
													result.completion_status === "COMPLETION_READY"
														? "text-emerald-400"
														: "text-amber-400"
												}
											>
												{result.completion_status}
											</span>
										</p>
									</div>
									<div className="flex items-center gap-4">
										<div
											className={`px-2 py-1 rounded text-[10px] font-bold ${result.input_quality_status === "SUFFICIENT" ? "bg-emerald-500/20 text-emerald-400" : "bg-amber-500/20 text-amber-400"}`}
										>
											QUALITY: {result.input_quality_status}
										</div>
										<button
											type="button"
											onClick={handleCreateDraft}
											disabled={isProcessing}
											className="px-4 py-2 rounded-xl bg-indigo-500 hover:bg-indigo-600 disabled:bg-slate-800 text-white text-xs font-bold uppercase tracking-widest transition-all shadow-lg shadow-indigo-500/20"
										>
											{isProcessing ? "Processing..." : "Create Review Draft"}
										</button>
									</div>
								</div>

								<ProductKnowledgeResultPanel result={result} />
							</section>
						)}

						{reviewDraft && (
							<section
								id="review-draft-section"
								className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700"
							>
								<div className="flex items-center justify-between">
									<h3 className="text-xl font-bold text-white">
										Registration Review Queue
									</h3>
									<button
										type="button"
										onClick={() => {
											setReviewDraft(null);
											fetchDrafts();
										}}
										className="text-xs font-bold text-slate-500 hover:text-white transition-colors uppercase tracking-widest"
									>
										Back to Intake
									</button>
								</div>
								<RegistrationReviewDraftPanel
									draft={reviewDraft}
									onUpdate={(updated) => {
										setReviewDraft(updated);
										fetchDrafts();
									}}
									onClear={() => {
										setReviewDraft(null);
										setResult(null);
										fetchDrafts();
									}}
								/>
							</section>
						)}
					</div>

					<aside className="space-y-6">
						<section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
							<div className="flex items-center justify-between mb-4">
								<h4 className="text-xs font-bold uppercase tracking-widest text-slate-500">
									Review Draft Queue
								</h4>
								<button
									type="button"
									onClick={fetchDrafts}
									className="p-1 hover:text-white text-slate-500 transition-colors"
								>
									<svg
										aria-hidden="true"
										className={`w-3.5 h-3.5 ${isLoadingDrafts ? "animate-spin" : ""}`}
										fill="none"
										viewBox="0 0 24 24"
										stroke="currentColor"
									>
										<path
											strokeLinecap="round"
											strokeLinejoin="round"
											strokeWidth={2}
											d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
										/>
									</svg>
								</button>
							</div>

							<div className="space-y-2 max-h-[300px] overflow-y-auto pr-1 custom-scrollbar">
								{savedDrafts.length === 0 ? (
									<p className="text-[10px] text-slate-600 italic">
										No active review drafts.
									</p>
								) : (
									paginatedDrafts.map((d) => (
										<div
											key={d.review_draft_id}
											className="relative group/card"
										>
											<button
												type="button"
												onClick={() => handleSelectDraft(d)}
												className={`w-full p-3 rounded-xl border text-left transition-all group ${
													reviewDraft?.review_draft_id === d.review_draft_id
														? "bg-indigo-500/10 border-indigo-500/40 ring-1 ring-indigo-500/20"
														: "bg-slate-800/30 border-slate-700/50 hover:border-slate-600"
												}`}
											>
												<div className="flex items-center justify-between mb-1">
													<span className="text-[10px] font-bold text-slate-400 group-hover:text-slate-200 truncate pr-2">
														{d.review_draft_id}
													</span>
													<span
														className={`text-[8px] font-bold px-1 rounded ${
															d.review_status === "COMMITTED"
																? "bg-blue-500/20 text-blue-400"
																: d.review_status === "BLOCKED"
																	? "bg-red-500/20 text-red-400"
																	: "bg-amber-500/20 text-amber-400"
														}`}
													>
														{d.review_status}
													</span>
												</div>
												<div className="text-xs text-white font-medium truncate">
													{d.declared_evidence_fields.product_name ||
														"Unnamed Product"}
												</div>
												<div className="text-[8px] text-slate-500 mt-1 uppercase tracking-widest">
													{d.updated_at
														? new Date(d.updated_at).toLocaleDateString()
														: "Unknown date"}
												</div>
											</button>
											<button
												type="button"
												onClick={() => handleDeleteDraft(d.review_draft_id)}
												className="absolute top-2 right-2 opacity-0 group-hover/card:opacity-100 transition-opacity p-1 rounded bg-red-500/10 hover:bg-red-500/30 text-red-400 hover:text-red-300"
												title="Delete draft"
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													className="h-3 w-3"
													fill="none"
													viewBox="0 0 24 24"
													stroke="currentColor"
												>
													<title>Delete draft</title>
													<path
														strokeLinecap="round"
														strokeLinejoin="round"
														strokeWidth={2}
														d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
													/>
												</svg>
											</button>
										</div>
									))
								)}
							</div>
							{totalPagesDrafts > 1 && (
								<div className="flex items-center justify-center gap-1 mt-3 flex-wrap">
									<button
										type="button"
										onClick={() =>
											setCurrentPageDrafts((p) => Math.max(1, p - 1))
										}
										disabled={safePageDrafts === 1}
										className="px-2 py-1 rounded text-[10px] bg-slate-800 border border-slate-700 text-slate-400 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
									>
										Prev
									</button>
									{(() => {
										const pages: (number | string)[] = [];
										const delta = 1;
										let last = 0;
										for (let pg = 1; pg <= totalPagesDrafts; pg++) {
											if (
												pg === 1 ||
												pg === totalPagesDrafts ||
												(pg >= safePageDrafts - delta &&
													pg <= safePageDrafts + delta)
											) {
												if (last && pg - last > 1) pages.push(`e${pg}`);
												pages.push(pg);
												last = pg;
											}
										}
										return pages.map((pg) =>
											typeof pg === "string" ? (
												<span
													key={pg}
													className="px-1 text-[10px] text-slate-600"
												>
													…
												</span>
											) : (
												<button
													key={pg}
													type="button"
													onClick={() => setCurrentPageDrafts(pg)}
													className={`w-6 h-6 rounded text-[10px] border ${safePageDrafts === pg ? "bg-indigo-600 border-indigo-500 text-white" : "bg-slate-800 border-slate-700 text-slate-400 hover:text-white"}`}
												>
													{pg}
												</button>
											),
										);
									})()}
									<button
										type="button"
										onClick={() =>
											setCurrentPageDrafts((p) =>
												Math.min(totalPagesDrafts, p + 1),
											)
										}
										disabled={safePageDrafts === totalPagesDrafts}
										className="px-2 py-1 rounded text-[10px] bg-slate-800 border border-slate-700 text-slate-400 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
									>
										Next
									</button>
								</div>
							)}
						</section>

						<div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
							<h4 className="text-xs font-bold uppercase tracking-widest text-slate-500 mb-4">
								Governance & Authority
							</h4>
							<div className="space-y-4 text-xs">
								<div className="flex items-start gap-3">
									<div className="mt-0.5 h-2 w-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)]" />
									<p className="text-slate-400 leading-relaxed">
										<strong className="text-slate-200">
											Controlled Storage:
										</strong>{" "}
										Review drafts are persisted locally. Progress is saved
										automatically during the review process.
									</p>
								</div>
								<div className="flex items-start gap-3">
									<div className="mt-0.5 h-2 w-2 rounded-full bg-indigo-500 shadow-[0_0_8px_rgba(99,102,241,0.5)]" />
									<p className="text-slate-400 leading-relaxed">
										<strong className="text-slate-200">Gated Commit:</strong>{" "}
										Registration requires approval of all review fields and a
										confirmation phrase to prevent unauthorized mutations.
									</p>
								</div>
								<div className="flex items-start gap-3">
									<div className="mt-0.5 h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
									<p className="text-slate-400 leading-relaxed">
										<strong className="text-slate-200">Canonical Truth:</strong>{" "}
										Once committed, the product becomes part of the BOSMAX
										canonical dataset for asset generation.
									</p>
								</div>
							</div>
						</div>
					</aside>
				</div>
			)}
		</div>
	);
}
