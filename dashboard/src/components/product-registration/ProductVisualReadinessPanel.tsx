import {
	useEffect,
	useRef,
	useState,
	type ChangeEvent,
	type PointerEvent as ReactPointerEvent,
	type ReactNode,
} from "react";
import {
	approveProductTruthLock,
	productTruthCutoutPreviewUrl,
} from "../../api/productTruthLock";
import {
	fetchProductVisualReadiness,
	prepareProductCutout,
	rejectProductCutout,
	rebuildProductCutout,
	uploadManualProductCutout,
	useOriginalProductFallback,
	startCanvaCutout,
	recordCanvaPreflight,
	advanceCanvaStage,
	completeCanvaCutout,
	setProductCutoutTarget,
	clearProductCutoutTarget,
	type CanvaCapabilityStatus,
	type CanvaMethod,
} from "../../api/productVisualOnboarding";
import type { CanvaCutoutWorkflow, ProductVisualReadiness } from "../../types";

interface Props {
	productId: string;
	productSourceUrl?: string | null;
	readiness?: ProductVisualReadiness;
	compact?: boolean;
	showApprovalForm?: boolean;
	onOpenReview?: () => void;
	onChanged?: (readiness: ProductVisualReadiness) => void;
}

const BADGE: Record<string, string> = {
	AVAILABLE: "bg-emerald-500/15 text-emerald-300",
	APPROVED: "bg-emerald-500/15 text-emerald-300",
	PENDING_REVIEW: "bg-amber-500/15 text-amber-300",
	PREPARING: "bg-sky-500/15 text-sky-300",
	PREPARATION_FAILED: "bg-red-500/15 text-red-300",
	BLOCKED: "bg-red-500/15 text-red-300",
	REJECTED: "bg-red-500/15 text-red-300",
	SUPERSEDED: "bg-slate-700/40 text-slate-400",
	VISUAL_GROUNDING_READY_FALLBACK: "bg-amber-500/15 text-amber-300",
	CUTOUT_REQUIRED: "bg-amber-500/15 text-amber-300",
	NOT_PREPARED: "bg-slate-700/40 text-slate-400",
};

const label = (value: string | undefined | null): string =>
	(value || "NOT_PREPARED").replace(/_/g, " ");

const CANVA_PREFLIGHT_FIELDS = [
	["login_status", "Canva login/session"],
	["magic_grab_status", "Magic Grab"],
	["background_remover_status", "Background Remover"],
	["magic_layers_status", "Magic Layers"],
	["transparent_export_status", "Transparent PNG export"],
] as const;
const CANVA_PREFLIGHT_OPTIONS: CanvaCapabilityStatus[] = ["UNKNOWN", "READY", "UNAVAILABLE", "PRO_REQUIRED", "USER_ACTION_REQUIRED"];
const CANVA_OPERATOR_STAGES = ["OPENING_CANVA", "MAGIC_GRAB", "BACKGROUND_REMOVER", "MAGIC_LAYERS", "CLEAN_CANVAS", "READY_TO_EXPORT", "EXPORTING", "PAUSED"] as const;

// ── Per-lane busy model ────────────────────────────────────────────────────
// A running action only disables its OWN lane. `busy` tracks the specific
// action (so button labels stay precise); `busyLane` is derived for the
// enable/disable logic so e.g. an Auto prepare/rebuild never disables Upload.
type BusyAction =
	| "prepare"
	| "rebuild"
	| "upload"
	| "canva"
	| "canva-preflight"
	| "canva-stage"
	| "canva-upload"
	| "approve"
	| "reject"
	| "fallback"
	| "target-save"
	| "target-clear";
type BusyLane = "auto" | "manual" | "canva" | "review" | "fallback" | "target";
const BUSY_LANE: Record<BusyAction, BusyLane> = {
	prepare: "auto",
	rebuild: "auto",
	upload: "manual",
	canva: "canva",
	"canva-preflight": "canva",
	"canva-stage": "canva",
	"canva-upload": "canva",
	approve: "review",
	reject: "review",
	fallback: "fallback",
	"target-save": "target",
	"target-clear": "target",
};

function candidateExists(status?: string | null): boolean {
	return !!status && status !== "NOT_PREPARED" && status !== "NOT_UPLOADED";
}

type CardKey = "original" | "auto" | "manual";

// Derive the CURRENT / OFFICIAL / PENDING markers for the three cards purely
// from backend authority. Exactly one card carries "CURRENT SYSTEM REFERENCE"
// whenever an active source exists.
function computeCardBadges(readiness: ProductVisualReadiness): Record<CardKey, string[]> {
	const active = readiness.active_visual_source;
	const autoHas = candidateExists(readiness.auto_cutout_status);
	const manualHas = candidateExists(readiness.manual_cutout_status);
	const pending = (has: boolean, fallback: string): string[] =>
		has ? ["PENDING REVIEW", "NOT YET USED BY SYSTEM"] : [fallback];

	if (active === "APPROVED_AUTO_CANONICAL_CUTOUT") {
		return {
			original: ["NOT SELECTED"],
			auto: ["OFFICIAL CUTOUT", "CURRENT SYSTEM REFERENCE"],
			manual: ["NOT SELECTED"],
		};
	}
	if (active === "APPROVED_MANUAL_CANONICAL_CUTOUT") {
		return {
			original: ["NOT SELECTED"],
			auto: ["NOT SELECTED"],
			manual: ["OFFICIAL CUTOUT", "CURRENT SYSTEM REFERENCE"],
		};
	}
	if (active === "SAME_PRODUCT_TRUSTED_SOURCE") {
		return {
			original: ["CURRENT SYSTEM REFERENCE", "ORIGINAL FALLBACK"],
			auto: pending(autoHas, "NOT SELECTED"),
			manual: pending(manualHas, "NOT AVAILABLE / NOT SELECTED"),
		};
	}
	// BLOCKED / nothing selected yet — no card is the current reference.
	return {
		original: ["NOT SELECTED"],
		auto: pending(autoHas, "NOT SELECTED"),
		manual: pending(manualHas, "NOT SELECTED"),
	};
}

