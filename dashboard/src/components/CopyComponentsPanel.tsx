import { Boxes } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
	addAngles,
	approveCopyComponent,
	authorCopyComponents,
	COMPONENT_STATUS_REVIEW,
	COMPONENT_TYPE_LABEL,
	COMPONENT_TYPES,
	composeCopyFromComponents,
	type CopyComponentsCapacity,
	fetchCopyCapacity,
	listCopyComponents,
	suggestAngles,
} from "../api/copyComponents";
import { Badge, ConfirmActionModal, HelperText, Section } from "./ui";

const DEFAULT_COMPOSE = 50;
const DEFAULT_PER_SLOT = 4; // components authored per (angle × type) call
const MAX_ANGLES = 12; // mirrors agent copy_angle_derivation.MAX_ANGLES

function isNotConfigured(message: string): boolean {
	return /409|NOT_CONFIGURED|NOT_CONFIG/i.test(message);
}

/**
 * Copy Components control panel — the full self-serve pipeline in one place.
 *
 * 1) Add angle (FREE) → 2) Author components (spends AI tokens, once per product)
 * → 3) Approve components → 4) Compose unlimited scripts (FREE, deterministic).
 * Composed scripts land in the Copy Set Registry as Review required, exactly like
 * AI-assist copy.
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
	const [painsText, setPainsText] = useState("");
	const [busy, setBusy] = useState<
		"compose" | "author" | "approve" | "angle" | "suggest" | null
	>(null);
	const [progress, setProgress] = useState("");
	const [error, setError] = useState("");
	const [success, setSuccess] = useState("");
	const [confirmAuthorOpen, setConfirmAuthorOpen] = useState(false);
	// Once the operator types a compose count we stop auto-syncing it to capacity.
	const composeTouched = useRef(false);
	const [confirmSuggestOpen, setConfirmSuggestOpen] = useState(false);

	const load = useCallback(async () => {
		try {
			const [c, pool] = await Promise.all([
				fetchCopyCapacity(productId),
				listCopyComponents(productId).catch(() => ({ items: [] as { status: string }[] })),
			]);
			setCap(c);
			// Default the compose count to the FULL composable capacity (auto — not a
			// hardcoded number) unless the operator has typed their own value.
			if (!composeTouched.current) {
				setComposeCount(
					Math.max(1, Math.min(500, c.total_combinations || DEFAULT_COMPOSE)),
				);
			}
			setReviewCount(
				(pool.items ?? []).filter((i) => i.status === COMPONENT_STATUS_REVIEW).length,
			);
		} catch (e) {
			setCap(null);
			setError(e instanceof Error ? e.message : "Failed to load component capacity.");
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

	const handleAddAngles = async () => {
		if (busy) return;
		const pains = painsText
			.split(/[\r\n]+/)
			.map((s) => s.trim())
			.filter(Boolean);
		if (!pains.length) {
			setError("Write at least one use-case (one angle per line).");
			return;
		}
		setBusy("angle");
		setError("");
		setSuccess("");
		try {
			const res = await addAngles({ product_id: productId, pains });
			if (!res.ok) {
				setError(
					res.error === "CLAIM_BLOCKED"
						? `Angle rejected — it contains banned claim terms: ${(res.claim_tokens ?? []).join(", ") || "—"}.`
						: res.error || "Failed to add angle.",
				);
			} else {
				setPainsText("");
				setSuccess(
					`${res.added} angle(s) added → ${res.angle_count} total${
						res.capped ? ` (max ${MAX_ANGLES})` : ""
					}. Free. Next: Author components for the new angles.`,
				);
			}
			await load();
		} catch (e) {
			const msg = e instanceof Error ? e.message : "Failed to add angle.";
			setError(
				/ANGLES_FULL/.test(msg)
					? `Angles are already full (${MAX_ANGLES}).`
					: /NO_APPROVED_SNAPSHOT/.test(msg)
						? "This product has no approved Product Intelligence yet — set it up in Products → Intelligence first."
						: msg,
			);
		} finally {
			setBusy(null);
		}
	};

	const handleSuggestAngles = async () => {
		setConfirmSuggestOpen(false);
		if (busy) return;
		setBusy("suggest");
		setError("");
		setSuccess("");
		try {
			const remaining = Math.max(0, MAX_ANGLES - angles.length);
			const res = await suggestAngles({
				product_id: productId,
				count: Math.min(8, remaining) || 8,
			});
			const fresh = (res.suggestions ?? []).filter(Boolean);
			if (!fresh.length) {
				setError(
					"AI found no new angles for this product — add more product knowledge first, or type your own.",
				);
			} else {
				setPainsText((prev) => {
					const base = prev.trim();
					return (base ? `${base}\n` : "") + fresh.join("\n");
				});
				setSuccess(
					`${fresh.length} angle(s) suggested by AI — review, edit, then click "Add angle" to save (free).`,
				);
			}
		} catch (e) {
			const msg = e instanceof Error ? e.message : "Failed to suggest angles.";
			setError(
				isNotConfigured(msg)
					? "The AI lane (DeepSeek) is not configured. Set it up in Cockpit Settings / AI Providers first."
					: /NO_APPROVED_SNAPSHOT/.test(msg)
						? "This product has no approved Product Intelligence yet — set it up in Products → Intelligence first."
						: msg,
			);
		} finally {
			setBusy(null);
		}
	};

	const handleCompose = async () => {
		if (busy || capacity === 0) return;
		setBusy("compose");
		setError("");
		setSuccess("");
		try {
			const n = Math.max(1, Math.min(500, Math.floor(composeCount) || 1));
			const res = await composeCopyFromComponents({ product_id: productId, count: n });
			setSuccess(
				`${res.created} unique scripts generated (FREE, no tokens)${
					res.deduped ? ` · ${res.deduped} duplicates filtered` : ""
				}. Added to the Copy Set Registry as "Review required".`,
			);
			onComposed?.();
			await load();
		} catch (e) {
			setError(e instanceof Error ? e.message : "Compose failed.");
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
		let failedSlots = 0;
		let notConfigured = false;
		// Resilient loop: one failed slot must NOT strand the other angles. Each
		// (angle × type) slot is isolated — retried once on a transient error, then
		// skipped so every registered angle still gets its components.
		for (const angle of angles) {
			for (const type of COMPONENT_TYPES) {
				done += 1;
				setProgress(
					`Authoring ${done}/${totalSlots} — ${COMPONENT_TYPE_LABEL[type]} · ${angle.angle_label || "angle"}`,
				);
				try {
					const r = await authorCopyComponents({
						product_id: productId,
						angle_key: angle.angle_key,
						component_type: type,
						count: per,
					});
					authored += r.created_count ?? 0;
				} catch (e) {
					const msg = e instanceof Error ? e.message : "";
					if (isNotConfigured(msg)) {
						notConfigured = true;
						break; // provider config won't self-heal mid-run
					}
					try {
						const retry = await authorCopyComponents({
							product_id: productId,
							angle_key: angle.angle_key,
							component_type: type,
							count: per,
						});
						authored += retry.created_count ?? 0;
					} catch {
						failedSlots += 1; // record + continue to the next slot
					}
				}
			}
			if (notConfigured) break;
		}
		setProgress("");
		setBusy(null);
		await load();
		if (notConfigured) {
			setError(
				"The AI lane (DeepSeek) is not configured. Set it up in Cockpit Settings / AI Providers first.",
			);
		} else if (failedSlots > 0) {
			setError(
				`${failedSlots} slot(s) failed (likely a transient AI hiccup) and were skipped — re-run Author to fill the gaps.`,
			);
			setSuccess(
				`${authored} components generated across ${angles.length} angles (partial). Approve below, then re-run Author to complete the rest.`,
			);
		} else {
			setSuccess(
				`${authored} components generated across ${angles.length} angles. Approve the components below, then Compose (free).`,
			);
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
				setProgress(`Approving component ${i + 1}/${pending.length}…`);
				try {
					await approveCopyComponent(pending[i].component_id);
					ok += 1;
				} catch {
					/* leave un-approved; reported via reload count */
				}
			}
			setSuccess(`${ok} components approved. Compose capacity updated.`);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Failed to approve components.");
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
			title="Copy Components — compose engine (free)"
			helper="Author components once (spends tokens) → Compose unlimited scripts (free). Scripts land in the Copy Set Registry below as Review required."
			action={
				<div className="flex items-center gap-2 text-blue-300">
					<Boxes size={18} />
					<Badge tone={capacity > 0 ? "success" : "neutral"}>
						{capacity.toLocaleString()} composable
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
						<span className="text-slate-500">Angles: </span>
						<span data-testid="cc-angle-count" className="font-semibold text-slate-100">
							{angles.length}
						</span>
					</div>
					<div>
						<span className="text-slate-500">Components: </span>
						<span data-testid="cc-component-count" className="font-semibold text-slate-100">
							{componentCount}
						</span>
						{reviewCount > 0 ? (
							<span className="ml-1 text-amber-300">({reviewCount} pending approval)</span>
						) : null}
					</div>
					<div>
						<span className="text-slate-500">Composable: </span>
						<span data-testid="cc-capacity" className="font-semibold text-slate-100">
							{capacity.toLocaleString()}
						</span>
					</div>
				</div>

				{cap && !cap.angles_derived ? (
					<HelperText tone="warn">
						This product has no approved angles (approved snapshot) yet. Approve
						its Product Intelligence first before authoring components.
					</HelperText>
				) : null}

				<HelperText>
					Order: 1) Add angle → 2) Author components (tokens) → 3) Approve
					components → 4) Compose scripts. Only the Author step spends tokens.
				</HelperText>

				{/* Angle — FREE */}
				<div className="space-y-2 rounded-xl border border-blue-500/20 bg-blue-500/5 p-3">
					<div className="flex items-center justify-between">
						<span className="text-xs font-bold uppercase text-blue-200">
							1. Angle / use-case (free)
						</span>
						<span className="text-[11px] text-slate-400" data-testid="cc-angle-cap">
							{angles.length}/{MAX_ANGLES}
						</span>
					</div>
					{angles.length ? (
						<div className="flex flex-wrap gap-1" data-testid="cc-angle-list">
							{angles.map((a) => (
								<span
									key={a.angle_key}
									className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-300"
								>
									{a.angle_label || a.angle_key}
								</span>
							))}
						</div>
					) : null}
					{angles.length < MAX_ANGLES ? (
						<>
							<div className="flex flex-col gap-2 sm:flex-row sm:items-start">
								<textarea
									value={painsText}
									onChange={(e) => setPainsText(e.target.value)}
									placeholder="Add a new use-case — one angle per line…"
									rows={2}
									data-testid="cc-pains"
									aria-label="New angle use-case"
									className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
								/>
								<div className="flex shrink-0 gap-2">
									<button
										type="button"
										data-testid="cc-suggest-angles"
										disabled={busy !== null}
										onClick={() => setConfirmSuggestOpen(true)}
										title="Let AI propose angles from this product's knowledge + avatar (spends a little token)"
										className="shrink-0 rounded-lg border border-fuchsia-500/40 bg-fuchsia-600/20 px-4 py-2 text-xs font-bold uppercase text-fuchsia-100 disabled:opacity-40"
									>
										{busy === "suggest" ? "Suggesting…" : "✨ Suggest (AI)"}
									</button>
									<button
										type="button"
										data-testid="cc-add-angles"
										disabled={busy !== null}
										onClick={() => void handleAddAngles()}
										className="shrink-0 rounded-lg border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40"
									>
										{busy === "angle" ? "Adding…" : "Add angle"}
									</button>
								</div>
							</div>
							<p className="text-[11px] text-slate-500">
								✨ Suggest uses a little AI token to draft angles; Add angle
								stays free.
							</p>
						</>
					) : (
						<p className="text-[11px] text-slate-400">
							Angles are full ({MAX_ANGLES}).
						</p>
					)}
				</div>

				{/* Compose — FREE */}
				<div className="flex flex-wrap items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
					<span className="text-xs font-bold uppercase text-emerald-200">
						Compose (free)
					</span>
					<input
						type="number"
						min={1}
						max={500}
						value={composeCount}
						onChange={(e) => {
								composeTouched.current = true;
								setComposeCount(Number(e.target.value));
							}}
						className={inputCls}
						data-testid="cc-compose-count"
						aria-label="Number of scripts to compose"
					/>
					<button
						type="button"
						data-testid="cc-compose"
						disabled={busy !== null || capacity === 0}
						onClick={() => void handleCompose()}
						className="rounded-lg border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40"
					>
						{busy === "compose" ? "Composing…" : "Compose scripts"}
					</button>
					<span className="text-[11px] text-slate-500">
						No tokens — just assembles existing components.
					</span>
				</div>

				{/* Author — TOKENS */}
				<div className="flex flex-wrap items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
					<span className="text-xs font-bold uppercase text-amber-200">
						Author components ⚠ (spends tokens)
					</span>
					<label className="text-[11px] text-slate-400">
						Per slot:{" "}
						<input
							type="number"
							min={2}
							max={12}
							value={perSlot}
							onChange={(e) => setPerSlot(Number(e.target.value))}
							className="w-16 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
							data-testid="cc-per-slot"
							aria-label="Components per slot"
						/>
					</label>
					<button
						type="button"
						data-testid="cc-author"
						disabled={busy !== null || angles.length === 0}
						onClick={() => setConfirmAuthorOpen(true)}
						className="rounded-lg border border-amber-500/40 bg-amber-600/20 px-4 py-2 text-xs font-bold uppercase text-amber-100 disabled:opacity-40"
					>
						{busy === "author" ? "Authoring…" : "Author components"}
					</button>
					{reviewCount > 0 ? (
						<button
							type="button"
							data-testid="cc-approve-components"
							disabled={busy !== null}
							onClick={() => void handleApproveComponents()}
							className="rounded-lg border border-emerald-500/40 px-4 py-2 text-xs font-bold uppercase text-emerald-200 disabled:opacity-40"
						>
							{busy === "approve" ? "Approving…" : `Approve ${reviewCount} components`}
						</button>
					) : null}
				</div>
			</div>

			<ConfirmActionModal
				open={confirmAuthorOpen}
				tone="danger"
				title="Author components — spend DeepSeek tokens?"
				body={`This will make ~${totalSlots} AI calls (${angles.length} angles × ${COMPONENT_TYPES.length} types, ${perSlot} per slot) and SPENDS TOKENS. It is a one-time step per product; after this, Compose is free and unlimited. New components are Review required — approve them before composing.`}
				confirmLabel="Yes, author (spend tokens)"
				busy={busy === "author"}
				onConfirm={() => void handleAuthor()}
				onCancel={() => setConfirmAuthorOpen(false)}
			/>

			<ConfirmActionModal
				open={confirmSuggestOpen}
				title="Suggest angles with AI (DeepSeek)?"
				body="AI reads this product's knowledge + customer avatar and drafts a few NEW angles (one small AI call — spends a little token). The suggestions only fill the box for you to review and edit; nothing is saved until you click Add angle (free)."
				confirmLabel="Yes, suggest (spend a little)"
				busy={busy === "suggest"}
				onConfirm={() => void handleSuggestAngles()}
				onCancel={() => setConfirmSuggestOpen(false)}
			/>
		</Section>
	);
}
