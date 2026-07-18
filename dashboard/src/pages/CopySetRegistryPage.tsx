import { PenLine } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
	approveCopySet,
	cloneCopySetToProduct,
	type CopyGroundingSummary,
	deleteCopySet,
	type CopyFormula,
	fetchCopyFormulas,
	fetchCopyGrounding,
	generateCopySet,
	generateCopySetBatch,
	listCopySetsForProduct,
	patchCopySet,
	rejectCopySet,
	runSimilarityBackfill,
} from "../api/copySets";
import { fetchProductCatalog, prepareProductForCopywriting } from "../api/products";
import {
	Badge,
	type BadgeTone,
	ConfirmActionModal,
	DataTable,
	type DataTableColumn,
	FormField,
	HelperText,
	Section,
} from "../components/ui";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { CopySet, CopySetStatus, Product } from "../types";

const GENERATE_COUNT = 5;
const DELETE_PHRASE = "DELETE";
// Owner decision 2026-07-19: one script reused (with different visuals) at
// most 15x before rotation retires it. Display-only here; the cap itself is
// enforced server-side by copy_rotation_service.
const REUSE_CAP = 15;

const STATUS_TONE: Record<CopySetStatus, BadgeTone> = {
	DRAFT_COPY: "neutral",
	COPY_REVIEW_REQUIRED: "warn",
	COPY_APPROVED: "success",
	COPY_REJECTED: "danger",
};
const STATUS_LABEL: Record<CopySetStatus, string> = {
	DRAFT_COPY: "Draft",
	COPY_REVIEW_REQUIRED: "Review required",
	COPY_APPROVED: "Approved",
	COPY_REJECTED: "Rejected",
};

// ---- Edit modal ---------------------------------------------------------

function EditCopySetModal({
	set,
	busy,
	onSave,
	onCancel,
}: {
	set: CopySet;
	busy: boolean;
	onSave: (patch: {
		angle: string;
		hook: string;
		subhook: string;
		usp_set: string[];
		cta: string;
	}) => void;
	onCancel: () => void;
}) {
	const [angle, setAngle] = useState(set.angle);
	const [hook, setHook] = useState(set.hook);
	const [subhook, setSubhook] = useState(set.subhook);
	const [usp1, setUsp1] = useState(set.usp_set[0] ?? "");
	const [usp2, setUsp2] = useState(set.usp_set[1] ?? "");
	const [usp3, setUsp3] = useState(set.usp_set[2] ?? "");
	const [cta, setCta] = useState(set.cta);

	const inputCls =
		"mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200";

	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
			<div
				className="w-full max-w-2xl rounded-2xl border border-slate-700 bg-slate-950 p-5"
				data-testid="edit-copy-set-modal"
			>
				<h3 className="text-sm font-bold text-slate-100">Edit copywriting set</h3>
				<p className="mt-1 text-xs text-slate-400">
					Editing re-derives status and clears any previous approval.
				</p>
				<div className="mt-4 grid gap-3 md:grid-cols-2">
					<FormField label="Angle">
						<input className={inputCls} value={angle} onChange={(e) => setAngle(e.target.value)} />
					</FormField>
					<FormField label="Hook">
						<input className={inputCls} value={hook} onChange={(e) => setHook(e.target.value)} />
					</FormField>
					<FormField label="Subhook" className="md:col-span-2">
						<input className={inputCls} value={subhook} onChange={(e) => setSubhook(e.target.value)} />
					</FormField>
					<FormField label="USP 1">
						<input className={inputCls} value={usp1} onChange={(e) => setUsp1(e.target.value)} />
					</FormField>
					<FormField label="USP 2">
						<input className={inputCls} value={usp2} onChange={(e) => setUsp2(e.target.value)} />
					</FormField>
					<FormField label="USP 3">
						<input className={inputCls} value={usp3} onChange={(e) => setUsp3(e.target.value)} />
					</FormField>
					<FormField label="CTA">
						<input className={inputCls} value={cta} onChange={(e) => setCta(e.target.value)} />
					</FormField>
				</div>
				<div className="mt-5 flex justify-end gap-2">
					<button
						type="button"
						onClick={onCancel}
						disabled={busy}
						className="rounded-lg border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300"
					>
						Cancel
					</button>
					<button
						type="button"
						data-testid="save-copy-set-edit"
						disabled={busy}
						onClick={() =>
							onSave({
								angle,
								hook,
								subhook,
								usp_set: [usp1, usp2, usp3].map((u) => u.trim()).filter(Boolean),
								cta,
							})
						}
						className="rounded-lg border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40"
					>
						{busy ? "Saving…" : "Save changes"}
					</button>
				</div>
			</div>
		</div>
	);
}