const CURRENT_MARKERS = new Set(["CURRENT SYSTEM REFERENCE", "OFFICIAL CUTOUT"]);

function CardBadges({ badges, testid }: { badges: string[]; testid: string }) {
	return (
		<div className="mt-1 flex flex-wrap gap-1" data-testid={testid}>
			{badges.map((badge) => (
				<span
					key={badge}
					className={`rounded px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-widest ${CURRENT_MARKERS.has(badge) ? "bg-emerald-500/20 text-emerald-200" : "bg-slate-700/40 text-slate-400"}`}
				>
					{badge}
				</span>
			))}
		</div>
	);
}

function Status({ name, value }: { name: string; value: string | undefined }) {
	return (
		<div className="min-w-0">
			<div className="mb-1 text-[8px] font-bold uppercase tracking-widest text-slate-500">
				{name}
			</div>
			<span
				className={`inline-flex max-w-full truncate rounded px-1.5 py-0.5 text-[9px] font-bold ${BADGE[value || ""] || "bg-slate-700/40 text-slate-400"}`}
			>
				{label(value)}
			</span>
		</div>
	);
}

function ReasonLine({ children, testid, tone = "muted" }: { children: ReactNode; testid?: string; tone?: "muted" | "warn" | "ok" }) {
	const color = tone === "warn" ? "text-amber-300" : tone === "ok" ? "text-emerald-300/80" : "text-slate-500";
	return (
		<p className={`mt-1 text-[9px] ${color}`} data-testid={testid}>
			{children}
		</p>
	);
}

// ── Bounded ROI selector over the ORIGINAL SOURCE preview ───────────────────
// The operator drags a rectangle; ROI is computed in SOURCE pixels from the
// image's natural vs rendered size. Coordinates are hidden from the normal
// view (kept in a small Advanced detail).
function ProductAreaSelector({
	imageUrl,
	target,
	busy,
	onSave,
	onClear,
}: {
	imageUrl: string;
	target?: ProductVisualReadiness["target_region"];
	busy: boolean;
	onSave: (roi: { x: number; y: number; width: number; height: number }) => void;
	onClear: () => void;
}) {
	const [open, setOpen] = useState(false);
	const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
	const [rect, setRect] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
	const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
	const containerRef = useRef<HTMLDivElement>(null);
	const hasTarget = !!target;

	function toLocal(event: ReactPointerEvent<HTMLDivElement>): { x: number; y: number } {
		const el = containerRef.current;
		if (!el) return { x: 0, y: 0 };
		const bounds = el.getBoundingClientRect();
		return {
			x: Math.max(0, Math.min(event.clientX - bounds.left, bounds.width)),
			y: Math.max(0, Math.min(event.clientY - bounds.top, bounds.height)),
		};
	}

	function onPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
		if (busy) return;
		event.preventDefault();
		(event.currentTarget as HTMLDivElement).setPointerCapture?.(event.pointerId);
		const point = toLocal(event);
		setDragStart(point);
		setRect({ x: point.x, y: point.y, w: 0, h: 0 });
	}

	function onPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
		if (!dragStart) return;
		const point = toLocal(event);
		setRect({
			x: Math.min(dragStart.x, point.x),
			y: Math.min(dragStart.y, point.y),
			w: Math.abs(point.x - dragStart.x),
			h: Math.abs(point.y - dragStart.y),
		});
	}

	function onPointerUp() {
		setDragStart(null);
	}

	function computeRoi(): { x: number; y: number; width: number; height: number } | null {
		const el = containerRef.current;
		if (!el || !natural || !rect || rect.w < 2 || rect.h < 2) return null;
		const rendered = el.getBoundingClientRect();
		if (rendered.width <= 0 || rendered.height <= 0) return null;
		const scaleX = natural.w / rendered.width;
		const scaleY = natural.h / rendered.height;
		const x = Math.max(0, Math.min(natural.w - 1, Math.round(rect.x * scaleX)));
		const y = Math.max(0, Math.min(natural.h - 1, Math.round(rect.y * scaleY)));
		const width = Math.max(1, Math.min(natural.w - x, Math.round(rect.w * scaleX)));
		const height = Math.max(1, Math.min(natural.h - y, Math.round(rect.h * scaleY)));
		return { x, y, width, height };
	}

	const roi = computeRoi();

	let savedOutline: { left: number; top: number; width: number; height: number } | null = null;
	const el = containerRef.current;
	if (target && natural && el && el.clientWidth > 0 && el.clientHeight > 0) {
		const scaleX = el.clientWidth / natural.w;
		const scaleY = el.clientHeight / natural.h;
		savedOutline = {
			left: target.x * scaleX,
			top: target.y * scaleY,
			width: target.width * scaleX,
			height: target.height * scaleY,
		};
	}

	return (
		<div className="mt-3">
			<div className="flex flex-wrap items-center gap-2">
				<button
					type="button"
					data-testid="select-product-area"
					onClick={() => setOpen((value) => !value)}
					className="rounded-lg bg-sky-600/80 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white"
				>
					{open ? "Hide Product Area" : hasTarget ? "Change Product Area" : "Select Product Area"}
				</button>
				{hasTarget && (
					<button
						type="button"
						onClick={onClear}
						disabled={busy}
						className="rounded-lg bg-slate-700 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-200 disabled:opacity-40"
					>
						{busy ? "Clearing…" : "Clear Product Area"}
					</button>
				)}
			</div>
			{open && (
				<div className="mt-2">
					<p className="mb-1 text-[9px] text-slate-400">
						Select only the actual product. Exclude props, food, text, hands, decoration, or other objects.
					</p>
					<div
						ref={containerRef}
						data-testid="roi-selector"
						onPointerDown={onPointerDown}
						onPointerMove={onPointerMove}
						onPointerUp={onPointerUp}
						className="relative inline-block max-w-full cursor-crosshair select-none overflow-hidden rounded border border-slate-700"
						style={{ touchAction: "none" }}
					>
						<img
							src={imageUrl}
							alt="Product source for area selection"
							draggable={false}
							onLoad={(event) => setNatural({ w: event.currentTarget.naturalWidth, h: event.currentTarget.naturalHeight })}
							className="block max-h-72 w-auto max-w-full"
						/>
						{savedOutline && !rect && (
							<div
								className="pointer-events-none absolute border-2 border-emerald-400"
								style={{ left: savedOutline.left, top: savedOutline.top, width: savedOutline.width, height: savedOutline.height }}
							/>
						)}
						{rect && rect.w > 0 && rect.h > 0 && (
							<div
								className="pointer-events-none absolute border-2 border-sky-400 bg-sky-400/10"
								style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}
							/>
						)}
					</div>
					<div className="mt-2 flex flex-wrap items-center gap-2">
						<button
							type="button"
							data-testid="save-product-area"
							onClick={() => {
								const next = computeRoi();
								if (next) onSave(next);
							}}
							disabled={busy || !roi}
							className="rounded-lg bg-emerald-600/80 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40"
						>
							{busy ? "Saving…" : "Save Product Area"}
						</button>
						<button
							type="button"
							onClick={() => {
								setRect(null);
								setDragStart(null);
							}}
							disabled={busy || !rect}
							className="rounded-lg bg-slate-700 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-200 disabled:opacity-40"
						>
							Reset Selection
						</button>
					</div>
					<details className="mt-2 text-[9px] text-slate-500">
						<summary className="cursor-pointer">Advanced (coordinates)</summary>
						<div className="mt-1">
							{roi
								? `Selection: x ${roi.x}, y ${roi.y}, w ${roi.width}, h ${roi.height} (source px)`
								: target
									? `Saved: x ${target.x}, y ${target.y}, w ${target.width}, h ${target.height} (source px)`
									: "Drag a rectangle on the image to select the product area."}
						</div>
					</details>
				</div>
			)}
		</div>
	);
}

