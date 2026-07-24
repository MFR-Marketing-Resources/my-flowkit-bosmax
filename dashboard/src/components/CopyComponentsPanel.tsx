import { Boxes } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
	approveCopyComponent,
	authorCopyComponents,
	COMPONENT_STATUS_REVIEW,
	COMPONENT_TYPE_LABEL,
	COMPONENT_TYPES,
	composeCopyFromComponents,
	type CopyComponentsCapacity,
	fetchCopyCapacity,
	listCopyComponents,
} from "../api/copyComponents";
import { Badge, ConfirmActionModal, HelperText, Section } from "./ui";

const DEFAULT_COMPOSE = 50;
const DEFAULT_PER_SLOT = 4; // components authored per (angle × type) call

function isNotConfigured(message: string): boolean {
	return /409|NOT_CONFIGURED|NOT_CONFIG/i.test(message);
}

/**
 * Copy Components control panel — the free-compose engine, self-serve.
 *
 * Author components (⚠ spends AI tokens, once per product) → Approve them →
 * Compose unlimited copy sets (free, deterministic). Composed sets land in the
 * Copy Set Registry as Review required, exactly like AI-assist copy.
 */
export default function CopyComponentsPanel({
	productId,
	onComposed,
}: {
	productId: string;
	onComposed?: () => void;
}) {
	const [cap, setCap] = useState<CopyComponentsCapacity | null>(null);
	const [reviewCount, setReviewCount] = useState(0);
	const [composeCount, setComposeCount] = useState(DEFAULT_COMPOSE);
	const [perSlot, setPerSlot] = useState(DEFAULT_PER_SLOT);
	const [busy, setBusy] = useState<"compose" | "author" | "approve" | null>(null);
	const [progress, setProgress] = useState("");
	const [error, setError] = useState("");
	const [success, setSuccess] = useState("");
	const [confirmAuthorOpen, setConfirmAuthorOpen] = useState(false);

	const load = useCallback(async () => {
		try {
			const [c, pool] = await Promise.all([
				fetchCopyCapacity(productId),
				listCopyComponents(productId).catch(() => ({ items: [] as { status: string }[] })),
			]);
			setCap(c);
			setReviewCount(
				(pool.items ?? []).filter((i) => i.status === COMPONENT_STATUS_REVIEW).length,
			);
		} catch (e) {
			setCap(null);
			setError(e instanceof Error ? e.message : "Gagal muat kapasiti komponen.");
		}
	}, [productId]);

	useEffect(() => {
		setError("");
		setSuccess("");
		setProgress("");
		void load();
	}, [load]);

	const angles = cap?.per_angle ?? [];
	const totalSlots = angles.length * COMPONENT_TYPES.length;
	const capacity = cap?.total_combinations ?? 0;
	const componentCount = cap?.component_count ?? 0;

	const handleCompose = async () => {
		if (busy || capacity === 0) return;
		setBusy("compose");
		setError("");
		setSuccess("");
		try {
			const n = Math.max(1, Math.min(500, Math.floor(composeCount) || 1));
			const res = await composeCopyFromComponents({ product_id: productId, count: n });
			setSuccess(
				`${res.created} skrip unik dijana (PERCUMA, tiada token)${
					res.deduped ? ` · ${res.deduped} duplikat ditapis` : ""
				}. Masuk Copy Set Registry sebagai "Review required".`,
			);
			onComposed?.();
			await load();
		} catch (e) {
			setError(e instanceof Error ? e.message : "Gagal compose.");
		} finally {
			setBusy(null);
		}
	};

	const handleAuthor = async () => {
		setConfirmAuthorOpen(false);
		if (busy || angles.length === 0) return;
		setBusy("author");
		setError("");
		setSuccess("");
		const per = Math.max(2, Math.min(12, Math.floor(perSlot) || DEFAULT_PER_SLOT));
		let authored = 0;
		let done = 0;
		try {
			for (const angle of angles) {
				for (const type of COMPONENT_TYPES) {
					done += 1;
					setProgress(
						`Authoring ${done}/${totalSlots} — ${COMPONENT_TYPE_LABEL[type]} · ${angle.angle_label || "angle"}`,
					);
					const r = await authorCopyComponents({
						product_id: productId,
						angle_key: angle.angle_key,
						component_type: type,
						count: per,
					});
					authored += r.created_count ?? 0;
				}
			}
			setSuccess(
				`${authored} komponen dijana merentas ${angles.length} angle. Approve komponen di bawah, kemudian Compose (percuma).`,
			);
		} catch (e) {
			const msg = e instanceof Error ? e.message : "Gagal author komponen.";
			setError(
				isNotConfigured(msg)
					? "Lane AI (DeepSeek) belum dikonfigur. Set di Cockpit Settings / AI Providers dahulu."
					: `Author terhenti (${authored} sudah dijana): ${msg}`,
			);
		} finally {
			setProgress("");
			setBusy(null);
			await load();
		}
	};

	const handleApproveComponents = async () => {
		if (busy || reviewCount === 0) return;
		setBusy("approve");
		setError("");
		setSuccess("");
		try {
			const pool = await listCopyComponents(productId);
			const pending = (pool.items ?? []).filter(
				(i) => i.status === COMPONENT_STATUS_REVIEW,
			);
			let ok = 0;
			for (let i = 0; i < pending.length; i += 1) {
				setProgress(`Approving komponen ${i + 1}/${pending.length}…`);
				try {
					await approveCopyComponent(pending[i].component_id);
					ok += 1;
				} catch {
					/* leave un-approved; reported via reload count */
				}
			}
			setSuccess(`${ok} komponen diluluskan. Kapasiti compose dikemas kini.`);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Gagal approve komponen.");
		} finally {
			setProgress("");
			setBusy(null);
			await load();
		}
	};

	const inputCls =
		"w-24 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200";

	return (
		<Section
			title="Copy Components — enjin compose (percuma)"
			helper="Author komponen sekali (guna token) → Compose skrip tanpa had (percuma). Skrip masuk Copy Set Registry di bawah sebagai Review required."
			action={
				<div className="flex items-center gap-2 text-blue-300">
					<Boxes size={18} />
					<Badge tone={capacity > 0 ? "success" : "neutral"}>
						{capacity.toLocaleString()} boleh dijana
					</Badge>
				</div>
			}
		>
			<div className="space-y-4" data-testid="copy-components-panel">
				{error ? (
					<p
						className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-100"
						data-testid="cc-error"
					>
						{error}
					</p>
				) : null}
				{success ? (
					<p
						className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100"
						data-testid="cc-success"
					>
						{success}
					</p>
				) : null}
				{progress ? (
					<p
						className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs text-blue-100"
						data-testid="cc-progress"
					>
						{progress}
					</p>
				) : null}

				{/* Status */}
				<div className="grid gap-2 rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-xs text-slate-300 sm:grid-cols-3">
					<div>
						<span className="text-slate-500">Angle: </span>
						<span data-testid="cc-angle-count" className="font-semibold text-slate-100">
							{angles.length}
						</span>
					</div>
					<div>
						<span className="text-slate-500">Komponen: </span>
						<span data-testid="cc-component-count" className="font-semibold text-slate-100">
							{componentCount}
						</span>
						{reviewCount > 0 ? (
							<span className="ml-1 text-amber-300">({reviewCount} belum approve)</span>
						) : null}
					</div>
					<div>
						<span className="text-slate-500">Boleh compose: </span>
						<span data-testid="cc-capacity" className="font-semibold text-slate-100">
							{capacity.toLocaleString()}
						</span>
					</div>
				</div>

				{cap && !cap.angles_derived ? (
					<HelperText tone="warn">
						Produk ini belum ada angle diluluskan (approved snapshot). Approve
						Product Intelligence dahulu sebelum author komponen.
					</HelperText>
				) : null}

				{/* Compose — FREE */}
				<div className="flex flex-wrap items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
					<span className="text-xs font-bold uppercase text-emerald-200">
						Compose (percuma)
					</span>
					<input
						type="number"
						min={1}
						max={500}
						value={composeCount}
						onChange={(e) => setComposeCount(Number(e.target.value))}
						className={inputCls}
						data-testid="cc-compose-count"
						aria-label="Bilangan skrip untuk compose"
					/>
					<button
						type="button"
						data-testid="cc-compose"
						disabled={busy !== null || capacity === 0}
						onClick={() => void handleCompose()}
						className="rounded-lg border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40"
					>
						{busy === "compose" ? "Composing…" : "Compose skrip"}
					</button>
					<span className="text-[11px] text-slate-500">
						Tiada token — cuma menyusun komponen sedia ada.
					</span>
				</div>

				{/* Author — TOKENS */}
				<div className="flex flex-wrap items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
					<span className="text-xs font-bold uppercase text-amber-200">
						Author komponen ⚠ (guna token)
					</span>
					<label className="text-[11px] text-slate-400">
						Setiap slot:{" "}
						<input
							type="number"
							min={2}
							max={12}
							value={perSlot}
							onChange={(e) => setPerSlot(Number(e.target.value))}
							className="w-16 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
							data-testid="cc-per-slot"
							aria-label="Komponen setiap slot"
						/>
					</label>
					<button
						type="button"
						data-testid="cc-author"
						disabled={busy !== null || angles.length === 0}
						onClick={() => setConfirmAuthorOpen(true)}
						className="rounded-lg border border-amber-500/40 bg-amber-600/20 px-4 py-2 text-xs font-bold uppercase text-amber-100 disabled:opacity-40"
					>
						{busy === "author" ? "Authoring…" : "Author komponen"}
					</button>
					{reviewCount > 0 ? (
						<button
							type="button"
							data-testid="cc-approve-components"
							disabled={busy !== null}
							onClick={() => void handleApproveComponents()}
							className="rounded-lg border border-emerald-500/40 px-4 py-2 text-xs font-bold uppercase text-emerald-200 disabled:opacity-40"
						>
							{busy === "approve" ? "Approving…" : `Approve ${reviewCount} komponen`}
						</button>
					) : null}
				</div>
			</div>

			<ConfirmActionModal
				open={confirmAuthorOpen}
				tone="danger"
				title="Author komponen — guna token DeepSeek?"
				body={`Ini akan buat ~${totalSlots} panggilan AI (${angles.length} angle × ${COMPONENT_TYPES.length} jenis, ${perSlot} setiap slot) dan MAKAN TOKEN. Ia langkah sekali per produk; lepas ni Compose percuma tanpa had. Komponen baru bertaraf Review required — approve sebelum compose.`}
				confirmLabel="Ya, author (guna token)"
				busy={busy === "author"}
				onConfirm={() => void handleAuthor()}
				onCancel={() => setConfirmAuthorOpen(false)}
			/>
		</Section>
	);
}
