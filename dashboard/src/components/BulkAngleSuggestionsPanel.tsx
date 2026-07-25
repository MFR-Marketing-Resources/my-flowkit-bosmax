import { useCallback, useEffect, useMemo, useState } from "react";
import {
	addAngles,
	bulkSuggestAngles,
	type EligibleProduct,
	fetchEligibleProducts,
} from "../api/copyComponents";
import { Badge, ConfirmActionModal, Section } from "./ui";

const CHUNK = 12; // product ids per bulk-suggest request (keeps each call short)
const DEFAULT_BATCH = 20;

function isNotConfigured(message: string): boolean {
	return /409|NOT_CONFIGURED|NOT_CONFIG/i.test(message);
}

interface ReviewRow {
	product_id: string;
	name: string;
	angle_count: number;
	suggestions: string[];
}

/**
 * Bulk Angle Suggestions (Phase 2) — cross-product AI angle drafting.
 *
 * Run AI over a batch of eligible products (approved snapshot + room for angles);
 * suggestions land here for review; Accept commits the chosen ones through the SAME
 * free, claim-gated add-angles path. No auto-commit; the only token spend is the
 * "Suggest" step (one small DeepSeek call per product, paced server-side).
 */
export default function BulkAngleSuggestionsPanel() {
	const [eligible, setEligible] = useState<EligibleProduct[] | null>(null);
	const [processed, setProcessed] = useState<Set<string>>(new Set());
	const [rows, setRows] = useState<ReviewRow[]>([]);
	const [selection, setSelection] = useState<Record<string, Set<string>>>({});
	const [batchSize, setBatchSize] = useState(DEFAULT_BATCH);
	const [busy, setBusy] = useState<"suggest" | "accept" | null>(null);
	const [progress, setProgress] = useState("");
	const [error, setError] = useState("");
	const [success, setSuccess] = useState("");
	const [confirmRunOpen, setConfirmRunOpen] = useState(false);

	const loadEligible = useCallback(async () => {
		try {
			const res = await fetchEligibleProducts();
			setEligible(res.items ?? []);
		} catch (e) {
			setEligible([]);
			setError(e instanceof Error ? e.message : "Failed to load eligible products.");
		}
	}, []);

	useEffect(() => {
		void loadEligible();
	}, [loadEligible]);

	const remaining = useMemo(
		() => (eligible ?? []).filter((p) => !processed.has(p.product_id)),
		[eligible, processed],
	);
	const nextBatch = useMemo(
		() => remaining.slice(0, Math.max(1, Math.min(50, Math.floor(batchSize) || 1))),
		[remaining, batchSize],
	);

	const runBatch = async () => {
		setConfirmRunOpen(false);
		if (busy || nextBatch.length === 0) return;
		setBusy("suggest");
		setError("");
		setSuccess("");
		const batch = nextBatch;
		const ids = batch.map((p) => p.product_id);
		const metaById = new Map(batch.map((p) => [p.product_id, p]));
		const collected: ReviewRow[] = [];
		try {
			for (let i = 0; i < ids.length; i += CHUNK) {
				const chunk = ids.slice(i, i + CHUNK);
				setProgress(`Suggesting ${Math.min(i + chunk.length, ids.length)}/${ids.length}…`);
				const res = await bulkSuggestAngles({ product_ids: chunk });
				for (const r of res.results) {
					if (r.ok && (r.suggestions?.length ?? 0) > 0) {
						const meta = metaById.get(r.product_id);
						collected.push({
							product_id: r.product_id,
							name: meta?.name ?? r.product_id,
							angle_count: meta?.angle_count ?? 0,
							suggestions: r.suggestions ?? [],
						});
					}
				}
			}
			setProcessed((prev) => {
				const next = new Set(prev);
				for (const id of ids) next.add(id);
				return next;
			});
			setRows((prev) => [...prev, ...collected]);
			setSelection((prev) => {
				const next = { ...prev };
				for (const row of collected) next[row.product_id] = new Set(row.suggestions);
				return next;
			});
			const totalAngles = collected.reduce((n, r) => n + r.suggestions.length, 0);
			setSuccess(
				`${collected.length} product(s) returned ${totalAngles} angle(s). Review + Accept below.`,
			);
		} catch (e) {
			const msg = e instanceof Error ? e.message : "Bulk suggest failed.";
			setError(
				isNotConfigured(msg)
					? "The AI lane (DeepSeek) is not configured. Set it up in Cockpit Settings / AI Providers first."
					: msg,
			);
		} finally {
			setProgress("");
			setBusy(null);
		}
	};

	const togglePain = (productId: string, pain: string) => {
		setSelection((prev) => {
			const set = new Set(prev[productId] ?? []);
			if (set.has(pain)) set.delete(pain);
			else set.add(pain);
			return { ...prev, [productId]: set };
		});
	};

	const discardRow = (productId: string) => {
		setRows((prev) => prev.filter((r) => r.product_id !== productId));
	};

	const acceptAll = async () => {
		if (busy || rows.length === 0) return;
		setBusy("accept");
		setError("");
		setSuccess("");
		let acceptedProducts = 0;
		let acceptedAngles = 0;
		const failures: string[] = [];
		const done: string[] = [];
		try {
			for (let i = 0; i < rows.length; i += 1) {
				const row = rows[i];
				const pains = [...(selection[row.product_id] ?? [])].filter(Boolean);
				if (pains.length === 0) continue;
				setProgress(`Accepting ${i + 1}/${rows.length} — ${row.name}`);
				try {
					const res = await addAngles({ product_id: row.product_id, pains });
					if (res.ok) {
						acceptedProducts += 1;
						acceptedAngles += res.added ?? pains.length;
						done.push(row.product_id);
					} else {
						failures.push(`${row.name}: ${res.error ?? "rejected"}`);
					}
				} catch (cause) {
					failures.push(`${row.name}: ${cause instanceof Error ? cause.message : "failed"}`);
				}
			}
			setRows((prev) => prev.filter((r) => !done.includes(r.product_id)));
			setSuccess(
				`${acceptedAngles} angle(s) added to ${acceptedProducts} product(s), free.` +
					(failures.length
						? ` ${failures.length} held: ${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""}`
						: ""),
			);
			await loadEligible();
		} catch (e) {
			setError(e instanceof Error ? e.message : "Accept failed.");
		} finally {
			setProgress("");
			setBusy(null);
		}
	};

	const eligibleCount = eligible?.length ?? 0;
	const totalSelected = rows.reduce(
		(n, r) => n + (selection[r.product_id]?.size ?? 0),
		0,
	);

	return (
		<Section
			title="Bulk angle suggestions (AI)"
			helper="Let AI draft angles across many products at once. Suggestions are reviewed here; Accept commits them free (claim-gated). No auto-commit."
			action={<Badge tone={eligibleCount > 0 ? "info" : "neutral"}>{eligibleCount} eligible</Badge>}
		>
			<div className="space-y-4" data-testid="bulk-angle-panel">
				{error ? (
					<p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-100" data-testid="bulk-error">{error}</p>
				) : null}
				{success ? (
					<p className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100" data-testid="bulk-success">{success}</p>
				) : null}
				{progress ? (
					<p className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs text-blue-100" data-testid="bulk-progress">{progress}</p>
				) : null}

				{eligible === null ? (
					<p className="text-xs text-slate-400" data-testid="bulk-loading">Loading eligible products…</p>
				) : (
					<div className="flex flex-wrap items-center gap-3 rounded-xl border border-fuchsia-500/20 bg-fuchsia-500/5 p-3">
						<span className="text-xs text-slate-300" data-testid="bulk-remaining">
							{remaining.length} not yet suggested this session
						</span>
						<label className="text-[11px] text-slate-400">
							Batch:{" "}
							<input
								type="number"
								min={1}
								max={50}
								value={batchSize}
								onChange={(e) => setBatchSize(Number(e.target.value))}
								className="w-16 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
								data-testid="bulk-batch-size"
								aria-label="Batch size"
							/>
						</label>
						<button
							type="button"
							data-testid="bulk-run"
							disabled={busy !== null || nextBatch.length === 0}
							onClick={() => setConfirmRunOpen(true)}
							className="rounded-lg border border-fuchsia-500/40 bg-fuchsia-600/20 px-4 py-2 text-xs font-bold uppercase text-fuchsia-100 disabled:opacity-40"
						>
							{busy === "suggest" ? "Suggesting…" : `✨ Suggest next ${nextBatch.length}`}
						</button>
						<span className="text-[11px] text-slate-500">Spends a little AI token per product.</span>
					</div>
				)}

				{rows.length > 0 ? (
					<div className="space-y-3" data-testid="bulk-review-list">
						<div className="flex flex-wrap items-center justify-between gap-2">
							<span className="text-xs font-bold uppercase text-slate-300">
								Review — {rows.length} product(s), {totalSelected} angle(s) selected
							</span>
							<button
								type="button"
								data-testid="bulk-accept-all"
								disabled={busy !== null || totalSelected === 0}
								onClick={() => void acceptAll()}
								className="rounded-lg border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40"
							>
								{busy === "accept" ? "Accepting…" : "Accept selected (free)"}
							</button>
						</div>
						{rows.map((row) => (
							<div key={row.product_id} className="rounded-xl border border-slate-800 bg-slate-900/40 p-3" data-testid={`bulk-row-${row.product_id}`}>
								<div className="mb-2 flex items-center justify-between gap-2">
									<span className="text-sm font-semibold text-slate-100">{row.name}</span>
									<div className="flex items-center gap-2">
										<span className="text-[11px] text-slate-500">{row.angle_count} current</span>
										<button
											type="button"
											onClick={() => discardRow(row.product_id)}
											className="text-[11px] text-slate-400 hover:text-rose-300"
											aria-label={`Discard ${row.name}`}
										>
											Discard
										</button>
									</div>
								</div>
								<div className="flex flex-wrap gap-2">
									{row.suggestions.map((pain) => {
										const checked = selection[row.product_id]?.has(pain) ?? false;
										return (
											<label
												key={pain}
												className={`cursor-pointer rounded border px-2 py-1 text-[11px] ${checked ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-100" : "border-slate-700 text-slate-400"}`}
											>
												<input
													type="checkbox"
													className="mr-1 align-middle"
													checked={checked}
													onChange={() => togglePain(row.product_id, pain)}
												/>
												{pain}
											</label>
										);
									})}
								</div>
							</div>
						))}
					</div>
				) : null}
			</div>

			<ConfirmActionModal
				open={confirmRunOpen}
				title="Suggest angles with AI for this batch?"
				body={`AI will draft new angles for ${nextBatch.length} product(s) — one small DeepSeek call each (spends a little token). Suggestions only appear here for review; nothing is saved until you Accept (free).`}
				confirmLabel={`Yes, suggest ${nextBatch.length} (spend a little)`}
				busy={busy === "suggest"}
				onConfirm={() => void runBatch()}
				onCancel={() => setConfirmRunOpen(false)}
			/>
		</Section>
	);
}