export default function ProductVisualReadinessPanel({
	productId,
	productSourceUrl,
	readiness: initialReadiness,
	compact = false,
	showApprovalForm = false,
	onOpenReview,
	onChanged,
}: Props) {
	const [readiness, setReadiness] = useState<ProductVisualReadiness | undefined>(
		initialReadiness,
	);
	const [busy, setBusy] = useState<BusyAction | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [reviewedBy, setReviewedBy] = useState("");
	const [reviewNote, setReviewNote] = useState("");
	const [confirmIdentity, setConfirmIdentity] = useState(false);
	const [confirmLabelLogo, setConfirmLabelLogo] = useState(false);
	const [confirmGeometryScale, setConfirmGeometryScale] = useState(false);
	const [confirmProductIsolation, setConfirmProductIsolation] = useState(false);
	const fileInputRef = useRef<HTMLInputElement>(null);
	const canvaFileInputRef = useRef<HTMLInputElement>(null);
	const [canvaWorkflow, setCanvaWorkflow] = useState<CanvaCutoutWorkflow | undefined>(initialReadiness?.canva_cutout_workflow);
	const [canvaMethod, setCanvaMethod] = useState<CanvaMethod>("MAGIC_GRAB");
	const [canvaDesignId, setCanvaDesignId] = useState("");
	const [canvaDesignUrl, setCanvaDesignUrl] = useState("");
	const [canvaOperatorStage, setCanvaOperatorStage] = useState<(typeof CANVA_OPERATOR_STAGES)[number]>("OPENING_CANVA");
	const [canvaPreflight, setCanvaPreflight] = useState<Record<string, CanvaCapabilityStatus>>({
		login_status: "UNKNOWN",
		magic_grab_status: "UNKNOWN",
		background_remover_status: "UNKNOWN",
		magic_layers_status: "UNKNOWN",
		transparent_export_status: "UNKNOWN",
	});

	const busyLane: BusyLane | null = busy ? BUSY_LANE[busy] : null;

	useEffect(() => {
		setReadiness(initialReadiness);
		setCanvaWorkflow(initialReadiness?.canva_cutout_workflow);
		if (initialReadiness?.canva_cutout_workflow) {
			const workflow = initialReadiness.canva_cutout_workflow;
			if (workflow.canva_method && workflow.canva_method !== "UNSELECTED") setCanvaMethod(workflow.canva_method as CanvaMethod);
			setCanvaDesignId(workflow.design_id || "");
			setCanvaDesignUrl(workflow.design_url || "");
			if (CANVA_OPERATOR_STAGES.includes(workflow.current_stage as (typeof CANVA_OPERATOR_STAGES)[number])) setCanvaOperatorStage(workflow.current_stage as (typeof CANVA_OPERATOR_STAGES)[number]);
			setCanvaPreflight((workflow.preflight || {}) as Record<string, CanvaCapabilityStatus>);
		}
	}, [initialReadiness]);

	useEffect(() => {
		if (initialReadiness) return;
		let cancelled = false;
		void fetchProductVisualReadiness(productId)
			.then((next) => {
				if (!cancelled) setReadiness(next);
			})
			.catch((err: unknown) => {
				if (!cancelled) setError(err instanceof Error ? err.message : "Visual readiness unavailable");
			});
		return () => {
			cancelled = true;
		};
	}, [initialReadiness, productId]);

	async function refresh(action: "prepare" | "rebuild") {
		setBusy(action);
		setError(null);
		try {
			const next = action === "prepare"
				? await prepareProductCutout(productId)
				: await rebuildProductCutout(productId);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Visual preparation failed");
		} finally {
			setBusy(null);
		}
	}

	async function approve() {
		if (!reviewedBy.trim() || !reviewNote.trim() || !confirmIdentity || !confirmLabelLogo || !confirmGeometryScale || !confirmProductIsolation) {
			setError("Explicit reviewer identity, note, and all four confirmations are required.");
			return;
		}
		setBusy("approve");
		setError(null);
		try {
			await approveProductTruthLock(productId, {
				reviewed_by: reviewedBy.trim(),
				review_note: reviewNote.trim(),
				confirm_identity: confirmIdentity,
				confirm_label_logo: confirmLabelLogo,
				confirm_geometry_scale: confirmGeometryScale,
				confirm_product_isolation: confirmProductIsolation,
			});
			const next = await fetchProductVisualReadiness(productId);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Approval failed");
		} finally {
			setBusy(null);
		}
	}

	async function uploadManual(event: ChangeEvent<HTMLInputElement>) {
		const file = event.target.files?.[0];
		event.target.value = "";
		if (!file) return;
		if (file.type !== "image/png" || !file.name.toLowerCase().endsWith(".png")) {
			setError("Manual cutout override requires a PNG file with image/png MIME type.");
			return;
		}
		setBusy("upload");
		setError(null);
		try {
			const next = await uploadManualProductCutout(productId, file, reviewedBy.trim() || "operator");
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Manual cutout upload failed");
		} finally {
			setBusy(null);
		}
	}

	function applyCanvaEnvelope(envelope: { workflow: CanvaCutoutWorkflow; readiness: ProductVisualReadiness }) {
		setCanvaWorkflow(envelope.workflow);
		setReadiness(envelope.readiness);
		if (envelope.workflow.canva_method && envelope.workflow.canva_method !== "UNSELECTED") setCanvaMethod(envelope.workflow.canva_method as CanvaMethod);
		setCanvaDesignId(envelope.workflow.design_id || "");
		setCanvaDesignUrl(envelope.workflow.design_url || "");
		if (CANVA_OPERATOR_STAGES.includes(envelope.workflow.current_stage as (typeof CANVA_OPERATOR_STAGES)[number])) setCanvaOperatorStage(envelope.workflow.current_stage as (typeof CANVA_OPERATOR_STAGES)[number]);
		setCanvaPreflight((envelope.workflow.preflight || {}) as Record<string, CanvaCapabilityStatus>);
		onChanged?.(envelope.readiness);
	}

	async function saveCanvaStage() {
		setBusy("canva-stage");
		setError(null);
		try {
			applyCanvaEnvelope(await advanceCanvaStage(productId, {
				stage: canvaOperatorStage,
				canva_method: canvaMethod,
				design_id: canvaDesignId.trim() || undefined,
				design_url: canvaDesignUrl.trim() || undefined,
			}));
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Canva operator stage could not be saved");
		} finally {
			setBusy(null);
		}
	}

	async function startCanva() {
		setBusy("canva");
		setError(null);
		try {
			applyCanvaEnvelope(await startCanvaCutout(productId));
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Canva workflow could not start");
		} finally {
			setBusy(null);
		}
	}

	async function saveCanvaPreflight() {
		setBusy("canva-preflight");
		setError(null);
		try {
			applyCanvaEnvelope(await recordCanvaPreflight(productId, {
				canva_method: canvaMethod,
				design_id: canvaDesignId.trim() || undefined,
				design_url: canvaDesignUrl.trim() || undefined,
				login_status: canvaPreflight.login_status || "UNKNOWN",
				magic_grab_status: canvaPreflight.magic_grab_status || "UNKNOWN",
				background_remover_status: canvaPreflight.background_remover_status || "UNKNOWN",
				magic_layers_status: canvaPreflight.magic_layers_status || "UNKNOWN",
				transparent_export_status: canvaPreflight.transparent_export_status || "UNKNOWN",
			}));
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Canva preflight could not be saved");
		} finally {
			setBusy(null);
		}
	}

	async function uploadCanva(event: ChangeEvent<HTMLInputElement>) {
		const file = event.target.files?.[0];
		event.target.value = "";
		if (!file) return;
		if (file.type !== "image/png" || !file.name.toLowerCase().endsWith(".png")) {
			setError("Canva handoff requires an image/png transparent PNG export.");
			return;
		}
		setBusy("canva-upload");
		setError(null);
		try {
			applyCanvaEnvelope(await completeCanvaCutout(productId, file, {
				canva_method: canvaMethod,
				uploaded_by: reviewedBy.trim() || "operator",
				design_id: canvaDesignId.trim() || undefined,
				design_url: canvaDesignUrl.trim() || undefined,
			}));
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Canva PNG handoff failed");
		} finally {
			setBusy(null);
		}
	}

	async function reject() {
		const operator = reviewedBy.trim() || window.prompt("Reviewer identity")?.trim() || "";
		const reason = window.prompt("Why is this cutout rejected?")?.trim() || "";
		if (!operator || !reason) {
			setError("Reviewer identity and rejection reason are required.");
			return;
		}
		setBusy("reject");
		setError(null);
		try {
			const next = await rejectProductCutout(productId, operator, reason);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Cutout rejection failed");
		} finally {
			setBusy(null);
		}
	}

	async function fallback() {
		const operator = reviewedBy.trim() || window.prompt("Operator identity")?.trim() || "";
		const reason = window.prompt("Why use the original same-product fallback?")?.trim() || "";
		if (!operator || !reason) {
			setError("Operator identity and fallback reason are required.");
			return;
		}
		setBusy("fallback");
		setError(null);
		try {
			const next = await useOriginalProductFallback(productId, operator, reason);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Fallback selection failed");
		} finally {
			setBusy(null);
		}
	}

	async function saveTarget(roi: { x: number; y: number; width: number; height: number }) {
		setBusy("target-save");
		setError(null);
		try {
			const next = await setProductCutoutTarget(productId, { ...roi, selected_by: reviewedBy.trim() || "operator" });
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Product area could not be saved");
		} finally {
			setBusy(null);
		}
	}

	async function clearTarget() {
		setBusy("target-clear");
		setError(null);
		try {
			const next = await clearProductCutoutTarget(productId);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Product area could not be cleared");
		} finally {
			setBusy(null);
		}
	}

	if (!readiness) {
		return (
			<div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-[11px] text-slate-500">
				Loading product visual readiness…
			</div>
		);
	}

	const trustedSourceReason = readiness.canonical_media_status !== "AVAILABLE"
		? "Trusted same-product source must be prepared first."
		: "This action is unavailable in the current review state.";

	const cardBadges = computeCardBadges(readiness);
	const roiImageUrl = readiness.original_preview_url || productSourceUrl || null;
	const showProductArea = Boolean(roiImageUrl) && (readiness.target_selection_required || readiness.target_selection_available);

	const canvaController = Boolean(canvaWorkflow?.current_stage) && canvaWorkflow?.current_stage !== "NOT_STARTED";
	const canvaPreflightBlocked = Object.values(canvaWorkflow?.preflight ?? {}).some((value) => value === "UNAVAILABLE" || value === "USER_ACTION_REQUIRED");
	const canvaNeedsUserAction = !canvaController || canvaPreflightBlocked;

	const autoDisabled = !(readiness.can_prepare_cutout || readiness.can_rebuild_cutout);
	const candidateWriteBusy = busyLane === "auto" || busyLane === "manual" || busyLane === "canva";
	const allApprovalConfirms = confirmIdentity && confirmLabelLogo && confirmGeometryScale && confirmProductIsolation;

	const reasonFor = (lane: BusyLane, disabled: boolean, disabledReason: string): { text: string; tone: "muted" | "warn" | "ok" } => {
		if (busyLane === lane) return { text: "Processing…", tone: "warn" };
		if (disabled) return { text: disabledReason, tone: "muted" };
		return { text: "Ready", tone: "ok" };
	};
	const autoReason = reasonFor("auto", autoDisabled, trustedSourceReason);
	const manualReason = reasonFor("manual", !readiness.can_upload_manual_cutout, trustedSourceReason);
	const canvaReason = reasonFor("canva", !readiness.can_start_canva_cutout, trustedSourceReason);
	const fallbackReason = reasonFor("fallback", !readiness.can_use_original_fallback, trustedSourceReason);

	const reviewingCandidate =
		readiness.auto_cutout_status === "PENDING_REVIEW"
			? "Auto Cutout"
			: readiness.manual_cutout_status === "PENDING_REVIEW"
				? "Manual Cutout"
				: "Cutout";

	const csv = readiness.current_system_visual;
	const csvLabel = csv?.label || "Original Source";
	const autoPending = readiness.auto_cutout_status === "PENDING_REVIEW";
	const csvStatusLine =
		csv?.status === "OFFICIAL"
			? "Official cutout."
			: autoPending
				? "Auto cutout is waiting for review."
				: csv?.status === "ORIGINAL_FALLBACK"
					? "Original source is the current system reference."
					: csv?.status === "BLOCKED"
						? "No trusted product source yet."
						: "No cutout selected yet.";

	const approveReason =
		busyLane === "review"
			? "Processing…"
			: candidateWriteBusy
				? "Temporarily unavailable while candidate write is completing."
				: !allApprovalConfirms
					? "Confirm all four checks to approve as the official cutout."
					: "Ready to approve as the official cutout.";

	return (
		<div className={`min-w-0 max-w-full overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40 ${compact ? "p-2" : "p-5"}`} data-testid="product-visual-readiness">
			<div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
				<div className="min-w-0">
					<h3 className={`${compact ? "text-[10px]" : "text-sm"} font-bold uppercase tracking-widest text-white`}>
						{compact ? "Visual" : "PRODUCT VISUAL READINESS"}
					</h3>
					{!compact && (
						<p className="mt-1 text-[11px] text-slate-500">
							Same-product evidence only. Deterministic preparation is review-only; Exact Commerce remains fail-closed until approved.
						</p>
					)}
				</div>
				{readiness.provider_operations === 0 && (
					<span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-widest text-emerald-300">
						No provider spend
					</span>
				)}
			</div>

			<div className={`mt-3 grid gap-2 ${compact ? "grid-cols-2" : "grid-cols-2 md:grid-cols-4"}`}>
				<Status name="Reference" value={readiness.canonical_media_status} />
				<Status name="Cutout" value={readiness.cutout_status} />
				<Status name="Visual Ready" value={readiness.visual_grounding_status} />
				<Status name="Exact Commerce" value={readiness.exact_commerce_status} />
			</div>

			{!compact && (
				<div className="mt-3 rounded-lg border border-slate-800 bg-slate-900/60 p-3" data-testid="current-system-visual">
					<div className="text-[8px] font-bold uppercase tracking-widest text-slate-500">Current System Visual</div>
					<div className="mt-1 text-xs font-bold text-white">{csvLabel}</div>
					<div className="mt-0.5 text-[10px] text-slate-400">{csvStatusLine}</div>
				</div>
			)}

			{!compact && (
				<div className="mt-3 grid gap-2 md:grid-cols-3">
					<Status name="Auto Candidate" value={readiness.auto_cutout_status} />
					<Status name="Manual Candidate" value={readiness.manual_cutout_status} />
					<Status name="Active Source" value={readiness.active_visual_source} />
				</div>
			)}

			{!compact && (
				<div className="mt-4 grid gap-2 text-[10px] text-slate-400 md:grid-cols-2">
					<div>Source: <span className="text-slate-200">{label(readiness.visual_grounding_source)}</span></div>
					<div>Reference Pack: <span className="text-slate-200">{label(readiness.reference_pack_status)}</span></div>
					<div>Review: <span className="text-slate-200">{label(readiness.cutout_review_status)}</span></div>
					<div>Attempts: <span className="text-slate-200">{readiness.attempt_count ?? 0}</span></div>
				</div>
			)}

			{!compact && (
				<div className="mt-4 grid gap-3 md:grid-cols-3" data-testid="product-cutout-comparison">
					{([
						["Original Source", readiness.original_preview_url, "original", "card-badge-original"],
						["Auto Cutout", readiness.auto_cutout_preview_url, "auto", "card-badge-auto"],
						["Manual / Canva", readiness.manual_cutout_preview_url, "manual", "card-badge-manual"],
					] as const).map(([name, src, key, testid]) => (
						<div key={name} className="rounded-lg border border-slate-800 p-2">
							<div className="mb-1 text-[9px] font-bold uppercase tracking-widest text-slate-500">{name}</div>
							<CardBadges badges={cardBadges[key]} testid={testid} />
							<div className="mt-2 flex h-36 items-center justify-center rounded bg-white" style={{ backgroundImage: "linear-gradient(45deg,#d1d5db 25%,transparent 25%),linear-gradient(-45deg,#d1d5db 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#d1d5db 75%),linear-gradient(-45deg,transparent 75%,#d1d5db 75%)", backgroundSize: "16px 16px", backgroundPosition: "0 0,0 8px,8px -8px,-8px 0" }}>
								{src ? <img src={src} alt={`${name} cutout`} className="max-h-full max-w-full object-contain" /> : <span className="text-[10px] text-slate-500">Not available</span>}
							</div>
						</div>
					))}
				</div>
			)}

			{(readiness.blockers.length > 0 || readiness.warnings.length > 0) && !compact && (
				<div className="mt-3 space-y-1 text-[10px]">
					{[...readiness.blockers, ...readiness.warnings].slice(0, 4).map((item) => (
						<div key={item} className="text-amber-300">• {label(item)}</div>
					))}
				</div>
			)}

			{!compact && (
				<div className="mt-4 grid gap-3 md:grid-cols-3" data-testid="product-cutout-control-lanes">
					<section className="rounded-lg border border-slate-800 p-3" aria-label="Original source controls">
						<h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-200">Original Source</h4>
						<p className="mt-2 text-[10px] text-slate-500">{readiness.canonical_media_status === "AVAILABLE" ? "Trusted same-product source is available." : trustedSourceReason}</p>
						<div className="mt-3 flex flex-wrap gap-2">
							{productSourceUrl && readiness.can_open_source && (
								<a href={productSourceUrl} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()} className="rounded-lg bg-slate-800 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-300">Open Source</a>
							)}
							<button type="button" onClick={() => void fallback()} disabled={busyLane === "fallback" || !readiness.can_use_original_fallback} title={!readiness.can_use_original_fallback ? trustedSourceReason : undefined} className="rounded-lg bg-amber-500/20 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-amber-200 disabled:opacity-40">
								{busy === "fallback" ? "Selecting…" : "Use Original Fallback"}
							</button>
						</div>
						<ReasonLine testid="reason-fallback" tone={fallbackReason.tone}>{fallbackReason.text}</ReasonLine>
						{showProductArea && roiImageUrl && (
							<ProductAreaSelector
								imageUrl={roiImageUrl}
								target={readiness.target_region}
								busy={busyLane === "target"}
								onSave={(roi) => void saveTarget(roi)}
								onClear={() => void clearTarget()}
							/>
						)}
					</section>

					<section className="rounded-lg border border-slate-800 p-3" aria-label="Auto cutout controls">
						<h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-200">Auto Cutout</h4>
						<p className="mt-2 text-[10px] text-slate-500">{readiness.can_prepare_cutout ? "Local deterministic preparation is ready." : trustedSourceReason}</p>
						<div className="mt-3 flex flex-wrap gap-2">
							<button type="button" onClick={() => void refresh("prepare")} disabled={busyLane === "auto" || !readiness.can_prepare_cutout} title={!readiness.can_prepare_cutout ? trustedSourceReason : undefined} className="rounded-lg bg-indigo-600/80 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40">
								{busy === "prepare" ? "Preparing…" : "Prepare Auto Cutout"}
							</button>
							{readiness.cutout_status !== "NOT_PREPARED" && (
								<button type="button" onClick={() => void refresh("rebuild")} disabled={busyLane === "auto" || !readiness.can_rebuild_cutout} className="rounded-lg bg-slate-700 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-200 disabled:opacity-40">{busy === "rebuild" ? "Rebuilding…" : "Rebuild Auto Cutout"}</button>
							)}
						</div>
						<ReasonLine testid="reason-auto" tone={autoReason.tone}>{autoReason.text}</ReasonLine>
					</section>

					<section className="rounded-lg border border-slate-800 p-3" aria-label="Manual and Canva cutout controls">
						<h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-200">Manual / Canva Cutout</h4>
						<input ref={fileInputRef} type="file" accept="image/png,.png" onChange={(event) => void uploadManual(event)} className="hidden" />
						<div className="mt-3">
							<button type="button" onClick={() => fileInputRef.current?.click()} disabled={busyLane === "manual" || !readiness.can_upload_manual_cutout} title={!readiness.can_upload_manual_cutout ? trustedSourceReason : undefined} className="rounded-lg bg-fuchsia-600/80 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40">
								{busy === "upload" ? "Uploading…" : readiness.manual_cutout_status === "NOT_UPLOADED" ? "Upload My Cutout" : "Replace Manual Cutout"}
							</button>
							<ReasonLine testid="reason-manual" tone={manualReason.tone}>{manualReason.text}</ReasonLine>
						</div>
						<div className="mt-3 border-t border-slate-800 pt-3">
							<div className="flex flex-wrap items-center gap-2">
								<button type="button" onClick={() => void startCanva()} disabled={busyLane === "canva" || !readiness.can_start_canva_cutout} title={!readiness.can_start_canva_cutout ? trustedSourceReason : undefined} className="rounded-lg bg-violet-600/90 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40" data-testid="canva-cutout-button">
									{busy === "canva" ? "Starting Canva…" : canvaController ? "Continue in Canva" : "Canva Cutout"}
								</button>
								{canvaNeedsUserAction && (
									<span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-widest text-amber-300">USER ACTION REQUIRED</span>
								)}
							</div>
							<p className="mt-2 text-[9px] text-slate-400" data-testid="canva-helper">
								Assisted workflow. Complete the Canva edit/export, then return the transparent PNG to BOSMAX.
							</p>
							<ReasonLine testid="reason-canva" tone={canvaReason.tone}>{canvaReason.text}</ReasonLine>
						</div>
					</section>
				</div>
			)}

			{!compact && readiness.can_review_cutout && (
				<div className="mt-4 text-[10px]" data-testid="reviewing-candidate">
					<span className="font-bold uppercase tracking-widest text-amber-200">Reviewing: {reviewingCandidate}</span>
				</div>
			)}

			<div className="mt-4 flex min-w-0 flex-wrap items-center gap-2">
				{readiness.can_review_cutout && (
					<button type="button" onClick={onOpenReview} className="rounded-lg bg-amber-500/20 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-amber-200">
						Review
					</button>
				)}
				{readiness.can_reject_cutout && (
					<button type="button" onClick={() => void reject()} disabled={busyLane === "review"} className="rounded-lg bg-red-500/20 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-red-200 disabled:opacity-40">
						{busy === "reject" ? "Rejecting…" : "Reject Cutout"}
					</button>
				)}
				{readiness.active_cutout_preview_url && (
					<a href={readiness.active_cutout_preview_url} download className="rounded-lg bg-slate-800 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-300">Download Active Cutout</a>
				)}
			</div>

			{canvaWorkflow && canvaWorkflow.current_stage !== "NOT_STARTED" && (
				<div className="mt-4 min-w-0 rounded-lg border border-violet-500/30 bg-violet-500/5 p-3 text-[10px]" data-testid="canva-cutout-workflow">
					<div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
						<div className="min-w-0 break-words font-bold uppercase tracking-widest text-violet-200">Canva Cutout · {label(canvaWorkflow.current_stage)}</div>
						{canvaWorkflow.design_url && <a href={canvaWorkflow.design_url} target="_blank" rel="noreferrer" className="rounded bg-violet-500/20 px-2 py-1 font-bold uppercase tracking-widest text-violet-200">Open Canva Design</a>}
					</div>
					<p className="mt-2 break-words leading-relaxed text-slate-400">
						Canva editing is operator/browser-controller work. BOSMAX records source identity, verifies alpha, and sends the PNG into the existing manual review lane; it does not store Canva cookies or auto-approve.
					</p>
					<div className={`mt-3 grid min-w-0 gap-2 ${compact ? "grid-cols-1 sm:grid-cols-2" : "md:grid-cols-3"}`}>
						<label className="text-slate-400">Method
							<select value={canvaMethod} onChange={(event) => setCanvaMethod(event.target.value as CanvaMethod)} className="mt-1 min-w-0 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-slate-200">
								<option value="MAGIC_GRAB">Magic Grab</option>
								<option value="BACKGROUND_REMOVER">Background Remover</option>
								<option value="MAGIC_LAYERS">Magic Layers</option>
							</select>
						</label>
						<label className="text-slate-400">Design ID
							<input value={canvaDesignId} onChange={(event) => setCanvaDesignId(event.target.value)} placeholder="Optional" className="mt-1 min-w-0 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-slate-200" />
						</label>
						<label className="text-slate-400">Design URL
							<input value={canvaDesignUrl} onChange={(event) => setCanvaDesignUrl(event.target.value)} placeholder="https://www.canva.com/design/..." className="mt-1 min-w-0 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-slate-200" />
						</label>
					</div>
					<div className={`mt-3 grid min-w-0 gap-2 ${compact ? "grid-cols-1 sm:grid-cols-2" : "md:grid-cols-5"}`}>
						{CANVA_PREFLIGHT_FIELDS.map(([key, name]) => (
							<label key={key} className="text-slate-400">{name}
								<select value={canvaPreflight[key] || "UNKNOWN"} onChange={(event) => setCanvaPreflight((previous) => ({ ...previous, [key]: event.target.value as CanvaCapabilityStatus }))} className="mt-1 min-w-0 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-[9px] text-slate-200">
									{CANVA_PREFLIGHT_OPTIONS.map((option) => <option key={option} value={option}>{option.replace(/_/g, " ")}</option>)}
								</select>
							</label>
						))}
					</div>
					<div className="mt-3 flex flex-wrap items-center gap-2">
						<button type="button" onClick={() => void saveCanvaPreflight()} disabled={busyLane === "canva"} className="rounded bg-violet-600/80 px-2.5 py-1.5 font-bold uppercase tracking-widest text-white disabled:opacity-40">
							{busy === "canva-preflight" ? "Saving preflight…" : "Save Canva Preflight"}
						</button>
						<input ref={canvaFileInputRef} type="file" accept="image/png,.png" onChange={(event) => void uploadCanva(event)} className="hidden" />
						<button type="button" onClick={() => canvaFileInputRef.current?.click()} disabled={busyLane === "canva" || canvaWorkflow.current_stage === "CANVA_PRO_REQUIRED"} className="rounded bg-fuchsia-600/80 px-2.5 py-1.5 font-bold uppercase tracking-widest text-white disabled:opacity-40">
							{busy === "canva-upload" ? "Verifying PNG…" : "Upload Canva PNG → Manual Review"}
						</button>
						<label className="text-slate-400">Operator stage
							<select value={canvaOperatorStage} onChange={(event) => setCanvaOperatorStage(event.target.value as (typeof CANVA_OPERATOR_STAGES)[number])} className="ml-2 rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-[9px] text-slate-200">
								{CANVA_OPERATOR_STAGES.map((stage) => <option key={stage} value={stage}>{stage.replace(/_/g, " ")}</option>)}
							</select>
						</label>
						<button type="button" onClick={() => void saveCanvaStage()} disabled={busyLane === "canva" || canvaWorkflow.current_stage === "CANVA_PRO_REQUIRED"} className="rounded bg-slate-700 px-2.5 py-1.5 font-bold uppercase tracking-widest text-slate-200 disabled:opacity-40">
							{busy === "canva-stage" ? "Saving stage…" : "Record Operator Stage"}
						</button>
						<span className="text-slate-500">Alpha verified: <span className={canvaWorkflow.alpha_verified ? "text-emerald-300" : "text-amber-300"}>{canvaWorkflow.alpha_verified ? "YES" : "NO"}</span></span>
					</div>
					{canvaWorkflow.current_stage === "CANVA_PRO_REQUIRED" && <div className="mt-2 text-amber-300">CANVA_PRO_REQUIRED — no editing/export workflow is started until transparent PNG entitlement is available.</div>}
					{canvaWorkflow.last_error && <div className="mt-2 text-red-300">{canvaWorkflow.last_error_code ? `${canvaWorkflow.last_error_code}: ` : ""}{canvaWorkflow.last_error}</div>}
				</div>
			)}

			{showApprovalForm && readiness.can_review_cutout && (
				<div className="mt-5 border-t border-slate-800 pt-4" data-testid="product-visual-approval">
					<div className="mb-2 text-[10px] font-bold uppercase tracking-widest text-amber-200" data-testid="reviewing-candidate-approval">Reviewing: {reviewingCandidate}</div>
					<div className="mb-3 flex flex-wrap items-start gap-4">
						{readiness.cutout_preview_available && (
							<img src={readiness.active_cutout_preview_url || productTruthCutoutPreviewUrl(productId)} alt="Deterministic cutout candidate" className="h-32 w-32 rounded-lg border border-slate-700 bg-white object-contain" />
						)}
						<div className="flex-1 text-[10px] leading-relaxed text-amber-200">
							This candidate is not approved. Inspect identity, label/logo, geometry, scale, product isolation, and source lineage. Approve as Official Cutout applies to the active candidate, including a Canva handoff, only after explicit human confirmation.
						</div>
					</div>
					<div className="grid gap-2 md:grid-cols-2">
						<input value={reviewedBy} onChange={(event) => setReviewedBy(event.target.value)} placeholder="Reviewer identity" className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white" />
						<input value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="Review note" className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white" />
					</div>
					<div className="mt-3 grid gap-2 text-[10px] text-slate-300 md:grid-cols-2">
						<label><input type="checkbox" checked={confirmIdentity} onChange={(event) => setConfirmIdentity(event.target.checked)} className="mr-1" /> Identity</label>
						<label><input type="checkbox" checked={confirmLabelLogo} onChange={(event) => setConfirmLabelLogo(event.target.checked)} className="mr-1" /> Label / logo</label>
						<label><input type="checkbox" checked={confirmGeometryScale} onChange={(event) => setConfirmGeometryScale(event.target.checked)} className="mr-1" /> Geometry / scale</label>
						<label><input type="checkbox" data-testid="confirm-product-isolation" checked={confirmProductIsolation} onChange={(event) => setConfirmProductIsolation(event.target.checked)} className="mr-1" /> Product only — no unrelated props, food, decoration, or secondary objects remain</label>
					</div>
					<button type="button" onClick={() => void approve()} disabled={busyLane === "review" || candidateWriteBusy || !reviewedBy.trim() || !reviewNote.trim() || !allApprovalConfirms} className="mt-3 rounded-lg bg-emerald-600/80 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40">
						{busy === "approve" ? "Approving…" : "Approve as Official Cutout"}
					</button>
					<ReasonLine testid="reason-approve" tone={busyLane === "review" ? "warn" : allApprovalConfirms && !candidateWriteBusy ? "ok" : "muted"}>{approveReason}</ReasonLine>
				</div>
			)}

			{!compact && (
				<details className="mt-4 text-[10px] text-slate-500">
					<summary className="cursor-pointer font-bold uppercase tracking-widest">Advanced / History</summary>
					<div className="mt-2 grid gap-1">
						<div>Preserved candidates: {readiness.cutout_history_count ?? 0}</div>
						<div>Attempts: {readiness.attempt_count ?? 0}</div>
						{readiness.file_quality_status && <div>File quality: {label(readiness.file_quality_status)}</div>}
						{readiness.product_isolation_status && <div>Isolation: {label(readiness.product_isolation_status)}</div>}
						{readiness.target_region && (
							<div>Product target: x {readiness.target_region.x}, y {readiness.target_region.y}, w {readiness.target_region.width}, h {readiness.target_region.height} (source px)</div>
						)}
					</div>
				</details>
			)}

			{error && <div className="mt-3 text-[10px] text-red-300">{error}</div>}
		</div>
	);
}