// ---- Clone modal --------------------------------------------------------
// Owner rule: similar products (e.g. two vanilla car perfumes) share scripts
// via EXPLICIT clone only — the clone re-enters review against the TARGET
// product and starts with a fresh reuse budget.

function CloneCopySetModal({
	set,
	products,
	busy,
	onClone,
	onCancel,
}: {
	set: CopySet;
	products: Product[];
	busy: boolean;
	onClone: (target: Product) => void;
	onCancel: () => void;
}) {
	const [target, setTarget] = useState<Product | null>(null);
	const candidates = useMemo(
		() => products.filter((p) => p.id !== set.product_id),
		[products, set.product_id],
	);
	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
			<div
				className="w-full max-w-xl rounded-2xl border border-slate-700 bg-slate-950 p-5"
				data-testid="clone-copy-set-modal"
			>
				<h3 className="text-sm font-bold text-slate-100">
					Clone skrip ke produk serupa
				</h3>
				<p className="mt-1 text-xs text-slate-400">
					Hook: “{set.hook || set.angle}”. Clone masuk semula sebagai{" "}
					<span className="font-semibold text-amber-200">Review required</span>{" "}
					dengan claim-safety scan terhadap produk sasaran — tidak pernah
					auto-approve. Usage bermula 0 (bajet reuse baharu).
				</p>
				<div className="mt-4">
					<SearchableProductSelect
						products={candidates}
						selectedProduct={target}
						onSelect={setTarget}
					/>
				</div>
				<div className="mt-5 flex justify-end gap-2">
					<button
						type="button"
						onClick={onCancel}
						disabled={busy}
						className="rounded-lg border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300"
					>
						Cancel
					</button>
					<button
						type="button"
						data-testid="confirm-clone-copy-set"
						disabled={busy || !target}
						onClick={() => target && onClone(target)}
						className="rounded-lg border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40"
					>
						{busy ? "Cloning…" : "Clone ke produk ini"}
					</button>
				</div>
			</div>
		</div>
	);
}

// ---- Page ---------------------------------------------------------------

