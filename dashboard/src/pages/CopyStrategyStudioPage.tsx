import { Ban, Check, Loader2, RefreshCw, Save, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchProductCatalog } from "../api/products";
import {
	approveCopySet,
	COPY_SET_APPROVAL_PHRASE,
	type CopySet,
	type CopySetStatus,
	generateCopySet,
	listCopySetsForProduct,
	patchCopySet,
	regenerateCopySet,
	rejectCopySet,
} from "../api/copySets";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { Product } from "../types";

// Copy Strategy Studio (Phase 2) — operator surface for the pre-generation
// copywriting approval loop: product -> angle/hook/subhook/usp/cta -> Copy Set
// -> review -> approve. It talks ONLY to /api/copy-sets. It does not compile a
// final prompt, does not enforce Google Flow execution gates, and never sends a
// job to Flow — those remain Phase 3.

interface CopySetForm {
	angle: string;
	hook: string;
	subhook: string;
	uspText: string; // one USP per line
	cta: string;
	platform: string;
	language: string;
	route_type: string;
	formula_family: string;
}

type NoticeTone = "idle" | "info" | "success" | "warning" | "error";

interface Notice {
	tone: NoticeTone;
	message: string;
}

const BLANK_FORM: CopySetForm = {
	angle: "",
	hook: "",
	subhook: "",
	uspText: "",
	cta: "",
	platform: "TIKTOK",
	language: "BM_MS",
	route_type: "DIRECT",
	formula_family: "HSO",
};

function uspTextToArray(text: string): string[] {
	return text
		.split("\n")
		.map((line) => line.trim())
		.filter((line) => line.length > 0);
}

function formFromCopySet(copySet: CopySet): CopySetForm {
	return {
		angle: copySet.angle ?? "",
		hook: copySet.hook ?? "",
		subhook: copySet.subhook ?? "",
		uspText: (copySet.usp_set ?? []).join("\n"),
		cta: copySet.cta ?? "",
		platform: copySet.platform ?? "TIKTOK",
		language: copySet.language ?? "BM_MS",
		route_type: copySet.route_type ?? "DIRECT",
		formula_family: copySet.formula_family ?? "HSO",
	};
}

function statusToneClass(status: CopySetStatus): string {
	if (status === "COPY_APPROVED")
		return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
	if (status === "COPY_REJECTED")
		return "border-rose-500/30 bg-rose-500/10 text-rose-200";
	if (status === "COPY_REVIEW_REQUIRED")
		return "border-amber-500/30 bg-amber-500/10 text-amber-100";
	return "border-slate-600/40 bg-slate-800/60 text-slate-300";
}