export default function CopySetRegistryPage() {
	const [searchParams, setSearchParams] = useSearchParams();
	const [products, setProducts] = useState<Product[]>([]);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [sets, setSets] = useState<CopySet[]>([]);
	const [loading, setLoading] = useState(false);
	const [generating, setGenerating] = useState(false);
	const [busyId, setBusyId] = useState<string | null>(null);
	const [error, setError] = useState("");
	const [success, setSuccess] = useState("");
	const [editTarget, setEditTarget] = useState<CopySet | null>(null);
	const [deleteTarget, setDeleteTarget] = useState<CopySet | null>(null);
	const [cloneTarget, setCloneTarget] = useState<CopySet | null>(null);
	const [scanning, setScanning] = useState(false);
	const [bulkApproving, setBulkApproving] = useState(false);
	const [bulkApproveOpen, setBulkApproveOpen] = useState(false);
	const [grounding, setGrounding] = useState<CopyGroundingSummary | null>(null);
	const [formulas, setFormulas] = useState<CopyFormula[]>([]);
	const [formulaId, setFormulaId] = useState("");
	const [preparing, setPreparing] = useState(false);
	useEffect(() => {
		void fetchCopyFormulas()
			.then((r) => setFormulas(r.formulas))
			.catch(() => setFormulas([]));
	}, []);

	useEffect(() => {
		void fetchProductCatalog(500)
			.then((r) => setProducts(r.items ?? []))
			.catch((e: Error) => setError(e.message || "Gagal muat katalog produk."));
	}, []);

	useEffect(() => {
		const pid = searchParams.get("product_id");
		if (!pid || products.length === 0) return;
		const match = products.find((p) => p.id === pid);
		if (match && match.id !== selectedProduct?.id) setSelectedProduct(match);
	}, [searchParams, products, selectedProduct?.id]);

	const loadSets = useCallback(async (productId: string) => {
		setLoading(true);
		setError("");
		try {
			const [res, g] = await Promise.all([
				listCopySetsForProduct(productId),
				fetchCopyGrounding(productId).catch(() => null),
			]);
			setSets(res.items ?? []);
			setGrounding(g);
		} catch (e) {
			setSets([]);
			setError(e instanceof Error ? e.message : "Gagal muat copywriting set.");
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		if (!selectedProduct) {
			setSets([]);
			return;
		}
		const cur = searchParams.get("product_id");
		if (cur !== selectedProduct.id) {
			setSearchParams({ product_id: selectedProduct.id }, { replace: true });
		}
		setSuccess("");
		void loadSets(selectedProduct.id);
		// eslint-disable-next-line react-hooks/exhaustive-deps -- reload only when product id changes
	}, [selectedProduct?.id]);

	// AI generation is EXPLICIT-only (button click). Never fired on product select.
	const handleGenerate = async () => {
		if (!selectedProduct || generating) return;
		setGenerating(true);
		setError("");
		setSuccess("");
		try {
			const res = await generateCopySetBatch({
				product_id: selectedProduct.id,
				requested_count: GENERATE_COUNT,
				formula_family: formulaId || undefined,
			});
			setSuccess(
				`${res.created_count} set baru dijana${res.deduped_count ? ` · ${res.deduped_count} duplikat ditapis` : ""}. Semak & approve sebelum guna.`,
			);
			await loadSets(selectedProduct.id);
		} catch (e) {
			const msg = e instanceof Error ? e.message : "Gagal jana copywriting set.";
			setError(
				/409|NOT_CONFIGURED/i.test(msg)
					? "Lane AI (DeepSeek text_assist) belum dikonfigur. Sila set di Cockpit Settings / AI Providers dahulu."
					: /COPY_GROUNDING_INSUFFICIENT/i.test(msg)
						? "Produk ini belum ada Product Knowledge + Customer Avatar diluluskan. Tekan 'Prepare Product for Copywriting' dahulu, atau approve snapshot di Products > Intelligence."
						: msg,
			);
		} finally {
			setGenerating(false);
		}
	};

	const handleAddDeterministic = async () => {
		if (!selectedProduct || generating) return;
		setGenerating(true);
		setError("");
		setSuccess("");
		try {
			await generateCopySet({ product_id: selectedProduct.id });
			setSuccess("1 set deterministik (tanpa AI) ditambah.");
			await loadSets(selectedProduct.id);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Gagal tambah set.");
		} finally {
			setGenerating(false);
		}
	};

	const handlePrepare = async () => {
		if (!selectedProduct || preparing) return;
		setPreparing(true);
		setError("");
		setSuccess("");
		try {
			const r = await prepareProductForCopywriting(selectedProduct.id);
			setSuccess(
				`AI sedia draf Product Knowledge + Customer Avatar (formula: ${r.recommended_formula}). Semak & approve di Products > Intelligence sebelum jana copy grounded.`,
			);
			void loadSets(selectedProduct.id);
		} catch (e) {
			const msg = e instanceof Error ? e.message : "Gagal sediakan produk.";
			setError(
				/503|NOT_CONFIGURED/i.test(msg)
					? "Lane AI (DeepSeek text_assist) belum dikonfigur."
					: msg,
			);
		} finally {
			setPreparing(false);
		}
	};

	const withBusy = async (id: string, fn: () => Promise<unknown>) => {
		setBusyId(id);
		setError("");
		try {
			await fn();
			if (selectedProduct) await loadSets(selectedProduct.id);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Tindakan gagal.");
		} finally {
			setBusyId(null);
		}
	};

	const handleApprove = (s: CopySet) =>
		void withBusy(s.copy_set_id, async () => {
			await approveCopySet(s.copy_set_id, { approved_by: "operator" });
			setSuccess("Set diluluskan (APPROVED).");
		});

	const handleReject = (s: CopySet) => {
		const note = window.prompt("Sebab reject (reviewer note):", "Not suitable");
		if (note == null || !note.trim()) return;
		void withBusy(s.copy_set_id, async () => {
			await rejectCopySet(s.copy_set_id, note.trim());
			setSuccess("Set direject.");
		});
	};

	const handleSaveEdit = (patch: {
		angle: string;
		hook: string;
		subhook: string;
		usp_set: string[];
		cta: string;
	}) => {
		if (!editTarget) return;
		const target = editTarget;
		void withBusy(target.copy_set_id, async () => {
			await patchCopySet(target.copy_set_id, patch);
			setSuccess("Set dikemas kini.");
			setEditTarget(null);
		});
	};

	const confirmDelete = () => {
		if (!deleteTarget) return;
		const target = deleteTarget;
		void withBusy(target.copy_set_id, async () => {
			await deleteCopySet(target.copy_set_id);
			setSuccess("Set dipadam.");
			setDeleteTarget(null);
		});
	};

	const handleClone = (targetProduct: Product) => {
		if (!cloneTarget) return;
		const source = cloneTarget;
		void withBusy(source.copy_set_id, async () => {
			const res = await cloneCopySetToProduct(source.copy_set_id, targetProduct.id);
			setSuccess(
				res.created
					? `Skrip di-clone ke "${targetProduct.product_display_name ?? targetProduct.id}" — masuk semula review di produk itu.`
					: "Skrip serupa sudah wujud di produk sasaran (dedupe match) — tiada clone baharu.",
			);
			setCloneTarget(null);
		});
	};

	// Near-dup backfill scan: dry-run first (report), operator confirms apply.
	const handleScan = async () => {
		if (!selectedProduct || scanning) return;
		setScanning(true);
		setError("");
		setSuccess("");
		try {
			const dry = await runSimilarityBackfill({ product_id: selectedProduct.id });
			if (dry.scanned === 0) {
				setSuccess("Tiada skrip untuk discan.");
				return;
			}
			const wantApply = window.confirm(
				`Scan (dry-run): ${dry.scanned} skrip, ${dry.flagged} near-dup dikesan, ${dry.items.filter((i) => i.changed).length} baris akan dikemas kini.\n\nTulis metadata similarity/uniqueness ke library? (Status TIDAK disentuh — anda tetap yang approve/reject.)`,
			);
			if (!wantApply) {
				setSuccess(
					`Dry-run sahaja: ${dry.scanned} skrip discan, ${dry.flagged} near-dup dikesan. Tiada apa-apa ditulis.`,
				);
				return;
			}
			const applied = await runSimilarityBackfill({
				product_id: selectedProduct.id,
				apply: true,
			});
			setSuccess(
				`Scan siap: ${applied.scanned} skrip, ${applied.flagged} near-dup, ${applied.updated} baris dikemas kini.`,
			);
			await loadSets(selectedProduct.id);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Scan gagal.");
		} finally {
			setScanning(false);
		}
	};

	const reviewRequired = sets.filter((s) => s.status === "COPY_REVIEW_REQUIRED");

	// Bulk approve = approve every review-required set for this product,
	// serially through the SAME approval endpoint (phrase + gates intact).
	const confirmBulkApprove = async () => {
		if (bulkApproving || reviewRequired.length === 0) {
			setBulkApproveOpen(false);
			return;
		}
		setBulkApproving(true);
		setError("");
		let ok = 0;
		const failures: string[] = [];
		for (const s of reviewRequired) {
			try {
				await approveCopySet(s.copy_set_id, { approved_by: "operator" });
				ok += 1;
			} catch (e) {
				failures.push(
					`${s.hook || s.copy_set_id}: ${e instanceof Error ? e.message : "gagal"}`,
				);
			}
		}
		setBulkApproving(false);
		setBulkApproveOpen(false);
		if (failures.length) {
			setError(
				`${failures.length} set gagal approve (gate menolak): ${failures.slice(0, 3).join(" · ")}${failures.length > 3 ? " · …" : ""}`,
			);
		}
		if (ok) setSuccess(`${ok} set diluluskan (bulk).`);
		if (selectedProduct) await loadSets(selectedProduct.id);
	};

	const columns: DataTableColumn<CopySet>[] = useMemo(
		() => [
			{
				key: "status",
				header: "Status",
				sortValue: (r) => r.status,
				render: (r) => (
					<Badge tone={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status]}</Badge>
				),
			},
			{
				key: "angle",
				header: "Angle",
				sortValue: (r) => r.angle,
				render: (r) => <span className="text-slate-200">{r.angle || "—"}</span>,
			},
			{
				key: "hook",
				header: "Hook",
				render: (r) => (
					<span className="text-slate-100">{r.hook || "—"}</span>
				),
			},
			{
				key: "subhook",
				header: "Subhook",
				render: (r) => (
					<span className="text-slate-400">{r.subhook || "—"}</span>
				),
			},
			{
				key: "usp",
				header: "USPs",
				render: (r) => (
					<span className="text-slate-400">
						{r.usp_set.filter(Boolean).join(" · ") || "—"}
					</span>
				),
			},
			{
				key: "cta",
				header: "CTA",
				render: (r) => <span className="text-slate-300">{r.cta || "—"}</span>,
			},
			{
				key: "library",
				header: "Library",
				sortValue: (r) => r.usage_count ?? 0,
				render: (r) => {
					const usage = r.usage_count ?? 0;
					const capped = usage >= REUSE_CAP;
					const uniq = r.uniqueness_score;
					return (
						<div
							className="space-y-0.5 text-[10px]"
							data-testid={`library-cell-${r.copy_set_id}`}
						>
							<div
								className={capped ? "font-bold text-rose-300" : "text-slate-300"}
								title={
									r.last_used_at
										? `Kali terakhir dipakai: ${r.last_used_at}${r.used_in_modes.length ? ` · mod: ${r.used_in_modes.join(", ")}` : ""}`
										: "Belum pernah dipakai"
								}
							>
								Guna {usage}/{REUSE_CAP}
								{capped ? " · RETIRED" : ""}
							</div>
							{r.similar_to_copy_set_id ? (
								<div
									className="font-bold text-amber-300"
									title={`Hampir sama dengan set ${r.similar_to_copy_set_id}`}
								>
									NEAR-DUP{" "}
									{r.similarity_score != null
										? `${Math.round(r.similarity_score * 100)}%`
										: ""}
								</div>
							) : null}
							{uniq != null ? (
								<div className={uniq < 0.4 ? "text-amber-300" : "text-slate-500"}>
									uniq {Math.round(uniq * 100)}%
								</div>
							) : null}
						</div>
					);
				},
			},
			{
				key: "formula",
				header: "Formula / QA",
				sortValue: (r) => r.claim_review?.formula_id || r.formula_family,
				render: (r) => {
					const cr = r.claim_review ?? {};
					const fid = cr.formula_id || r.formula_family;
					const val = cr.formula_validation;
					const isDraft =
						!!cr.formula_definition_status &&
						cr.formula_definition_status !== "CANONICAL";
					const issues = val?.violations?.length ?? 0;
					const clarity = cr.sales_clarity?.clarity_score;
					const slots = val?.slot_coverage
						? Object.entries(val.slot_coverage)
								.map(([s, ok]) => `${s}:${ok ? "ok" : "MISSING"}`)
								.join("  ")
						: "";
					const breakdown = cr.formula_breakdown
						? Object.entries(cr.formula_breakdown)
								.map(([s, t]) => `${s}: ${t}`)
								.join("\n")
						: "";
					return (
						<div
							className="text-[10px]"
							data-testid={`formula-cell-${r.copy_set_id}`}
							title={[slots, breakdown].filter(Boolean).join("\n")}
						>
							<span className="font-bold uppercase text-slate-200">{fid}</span>
							{r.formula_family && r.formula_family !== fid ? (
								<span className="text-slate-500"> → {r.formula_family}</span>
							) : null}
							{isDraft ? <span className="text-amber-300"> (draft)</span> : null}
							<div className={issues ? "text-amber-300" : "text-emerald-300"}>
								{val ? (issues ? `⚠ ${issues} issue(s)` : "✓ formula ok") : "—"}
								{clarity != null ? ` · clarity ${clarity}` : ""}
							</div>
						</div>
					);
				},
			},
			{
				key: "source",
				header: "Source",
				sortValue: (r) => r.source,
				render: (r) => (
					<span className="text-[10px] uppercase text-slate-500">{r.source || "—"}</span>
				),
			},
		],
		[],
	);

	const filters = useMemo(
		() => [
			{
				key: "status",
				label: "Status",
				value: (r: CopySet) => r.status,
				options: [
					{ value: "COPY_APPROVED", label: "Approved" },
					{ value: "COPY_REVIEW_REQUIRED", label: "Review required" },
					{ value: "DRAFT_COPY", label: "Draft" },
					{ value: "COPY_REJECTED", label: "Rejected" },
				],
			},
		],
		[],
	);

	const rowActions = (r: CopySet) => {
		const busy = busyId === r.copy_set_id;
		return (
			<div className="flex flex-wrap justify-end gap-1.5">
				{r.status !== "COPY_APPROVED" && r.status !== "COPY_REJECTED" ? (
					<button
						type="button"
						data-testid={`approve-${r.copy_set_id}`}
						disabled={busy}
						onClick={() => handleApprove(r)}
						className="rounded border border-emerald-500/40 px-2 py-1 text-[10px] font-bold uppercase text-emerald-200 disabled:opacity-40"
					>
						Approve
					</button>
				) : null}
				{r.status !== "COPY_REJECTED" ? (
					<button
						type="button"
						data-testid={`reject-${r.copy_set_id}`}
						disabled={busy}
						onClick={() => handleReject(r)}
						className="rounded border border-amber-500/40 px-2 py-1 text-[10px] font-bold uppercase text-amber-200 disabled:opacity-40"
					>
						Reject
					</button>
				) : null}
				{r.status === "COPY_APPROVED" ? (
					<button
						type="button"
						data-testid={`clone-${r.copy_set_id}`}
						disabled={busy}
						onClick={() => setCloneTarget(r)}
						title="Kongsi skrip dengan produk serupa (masuk semula review di sana)"
						className="rounded border border-blue-500/40 px-2 py-1 text-[10px] font-bold uppercase text-blue-200 disabled:opacity-40"
					>
						Clone
					</button>
				) : null}
				<button
					type="button"
					data-testid={`edit-${r.copy_set_id}`}
					disabled={busy}
					onClick={() => setEditTarget(r)}
					className="rounded border border-slate-600 px-2 py-1 text-[10px] font-bold uppercase text-slate-200 disabled:opacity-40"
				>
					Edit
				</button>
				<button
					type="button"
					data-testid={`delete-${r.copy_set_id}`}
					disabled={busy}
					onClick={() => setDeleteTarget(r)}
					className="rounded border border-rose-500/40 px-2 py-1 text-[10px] font-bold uppercase text-rose-200 disabled:opacity-40"
				>
					Delete
				</button>
			</div>
		);
	};

	const approvedCount = sets.filter((s) => s.status === "COPY_APPROVED").length;

	return (
		<div
			className="mx-auto max-w-6xl space-y-6 p-4 md:p-8"
			data-testid="copy-set-registry-page"
		>
			<header>
				<div className="flex items-center gap-2 text-blue-300">
					<PenLine size={20} />
					<span className="text-[10px] font-bold uppercase tracking-[0.2em]">
						Creative
					</span>
				</div>
				<h1 className="mt-1 text-2xl font-bold text-slate-100">
					Copywriting Set Registry
				</h1>
				<p className="mt-2 max-w-3xl text-sm text-slate-400">
					Satu database copywriting set per produk (angle → hook → subhook → USP →
					CTA). Tekan Generate, AI (DeepSeek) isi set. Approved set dipakai oleh
					Poster Builder dan video generation (T2V/F2V/Hybrid/I2V). Setiap baris =
					satu set MAPPING lengkap.
				</p>
			</header>

			{error ? (
				<p
					className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100"
					data-testid="copy-registry-error"
				>
					{error}
				</p>
			) : null}
			{success ? (
				<p
					className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100"
					data-testid="copy-registry-success"
				>
					{success}
				</p>
			) : null}

			<Section title="Product" helper="Pilih produk untuk urus copywriting set-nya.">
				<div className="max-w-xl">
					<SearchableProductSelect
						products={products}
						selectedProduct={selectedProduct}
						onSelect={setSelectedProduct}
					/>
				</div>
			</Section>

			{selectedProduct ? (
				<>
					{grounding ? (
						<Section
							title="Copy grounding"
							helper="Adakah copy dijana berdasarkan product knowledge + customer avatar sebenar?"
							action={
								<Badge
									tone={
										grounding.source === "APPROVED_SNAPSHOT"
											? "success"
											: grounding.source === "FRAMEWORK_FAMILY"
												? "info"
												: "danger"
									}
								>
									{grounding.source === "APPROVED_SNAPSHOT"
										? "Grounded · approved snapshot"
										: grounding.source === "FRAMEWORK_FAMILY"
											? "Grounded · BOSMAX framework"
											: "Ungrounded · generic"}
								</Badge>
							}
						>
							<div
								data-testid="copy-grounding-banner"
								className="space-y-2 text-xs text-slate-300"
							>
								<p>
									<span className="text-slate-500">Family: </span>
									{grounding.family || "—"}
									{grounding.is_stealth ? (
										<span className="ml-2 rounded bg-amber-600/20 px-1.5 py-0.5 text-[9px] font-bold uppercase text-amber-200">
											STEALTH
										</span>
									) : null}
									<span className="ml-2 text-slate-500">· route </span>
									{grounding.effective_route}
									<span className="ml-2 text-slate-500">· claim </span>
									{grounding.claim_guardrails.claim_gate || "—"}
								</p>
								{grounding.buyer_persona.audience ? (
									<p>
										<span className="text-slate-500">Avatar: </span>
										{grounding.buyer_persona.audience}
									</p>
								) : null}
								{grounding.angle_strategies.length ? (
									<div className="flex flex-wrap items-center gap-1.5">
										<span className="text-slate-500">Angle strategies:</span>
										{grounding.angle_strategies.map((a) => (
											<span
												key={a}
												className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-300"
											>
												{a}
											</span>
										))}
									</div>
								) : null}
								{grounding.source !== "APPROVED_SNAPSHOT" ? (
									<HelperText tone="warn">
										Grounded pada peringkat framework family. Untuk copy paling
										tepat (benefit / USP / persona sebenar), author satu Product
										Knowledge snapshot untuk produk ini.
										{grounding.missing.length
											? ` Kurang: ${grounding.missing.join("; ")}.`
											: ""}
									</HelperText>
								) : null}
							</div>
						</Section>
					) : null}

					<Section
						title="Generate copywriting sets"
						helper={`AI menjana ${GENERATE_COUNT} set setiap tekan (max ${GENERATE_COUNT} demi kualiti). Tekan lagi untuk tambah. Set baru bertaraf "Review required" — approve sebelum guna.`}
						action={
							<div className="flex flex-wrap items-center gap-2">
								<select
									data-testid="formula-picker"
									value={formulaId}
									onChange={(e) => setFormulaId(e.target.value)}
									title="Formula for generation (empty = system recommends)"
									className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200"
								>
									<option value="">Formula: auto (recommended)</option>
									{formulas.map((f) => (
										<option key={f.formula_id} value={f.formula_id}>
											{f.display_name}
											{f.definition_status !== "CANONICAL" ? " (draft)" : ""}
										</option>
									))}
								</select>
								<button
									type="button"
									data-testid="generate-copy-sets"
									disabled={generating}
									onClick={handleGenerate}
									className="rounded-xl border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40"
								>
									{generating ? "Generating…" : `Generate ${GENERATE_COUNT} sets (AI)`}
								</button>
								<button
									type="button"
									data-testid="add-deterministic-copy-set"
									disabled={generating}
									onClick={handleAddDeterministic}
									className="rounded-xl border border-slate-700 px-4 py-2 text-xs font-bold uppercase text-slate-300 disabled:opacity-40"
								>
									Add 1 (no AI)
								</button>
								<button
									type="button"
									data-testid="prepare-product-copywriting"
									disabled={preparing}
									onClick={handlePrepare}
									title="Draft Product Knowledge + Customer Avatar + formula via DeepSeek. Review & approve in Products > Intelligence."
									className="rounded-xl border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40"
								>
									{preparing ? "Preparing…" : "Prepare Product for Copywriting"}
								</button>
							</div>
						}
					>
						<HelperText tone="warn">
							Generate menggunakan token DeepSeek — hanya berjalan bila anda tekan
							butang, tidak automatik. {approvedCount} set diluluskan setakat ini.
						</HelperText>
					</Section>

					<Section
						title="Copywriting sets"
						helper="Edit / Approve / Reject / Delete. Approved set auto dipakai builder & video. Kolum Library: guna x/15 (rotation cap) + flag NEAR-DUP."
						action={
							<div className="flex flex-wrap items-center gap-2">
								<button
									type="button"
									data-testid="scan-near-dup"
									disabled={scanning || loading || sets.length === 0}
									onClick={() => void handleScan()}
									title="Kira semula metadata near-dup + uniqueness untuk semua skrip produk ini (dry-run dulu, confirm sebelum tulis). Status tidak disentuh."
									className="rounded-xl border border-amber-500/40 px-4 py-2 text-xs font-bold uppercase text-amber-200 disabled:opacity-40"
								>
									{scanning ? "Scanning…" : "Scan Near-Dup"}
								</button>
								<button
									type="button"
									data-testid="bulk-approve"
									disabled={bulkApproving || loading || reviewRequired.length === 0}
									onClick={() => setBulkApproveOpen(true)}
									className="rounded-xl border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40"
								>
									{bulkApproving
										? "Approving…"
										: `Approve semua review (${reviewRequired.length})`}
								</button>
							</div>
						}
					>
						{loading ? (
							<p className="text-sm text-slate-400">Memuatkan…</p>
						) : (
							<DataTable<CopySet>
								rows={sets}
								columns={columns}
								getRowId={(r) => r.copy_set_id}
								pageSize={25}
								searchText={(r) =>
									`${r.angle} ${r.hook} ${r.subhook} ${r.usp_set.join(" ")} ${r.cta}`
								}
								searchPlaceholder="Cari angle / hook / CTA…"
								filters={filters}
								initialSort={{ key: "status", dir: "asc" }}
								rowActions={rowActions}
								emptyLabel="Belum ada copywriting set. Tekan Generate untuk mula."
								minWidthClassName="min-w-[900px]"
							/>
						)}
					</Section>
				</>
			) : (
				<Section title="Copywriting sets">
					<p className="text-sm text-slate-500">
						Pilih produk dahulu untuk lihat & jana copywriting set.
					</p>
				</Section>
			)}

			{editTarget ? (
				<EditCopySetModal
					set={editTarget}
					busy={busyId === editTarget.copy_set_id}
					onSave={handleSaveEdit}
					onCancel={() => setEditTarget(null)}
				/>
			) : null}

			{cloneTarget ? (
				<CloneCopySetModal
					set={cloneTarget}
					products={products}
					busy={busyId === cloneTarget.copy_set_id}
					onClone={handleClone}
					onCancel={() => setCloneTarget(null)}
				/>
			) : null}

			<ConfirmActionModal
				open={bulkApproveOpen}
				title={`Approve ${reviewRequired.length} set sekali gus?`}
				body="Setiap set melalui endpoint approval yang SAMA (gate formula/claim kekal berkuat kuasa — set yang ditolak gate akan dilaporkan gagal). Approved set terus masuk rotation Script Library."
				confirmLabel={`Approve ${reviewRequired.length} sets`}
				busy={bulkApproving}
				onConfirm={() => void confirmBulkApprove()}
				onCancel={() => setBulkApproveOpen(false)}
			/>

			<ConfirmActionModal
				open={!!deleteTarget}
				tone="danger"
				title="Padam copywriting set?"
				body={
					deleteTarget
						? `Set "${deleteTarget.angle || deleteTarget.hook || deleteTarget.copy_set_id}" akan dipadam kekal. Guna Reject jika hanya mahu tandakan tidak sesuai.`
						: ""
				}
				requiredPhrase={DELETE_PHRASE}
				confirmLabel="Delete permanently"
				busy={!!deleteTarget && busyId === deleteTarget.copy_set_id}
				onConfirm={confirmDelete}
				onCancel={() => setDeleteTarget(null)}
			/>
		</div>
	);
}