function StatusBadge({ status }: { status: CopySetStatus }) {
	return (
		<span
			className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em] ${statusToneClass(status)}`}
		>
			{status}
		</span>
	);
}

export default function CopyStrategyStudioPage() {
	const [products, setProducts] = useState<Product[]>([]);
	const [productsError, setProductsError] = useState<string | null>(null);
	const [isLoadingProducts, setIsLoadingProducts] = useState(false);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);

	const [copySets, setCopySets] = useState<CopySet[]>([]);
	const [isLoadingCopySets, setIsLoadingCopySets] = useState(false);
	const [selected, setSelected] = useState<CopySet | null>(null);

	const [form, setForm] = useState<CopySetForm>(BLANK_FORM);
	const [approvePhrase, setApprovePhrase] = useState("");
	const [reviewerNote, setReviewerNote] = useState("");
	const [busy, setBusy] = useState(false);
	const [notice, setNotice] = useState<Notice>({
		tone: "idle",
		message: "Select a product to start a Copy Set.",
	});

	const setField = useCallback(
		<K extends keyof CopySetForm>(key: K, value: CopySetForm[K]) => {
			setForm((prev) => ({ ...prev, [key]: value }));
		},
		[],
	);

	useEffect(() => {
		setIsLoadingProducts(true);
		setProductsError(null);
		void fetchProductCatalog(500)
			.then((response) => setProducts(response.items ?? []))
			.catch((err: unknown) =>
				setProductsError(
					err instanceof Error ? err.message : "Failed to load product catalog",
				),
			)
			.finally(() => setIsLoadingProducts(false));
	}, []);

	const loadCopySets = useCallback(async (productId: string) => {
		setIsLoadingCopySets(true);
		try {
			const response = await listCopySetsForProduct(productId);
			setCopySets(response.items ?? []);
		} catch (err: unknown) {
			setNotice({
				tone: "error",
				message:
					err instanceof Error ? err.message : "Failed to load Copy Sets.",
			});
		} finally {
			setIsLoadingCopySets(false);
		}
	}, []);

	useEffect(() => {
		if (!selectedProduct) {
			setCopySets([]);
			setSelected(null);
			return;
		}
		setSelected(null);
		setForm(BLANK_FORM);
		void loadCopySets(selectedProduct.id);
	}, [selectedProduct, loadCopySets]);

	const selectCopySet = useCallback((copySet: CopySet) => {
		setSelected(copySet);
		setForm(formFromCopySet(copySet));
		setApprovePhrase("");
		setReviewerNote(copySet.reviewer_note ?? "");
		setNotice({
			tone: "info",
			message: `Loaded Copy Set ${copySet.copy_set_id} (${copySet.status}).`,
		});
	}, []);

	// Merge an updated Copy Set back into local state (list + selection).
	const applyUpdated = useCallback((copySet: CopySet) => {
		setCopySets((prev) => {
			const exists = prev.some((c) => c.copy_set_id === copySet.copy_set_id);
			return exists
				? prev.map((c) => (c.copy_set_id === copySet.copy_set_id ? copySet : c))
				: [copySet, ...prev];
		});
		setSelected(copySet);
		setForm(formFromCopySet(copySet));
	}, []);

	const runAction = useCallback(
		async (fn: () => Promise<void>) => {
			setBusy(true);
			try {
				await fn();
			} catch (err: unknown) {
				setNotice({
					tone: "error",
					message: err instanceof Error ? err.message : "Action failed.",
				});
			} finally {
				setBusy(false);
			}
		},
		[],
	);

	const handleGenerate = useCallback(() => {
		if (!selectedProduct) return;
		void runAction(async () => {
			const result = await generateCopySet({
				product_id: selectedProduct.id,
				// Explicit overrides are optional — send only non-empty fields so the
				// backend can resolve from landbank / copy-signal when a field is blank.
				angle: form.angle || undefined,
				hook: form.hook || undefined,
				subhook: form.subhook || undefined,
				usp_set: uspTextToArray(form.uspText),
				cta: form.cta || undefined,
				platform: form.platform || undefined,
				language: form.language || undefined,
				route_type: form.route_type || undefined,
				formula_family: form.formula_family || undefined,
			});
			applyUpdated(result.copy_set);
			setNotice({
				tone: result.created ? "success" : "warning",
				message: result.created
					? `Generated Copy Set ${result.copy_set.copy_set_id}.`
					: result.dedupe_match
						? "Dedupe match — returned the existing Copy Set for this exact combination (no duplicate created)."
						: "Returned existing Copy Set.",
			});
		});
	}, [selectedProduct, form, runAction, applyUpdated]);

	const handleSave = useCallback(() => {
		if (!selected) return;
		void runAction(async () => {
			const updated = await patchCopySet(selected.copy_set_id, {
				angle: form.angle,
				hook: form.hook,
				subhook: form.subhook,
				usp_set: uspTextToArray(form.uspText),
				cta: form.cta,
				platform: form.platform,
				language: form.language,
				route_type: form.route_type,
				formula_family: form.formula_family,
				reviewer_note: reviewerNote || undefined,
			});
			applyUpdated(updated);
			setNotice({
				tone: "info",
				message:
					"Saved. Editing a Copy Set resets any prior approval — re-approve after review.",
			});
		});
	}, [selected, form, reviewerNote, runAction, applyUpdated]);

	const handleRegenerate = useCallback(() => {
		if (!selected) return;
		void runAction(async () => {
			const updated = await regenerateCopySet(selected.copy_set_id, {
				angle: form.angle || undefined,
			});
			applyUpdated(updated);
			setNotice({
				tone: "info",
				message: "Regenerated copy in place. Prior approval was reset.",
			});
		});
	}, [selected, form.angle, runAction, applyUpdated]);

	const handleReject = useCallback(() => {
		if (!selected) return;
		if (!reviewerNote.trim()) {
			setNotice({ tone: "warning", message: "Add a reviewer note to reject." });
			return;
		}
		void runAction(async () => {
			const updated = await rejectCopySet(selected.copy_set_id, {
				reviewer_note: reviewerNote.trim(),
			});
			applyUpdated(updated);
			setNotice({ tone: "warning", message: "Copy Set rejected." });
		});
	}, [selected, reviewerNote, runAction, applyUpdated]);

	const canApprove = approvePhrase === COPY_SET_APPROVAL_PHRASE;

	const handleApprove = useCallback(() => {
		if (!selected || !canApprove) return;
		void runAction(async () => {
			const updated = await approveCopySet(selected.copy_set_id, {
				approval_phrase: approvePhrase,
				reviewer_note: reviewerNote || undefined,
			});
			applyUpdated(updated);
			setApprovePhrase("");
			setNotice({
				tone: "success",
				message: `Copy Set APPROVED (${updated.approved_at ?? "now"}).`,
			});
		});
	}, [selected, canApprove, approvePhrase, reviewerNote, runAction, applyUpdated]);

	const completeness = selected?.claim_review?.completeness;
	const safety = selected?.claim_review?.safety;
	const provenanceJson = useMemo(
		() =>
			selected
				? JSON.stringify(
						{ source: selected.source, provenance: selected.provenance },
						null,
						2,
					)
				: "",
		[selected],
	);

	return (
		<div className="flex h-full flex-col bg-slate-950 px-4 py-4 md:px-8 md:py-8">
			<div className="mb-6">
				<h2 className="text-xl font-bold tracking-tight text-white md:text-2xl">
					Copy Strategy Studio
				</h2>
				<p className="text-sm italic text-slate-400">
					Generate, review, edit, and approve a Copy Set before final prompt
					compilation. No Google Flow execution happens here.
				</p>
			</div>

			<div className="grid flex-1 min-h-0 gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
				{/* ── Left: product + existing copy sets ── */}
				<div className="space-y-4">
					<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
						<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
							Step 1 — Select Product
						</div>
						{productsError ? (
							<div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-200">
								{productsError}
							</div>
						) : null}
						<SearchableProductSelect
							products={products}
							selectedProduct={selectedProduct}
							onSelect={setSelectedProduct}
						/>
						{isLoadingProducts ? (
							<div className="mt-2 text-[11px] text-slate-500">
								Loading products…
							</div>
						) : null}
					</div>

					<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
						<div className="mb-3 flex items-center justify-between">
							<div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
								Copy Sets
							</div>
							{isLoadingCopySets ? (
								<Loader2 size={14} className="animate-spin text-slate-500" />
							) : (
								<span className="text-[10px] text-slate-600">
									{copySets.length}
								</span>
							)}
						</div>
						{!selectedProduct ? (
							<div className="text-[11px] text-slate-500">
								Select a product to list its Copy Sets.
							</div>
						) : copySets.length === 0 && !isLoadingCopySets ? (
							<div className="text-[11px] text-slate-500">
								No Copy Sets yet. Fill the form and press Generate.
							</div>
						) : (
							<div className="max-h-72 space-y-2 overflow-y-auto">
								{copySets.map((copySet) => (
									<button
										type="button"
										key={copySet.copy_set_id}
										onClick={() => selectCopySet(copySet)}
										className={`w-full rounded-xl border px-3 py-2 text-left transition-colors ${selected?.copy_set_id === copySet.copy_set_id ? "border-blue-500/40 bg-blue-500/10" : "border-slate-800 bg-slate-950/60 hover:border-slate-700"}`}
									>
										<div className="flex items-center justify-between gap-2">
											<span className="truncate text-xs font-semibold text-slate-200">
												{copySet.angle || copySet.hook || "(no angle/hook yet)"}
											</span>
											<StatusBadge status={copySet.status} />
										</div>
										<div className="mt-1 truncate text-[10px] text-slate-500">
											{copySet.platform} · {copySet.language} ·{" "}
											{copySet.route_type}
										</div>
									</button>
								))}
							</div>
						)}
					</div>
				</div>

				{/* ── Right: editor + review + actions ── */}
				<div className="min-h-0 space-y-4">
					<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
						<div className="mb-3 flex items-center justify-between">
							<div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
								Step 2 — Copy Set
							</div>
							{selected ? <StatusBadge status={selected.status} /> : null}
						</div>

						<div className="grid gap-3 md:grid-cols-2">
							<label className="space-y-1">
								<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Angle
								</span>
								<input
									value={form.angle}
									onChange={(e) => setField("angle", e.target.value)}
									placeholder="e.g. Nilai stok rumah"
									className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-100"
								/>
							</label>
							<label className="space-y-1">
								<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Hook
								</span>
								<input
									value={form.hook}
									onChange={(e) => setField("hook", e.target.value)}
									placeholder="Opening line that seizes attention"
									className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-100"
								/>
							</label>
							<label className="space-y-1 md:col-span-2">
								<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Subhook
								</span>
								<input
									value={form.subhook}
									onChange={(e) => setField("subhook", e.target.value)}
									placeholder="Supports the hook (optional)"
									className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-100"
								/>
							</label>
							<label className="space-y-1 md:col-span-2">
								<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									USP set (one per line)
								</span>
								<textarea
									value={form.uspText}
									onChange={(e) => setField("uspText", e.target.value)}
									rows={3}
									placeholder={"Jimat jangka panjang\nPraktikal untuk demo"}
									className="w-full resize-none rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-100"
								/>
							</label>
							<label className="space-y-1 md:col-span-2">
								<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									CTA
								</span>
								<input
									value={form.cta}
									onChange={(e) => setField("cta", e.target.value)}
									placeholder="Pilih variasi dan tambah ke cart."
									className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-100"
								/>
							</label>
							<label className="space-y-1">
								<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Platform
								</span>
								<input
									value={form.platform}
									onChange={(e) => setField("platform", e.target.value)}
									className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-100"
								/>
							</label>
							<label className="space-y-1">
								<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Language
								</span>
								<input
									value={form.language}
									onChange={(e) => setField("language", e.target.value)}
									className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-100"
								/>
							</label>
							<label className="space-y-1">
								<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Route type
								</span>
								<input
									value={form.route_type}
									onChange={(e) => setField("route_type", e.target.value)}
									placeholder="DIRECT / STEALTH / REVIEW_REQUIRED"
									className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-100"
								/>
							</label>
							<label className="space-y-1">
								<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Formula family
								</span>
								<input
									value={form.formula_family}
									onChange={(e) => setField("formula_family", e.target.value)}
									placeholder="HSO / PAS / AIDA…"
									className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-100"
								/>
							</label>
						</div>

						<div className="mt-4 flex flex-wrap gap-2">
							<button
								type="button"
								onClick={handleGenerate}
								disabled={!selectedProduct || busy}
								className="inline-flex items-center gap-2 rounded-lg border border-blue-500/40 bg-blue-500/15 px-3 py-2 text-xs font-semibold text-blue-100 hover:bg-blue-500/25 disabled:opacity-50"
							>
								<Sparkles size={14} /> Generate Copy Set
							</button>
							<button
								type="button"
								onClick={handleSave}
								disabled={!selected || busy}
								className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:opacity-50"
							>
								<Save size={14} /> Save / Edit
							</button>
							<button
								type="button"
								onClick={handleRegenerate}
								disabled={!selected || busy}
								className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:opacity-50"
							>
								<RefreshCw size={14} /> Regenerate
							</button>
							{busy ? (
								<span className="inline-flex items-center gap-2 text-[11px] text-slate-400">
									<Loader2 size={14} className="animate-spin" /> Working…
								</span>
							) : null}
						</div>
					</div>

					{/* Notice */}
					<div
						className={`rounded-2xl border px-4 py-3 text-xs ${notice.tone === "error" ? "border-rose-500/40 bg-rose-500/10 text-rose-200" : notice.tone === "success" ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200" : notice.tone === "warning" ? "border-amber-500/40 bg-amber-500/10 text-amber-200" : notice.tone === "info" ? "border-blue-500/40 bg-blue-500/10 text-blue-200" : "border-slate-800 bg-slate-900/40 text-slate-400"}`}
					>
						{notice.message}
					</div>

					{/* Review + actions (only when a Copy Set is selected) */}
					{selected ? (
						<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
							<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
								Step 3 — Review & Approve
							</div>

							<div className="grid gap-3 md:grid-cols-2">
								<div className="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-3">
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
										Completeness
									</div>
									<div className="mt-1 text-xs text-slate-200">
										{completeness
											? completeness.complete
												? "Complete"
												: `Missing: ${completeness.missing_fields.join(", ") || "—"}`
											: "—"}
									</div>
								</div>
								<div className="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-3">
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
										Claim / Risk Safety
									</div>
									<div
										className={`mt-1 text-xs ${safety && !safety.safe ? "text-rose-200" : "text-slate-200"}`}
									>
										{safety
											? safety.safe
												? "Safe"
												: `Violations: ${safety.violations.join(", ") || "—"}`
											: "—"}
									</div>
								</div>
							</div>

							{selected.approved_at ? (
								<div className="mt-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-[11px] text-emerald-200">
									Approved at {selected.approved_at}
									{selected.approved_by ? ` by ${selected.approved_by}` : ""}.
								</div>
							) : null}

							<div className="mt-4 space-y-3">
								<label className="block space-y-1">
									<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
										Reviewer note (used for reject / approve)
									</span>
									<input
										value={reviewerNote}
										onChange={(e) => setReviewerNote(e.target.value)}
										placeholder="Optional note; required to reject."
										className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-100"
									/>
								</label>

								<div className="flex flex-wrap items-end gap-2">
									<label className="space-y-1">
										<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
											Type {COPY_SET_APPROVAL_PHRASE} to approve
										</span>
										<input
											value={approvePhrase}
											onChange={(e) => setApprovePhrase(e.target.value)}
											placeholder={COPY_SET_APPROVAL_PHRASE}
											className="w-64 rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-100"
										/>
									</label>
									<button
										type="button"
										onClick={handleApprove}
										disabled={!canApprove || busy}
										className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-xs font-semibold text-emerald-100 hover:bg-emerald-500/25 disabled:opacity-50"
									>
										<Check size={14} /> Approve Copy Set
									</button>
									<button
										type="button"
										onClick={handleReject}
										disabled={busy}
										className="inline-flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50"
									>
										<Ban size={14} /> Reject
									</button>
								</div>
								<p className="text-[11px] text-slate-500">
									Approval fails closed on unsafe or incomplete copy. Editing or
									regenerating an approved Copy Set resets its approval.
								</p>
							</div>

							{/* Operator-safe diagnostics — NOT part of any engine-facing prompt. */}
							<details className="mt-4">
								<summary className="cursor-pointer text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Diagnostics (source / provenance)
								</summary>
								<pre className="mt-2 overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/70 p-3 text-[10px] text-slate-400">
									{provenanceJson}
								</pre>
							</details>
						</div>
					) : null}
				</div>
			</div>
		</div>
	);
}
