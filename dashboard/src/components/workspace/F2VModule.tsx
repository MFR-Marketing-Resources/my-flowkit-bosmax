import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { handleAssetUpload } from "../../api/assets";
import { fetchCreativeAssetEligibilityAudit } from "../../api/creativeAssets";
import { resolveF2vFrameSources } from "../../api/imgFactory";
import type {
	CreativeAsset,
	CreativeAssetEligibilityAuditResponse,
	Orientation,
	UploadedAsset,
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
} from "../../types";
import CopyBindingGate from "../copywriting/CopyBindingGate";
import WorkspaceImageAssetSlot from "./WorkspaceImageAssetSlot";

// IMG Asset Factory bridge: a saved COMPOSITE_FRAME_REFERENCE asset can feed an
// F2V start/end frame. Posters (rendered text) + archived assets are excluded by
// the backend gate; this only surfaces ACTIVE, F2V-eligible composites.
function compositeToUploadedAsset(asset: CreativeAsset): UploadedAsset {
	return {
		mediaId: asset.media_id ?? null,
		fileName: asset.display_name,
		label: `${asset.display_name} (composite frame)`,
		previewUrl: asset.preview_url ?? undefined,
		downloadUrl: asset.download_url ?? undefined,
		localFilePath: asset.local_file_path ?? undefined,
		assetId: asset.asset_id,
		assetFingerprint: `composite:${asset.asset_id}`,
		assetSource: "CREATIVE_LIBRARY_COMPOSITE",
		isDefaultPackageAsset: false,
		previewRenderableStatus: asset.preview_url ? "READY" : "NOT_AVAILABLE",
		previewErrorDetail: null,
		localImagePathPresent: Boolean(asset.local_file_path),
		remoteImageUrlPresent: Boolean(asset.remote_source_url),
	};
}

interface F2VModuleProps {
	onExecute: (data: WorkspaceExecutePayload) => void;
	isExecuting: boolean;
	compact?: boolean;
	workspacePackage?: WorkspaceExecutionPackage | null;
	copyReady?: boolean;
	surfaceMode?: "F2V" | "HYBRID";
}

const CANONICAL_PROMPT_SECTIONS = [
	"SECTION 1 - ROLE & OBJECTIVE",
	"SECTION 2 - PRODUCT TRUTH LOCK",
	"SECTION 3 - CONTINUITY & STATE LOCK",
	"SECTION 4 - VISUAL STORY",
	"SECTION 5 - SHOT & CAMERA RULES",
	"SECTION 6 - SPOKEN DIALOGUE",
	"SECTION 7 - VOICE & DELIVERY",
	"SECTION 8 - CTA & END FRAME",
	"SECTION 9 - NO_OVERLAY",
] as const;

type PromptAuditBlock = NonNullable<
	WorkspaceExecutionPackage["prompt_blocks"]
>[number];

interface PromptAuditSection {
	heading: string;
	sectionNumber: number | null;
	title: string;
	body: string;
}

function parsePromptSections(text: string): PromptAuditSection[] {
	const normalized = (text ?? "").replace(/\r\n/g, "\n");
	const matches = [...normalized.matchAll(/^SECTION [1-9] - .+$/gm)];
	if (matches.length === 0) {
		return [];
	}

	return matches.map((match, index) => {
		const heading = match[0].trim();
		const start = (match.index ?? 0) + match[0].length;
		const end =
			index + 1 < matches.length
				? (matches[index + 1].index ?? normalized.length)
				: normalized.length;
		const sectionNumberMatch = heading.match(/^SECTION (\d+)/);
		return {
			heading,
			sectionNumber: sectionNumberMatch ? Number(sectionNumberMatch[1]) : null,
			title: heading.replace(/^SECTION \d+ - /, ""),
			body: normalized.slice(start, end).trim(),
		};
	});
}

function PromptAuditCard({
	label,
	text,
	block,
}: {
	label: string;
	text: string;
	block?: PromptAuditBlock;
}) {
	const [copied, setCopied] = useState(false);
	const sections = parsePromptSections(text);
	const presentHeadings = new Set(sections.map((section) => section.heading));
	const missingSections = CANONICAL_PROMPT_SECTIONS.filter(
		(heading) => !presentHeadings.has(heading),
	);
	const metaChips = [
		block?.block_role ? `Role ${block.block_role}` : null,
		block?.duration_seconds ? `${block.duration_seconds}s` : null,
		block?.shot_count
			? `${block.shot_count} shot${block.shot_count > 1 ? "s" : ""}`
			: null,
	].filter(Boolean) as string[];

	const handleCopy = () => {
		navigator.clipboard.writeText(text || "").then(() => {
			setCopied(true);
			window.setTimeout(() => setCopied(false), 2200);
		});
	};

	return (
		<div className="rounded-xl border border-slate-800 bg-slate-950/70 overflow-hidden">
			<div className="flex flex-col gap-3 border-b border-slate-800 px-4 py-3 md:flex-row md:items-start md:justify-between">
				<div className="space-y-2">
					<div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-200">
						{label}
					</div>
					<div className="flex flex-wrap gap-2">
						<span className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">
							{sections.length}/9 sections
						</span>
						{metaChips.map((chip) => (
							<span
								key={chip}
								className="rounded-full border border-slate-800 bg-slate-900/70 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
							>
								{chip}
							</span>
						))}
						{missingSections.length === 0 ? (
							<span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-200">
								Canonical 9-section structure
							</span>
						) : (
							<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-200">
								Missing{" "}
								{missingSections
									.map((heading) => heading.replace("SECTION ", "S"))
									.join(", ")}
							</span>
						)}
					</div>
				</div>
				<button
					type="button"
					onClick={handleCopy}
					className={`rounded-lg border px-3 py-2 text-[11px] font-semibold transition-colors ${copied ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-blue-500/30 bg-blue-500/10 text-blue-100 hover:bg-blue-500/20"}`}
				>
					{copied ? "Copied" : "Copy Prompt"}
				</button>
			</div>
			{sections.length > 0 ? (
				<div className="divide-y divide-slate-800">
					{sections.map((section) => (
						<details
							key={section.heading}
							open={
								section.sectionNumber === 4 ||
								section.sectionNumber === 6 ||
								section.sectionNumber === 8
							}
							className="group"
						>
							<summary className="cursor-pointer list-none px-4 py-3">
								<div className="flex items-center justify-between gap-3">
									<div className="flex items-center gap-2">
										<span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">
											S{section.sectionNumber ?? "?"}
										</span>
										<span className="text-xs font-semibold text-slate-100">
											{section.title}
										</span>
									</div>
									<span className="text-[10px] uppercase tracking-[0.16em] text-slate-500 group-open:text-slate-300">
										Expand
									</span>
								</div>
							</summary>
							<pre className="border-t border-slate-800 px-4 py-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed">
								{section.body || "(empty section)"}
							</pre>
						</details>
					))}
				</div>
			) : (
				<pre className="px-4 py-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed">
					{text || "(no prompt text)"}
				</pre>
			)}
		</div>
	);
}

const FRAME_AUDIT_REASON_LABELS: Array<{
	key: string;
	label: string;
	className: string;
}> = [
	{
		key: "NOT_APPROVED_FOR_REUSE",
		label: "Pending / rejected",
		className: "border-amber-500/30 bg-amber-500/10 text-amber-200",
	},
	{
		key: "RENDERED_TEXT_NOT_ALLOWED_FOR_VIDEO_FRAME",
		label: "Poster excluded",
		className: "border-rose-500/30 bg-rose-500/10 text-rose-200",
	},
	{
		key: "ENGINE_SLOT_NOT_ALLOWED",
		label: "Wrong slot",
		className: "border-purple-500/30 bg-purple-500/10 text-purple-200",
	},
	{
		key: "MODE_NOT_ALLOWED",
		label: "Wrong mode",
		className: "border-sky-500/30 bg-sky-500/10 text-sky-200",
	},
	{
		key: "SEMANTIC_ROLE_MISMATCH",
		label: "Wrong role",
		className: "border-slate-700 bg-slate-900 text-slate-300",
	},
	{
		key: "ASSET_ARCHIVED",
		label: "Archived",
		className: "border-slate-700 bg-slate-900 text-slate-300",
	},
	{
		key: "PREVIEW_OR_FILE_MISSING",
		label: "Source missing",
		className: "border-red-500/30 bg-red-500/10 text-red-200",
	},
];

function getFramePickerPlaceholder(
	audit: CreativeAssetEligibilityAuditResponse | null,
	error: string | null,
	label: "START" | "END",
) {
	if (error) return `API fetch failed — refresh ${label} eligibility audit`;
	if (!audit) return `Loading ${label} eligibility audit…`;
	if (audit.eligible_count > 0) return `Pick composite ${label} frame…`;
	if (audit.library_total_count === 0)
		return "No Creative Library assets found";
	return `Assets found but none eligible for ${label} frame`;
}

function renderFrameAuditCard(
	label: "START" | "END",
	audit: CreativeAssetEligibilityAuditResponse | null,
	error: string | null,
) {
	if (error) {
		return (
			<div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[10px] text-red-200">
				<div className="font-bold uppercase tracking-[0.16em]">
					{label} Audit
				</div>
				<div className="mt-1">API fetch failed: {error}</div>
			</div>
		);
	}
	if (!audit) {
		return (
			<div className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 text-[10px] text-slate-400">
				<div className="font-bold uppercase tracking-[0.16em]">
					{label} Audit
				</div>
				<div className="mt-1">Loading eligibility audit…</div>
			</div>
		);
	}
	const pendingCount = audit.review_status_counts.PENDING_REVIEW ?? 0;
	const chips = FRAME_AUDIT_REASON_LABELS.filter(
		(reason) => (audit.excluded_by_reason[reason.key] ?? 0) > 0,
	);
	const summary =
		audit.library_total_count === 0
			? "No Creative Library assets found."
			: audit.eligible_count === 0
				? "Assets found but none are eligible for this surface."
				: `${audit.eligible_count} asset${audit.eligible_count === 1 ? "" : "s"} currently selectable.`;
	return (
		<div className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 text-[10px] text-slate-300">
			<div className="font-bold uppercase tracking-[0.16em] text-slate-200">
				{label} Audit
			</div>
			<div className="mt-1">
				Library has {audit.library_total_count} assets; {audit.eligible_count}{" "}
				eligible for this surface; {audit.excluded_count} excluded.
			</div>
			<div className="mt-1 text-slate-400">{summary}</div>
			<div className="mt-2 flex flex-wrap gap-1.5">
				<span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-300">
					Role pool {audit.matching_role_total_count}
				</span>
				<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-amber-200">
					Pending approval {pendingCount}
				</span>
				{chips.map((chip) => (
					<span
						key={chip.key}
						className={`rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] ${chip.className}`}
					>
						{chip.label} {audit.excluded_by_reason[chip.key]}
					</span>
				))}
			</div>
			{audit.eligible_count === 0 && audit.matching_role_total_count > 0 ? (
				<div className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-amber-100">
					<div>
						Composite frames found but none are eligible for this surface.
						Review or fix them in the Creative Library — approval is only one
						gate (role, mode, slot, rendered-text and source must also pass).
					</div>
					<a
						href="/assets/creative-library"
						className="mt-1 inline-flex items-center gap-1 rounded border border-amber-400/40 bg-amber-400/10 px-2 py-0.5 text-[10px] font-semibold text-amber-100 hover:bg-amber-400/20"
					>
						Open Creative Library review →
					</a>
				</div>
			) : null}
		</div>
	);
}

async function fetchFrameEligibilityAudits(surfaceMode: "F2V" | "HYBRID") {
	return Promise.allSettled([
		fetchCreativeAssetEligibilityAudit({
			surface:
				surfaceMode === "HYBRID"
					? "HYBRID_START_FRAME_PICKER"
					: "F2V_START_FRAME_PICKER",
		}),
		fetchCreativeAssetEligibilityAudit({
			surface:
				surfaceMode === "HYBRID"
					? "HYBRID_END_FRAME_PICKER"
					: "F2V_END_FRAME_PICKER",
		}),
	]);
}

function toUploadedAsset(
	asset:
		| WorkspaceExecutionPackage["resolved_assets"][number]
		| null
		| undefined,
): UploadedAsset | null {
	if (!asset) return null;
	return {
		mediaId: asset.media_id ?? null,
		fileName: asset.file_name,
		label: asset.label,
		previewUrl: asset.preview_url,
		downloadUrl: asset.download_url,
		localFilePath: asset.local_file_path ?? undefined,
		assetId: asset.asset_id,
		assetFingerprint: asset.asset_fingerprint,
		assetSource: asset.asset_source,
		isDefaultPackageAsset: true,
		previewRenderableStatus: asset.preview_renderable_status,
		previewErrorDetail: asset.preview_error_detail ?? null,
		localImagePathPresent: asset.local_image_path_present,
		remoteImageUrlPresent: asset.remote_image_url_present,
	};
}

export default function F2VModule({
	onExecute,
	isExecuting,
	compact = false,
	workspacePackage = null,
	copyReady = false,
	surfaceMode = "F2V",
}: F2VModuleProps) {
	// --- States ---
	const [manualPrompt, setManualPrompt] = useState("");
	const [isManualOverride, setIsManualOverride] = useState(false);
	const [copyFallbackConfirmed, setCopyFallbackConfirmed] = useState(false);
	const [orientation, setOrientation] = useState<Orientation>("VERTICAL");
	const [count, setCount] = useState(1);
	const [isUploading, setIsUploading] = useState(false);
	const [startPreviewFailed, setStartPreviewFailed] = useState(false);
	const packagePromptText =
		workspacePackage?.prompt_blocks?.[0]?.engine_prompt_text ??
		workspacePackage?.prompt_text ??
		"";

	// Frame Assets
	const [startAsset, setStartAsset] = useState<UploadedAsset | null>(null);
	const [endAsset, setEndAsset] = useState<UploadedAsset | null>(null);

	// IMG Asset Factory bridge: use the backend eligibility audit as the single
	// truthful source for the frame pickers, including HYBRID (same F2V rules).
	const [startFrameAudit, setStartFrameAudit] =
		useState<CreativeAssetEligibilityAuditResponse | null>(null);
	const [endFrameAudit, setEndFrameAudit] =
		useState<CreativeAssetEligibilityAuditResponse | null>(null);
	const [startFrameAuditError, setStartFrameAuditError] = useState<
		string | null
	>(null);
	const [endFrameAuditError, setEndFrameAuditError] = useState<string | null>(
		null,
	);
	const [isRefreshingAudit, setIsRefreshingAudit] = useState(false);
	const startCompositeAssets = startFrameAudit?.eligible_assets ?? [];
	const endCompositeAssets = endFrameAudit?.eligible_assets ?? [];

	const refreshEligibilityAudit = async () => {
		setIsRefreshingAudit(true);
		const [startResult, endResult] =
			await fetchFrameEligibilityAudits(surfaceMode);
		if (startResult.status === "fulfilled") {
			setStartFrameAudit(startResult.value);
			setStartFrameAuditError(null);
		} else {
			setStartFrameAudit(null);
			setStartFrameAuditError(
				startResult.reason instanceof Error
					? startResult.reason.message
					: "Unknown audit failure",
			);
		}
		if (endResult.status === "fulfilled") {
			setEndFrameAudit(endResult.value);
			setEndFrameAuditError(null);
		} else {
			setEndFrameAudit(null);
			setEndFrameAuditError(
				endResult.reason instanceof Error
					? endResult.reason.message
					: "Unknown audit failure",
			);
		}
		setIsRefreshingAudit(false);
	};

	useEffect(() => {
		let cancelled = false;
		const run = async () => {
			setIsRefreshingAudit(true);
			const [startResult, endResult] =
				await fetchFrameEligibilityAudits(surfaceMode);
			if (cancelled) return;
			if (startResult.status === "fulfilled") {
				setStartFrameAudit(startResult.value);
				setStartFrameAuditError(null);
			} else {
				setStartFrameAudit(null);
				setStartFrameAuditError(
					startResult.reason instanceof Error
						? startResult.reason.message
						: "Unknown audit failure",
				);
			}
			if (endResult.status === "fulfilled") {
				setEndFrameAudit(endResult.value);
				setEndFrameAuditError(null);
			} else {
				setEndFrameAudit(null);
				setEndFrameAuditError(
					endResult.reason instanceof Error
						? endResult.reason.message
						: "Unknown audit failure",
				);
			}
			setIsRefreshingAudit(false);
		};
		void run();
		return () => {
			cancelled = true;
		};
	}, [surfaceMode]);

	// Every composite selection is validated by the backend F2V resolver, which
	// enforces role + ACTIVE + F2V + APPROVED + rendered-text/poster exclusion. A
	// rejected selection is NOT applied to the frame.
	const handlePickComposite = async (
		assetId: string,
		slot: "start" | "end",
	) => {
		if (!assetId) return;
		const sourceAssets =
			slot === "start" ? startCompositeAssets : endCompositeAssets;
		const asset = sourceAssets.find((c) => c.asset_id === assetId);
		if (!asset) return;
		try {
			const response = await resolveF2vFrameSources(
				slot === "start"
					? { start_frame_asset_id: assetId }
					: {
							end_frame_asset_id: assetId,
							start_frame_manual_upload_present: true,
						},
			);
			const prefix = slot === "start" ? "START_FRAME_" : "END_FRAME_";
			if (response.blockers.some((b) => b.startsWith(prefix))) {
				alert(
					`Composite ${slot} frame rejected by the F2V resolver: ${response.blockers.join(", ")}`,
				);
				return;
			}
			if (slot === "start") setStartAsset(compositeToUploadedAsset(asset));
			else setEndAsset(compositeToUploadedAsset(asset));
		} catch {
			alert("Failed to validate the composite frame via the F2V resolver.");
		}
	};

	useEffect(() => {
		if (workspacePackage?.mode !== "F2V") return;
		setManualPrompt(workspacePackage.prompt_text);
		setOrientation(
			workspacePackage.aspect_ratio === "16:9" ? "HORIZONTAL" : "VERTICAL",
		);
		setStartAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find(
					(asset) => asset.slot_key === "start_frame",
				),
			),
		);
		setEndAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find(
					(asset) => asset.slot_key === "end_frame",
				),
			),
		);
		setIsManualOverride(false);
		setStartPreviewFailed(false);
	}, [workspacePackage]);

	// --- Handlers ---
	const handleFileChange = async (
		type: "start" | "end",
		e: React.ChangeEvent<HTMLInputElement>,
	) => {
		const file = e.target.files?.[0];
		if (!file) return;

		setIsUploading(true);
		try {
			console.log(`[F2V] Uploading ${type} to agent...`);
			const asset = await handleAssetUpload(file);
			console.log(`[F2V] Upload success:`, asset.mediaId);

			if (type === "start") {
				setStartAsset(asset);
				setStartPreviewFailed(false);
			} else setEndAsset(asset);
			setIsManualOverride(Boolean(workspacePackage));
		} catch (error: unknown) {
			const message = error instanceof Error ? error.message : "Unknown error";
			console.error(`[F2V] ${type} upload failed:`, error);
			alert(`UPLOAD ERROR: ${message}. Check your agent.`);
		} finally {
			setIsUploading(false);
		}
	};

	// --- Copywriting binding gate (Phase B enforcement; also covers HYBRID, which
	// reuses this module) --- F2V does not rebuild on execute, so the run is
	// copy-bound ONLY when the loaded package was compiled from an approved Copy Set.
	// Otherwise SEND stays blocked until the operator explicitly confirms fallback.
	const boundCopySetId =
		workspacePackage?.copy_binding?.copy_source === "selected_copy_set"
			? (workspacePackage?.copy_binding?.copy_set_id ?? null)
			: null;
	const copyBound = Boolean(boundCopySetId);
	const copyGateBlocked = !copyBound && !copyFallbackConfirmed;

	const handleExecute = () => {
		if (copyGateBlocked) return;
		// Dispatch through the Google Flow V2 runtime lane
		// (GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE): auto-acquire a healthy V2 surface,
		// then Upload media -> Add to Prompt -> Settings -> Prompt and STOP before
		// Generate. The backend still materializes the remote Start image to a local
		// file for the CDP file chooser (lane recognised by flow.py).
		onExecute({
			lane: "GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE",
			gfv2: true,
			prompt: manualPrompt,
			orientation,
			count,
			// Pass the full asset object (including previewUrl/base64) so extension can use it directly
			startAsset: startAsset,
			endAsset: endAsset,
			product_id: workspacePackage?.product_id,
			prompt_package_snapshot_id: workspacePackage?.prompt_package_snapshot_id,
			workspace_execution_package_id:
				workspacePackage?.workspace_execution_package_id,
			prompt_fingerprint: workspacePackage?.prompt_fingerprint,
			asset_fingerprints:
				workspacePackage?.request_lineage_payload.asset_fingerprints ?? [],
			copy_set_id: copyBound ? boundCopySetId : null,
			copy_fallback_confirmed: copyBound ? false : copyFallbackConfirmed,
			request_lineage_payload: {
				...(workspacePackage?.request_lineage_payload ?? {}),
				copy_binding_gate: copyBound
					? { copy_bound: true, copy_set_id: boundCopySetId }
					: {
							copy_bound: false,
							copy_fallback_confirmed: true,
							copy_source: "operator_confirmed_fallback",
						},
			},
			mode: "F2V",
		});
	};

	// Shared composite-frame picker (Creative Library COMPOSITE_FRAME_REFERENCE).
	// Rendered inline/primary for F2V; demoted into a collapsed advanced-override
	// for HYBRID. Single source so the eligibility audit cards, the "Open Creative
	// Library review" CTA (PR #291), and the resolver-truth caption are preserved
	// verbatim in both surfaces.
	const compositePicker = (
		<div className="mb-3 rounded-xl border border-slate-800 bg-slate-950/40 p-3 space-y-2">
			<div className="flex items-center justify-between gap-3">
				<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
					Or pick a saved composite frame from the Creative Library
				</div>
				<button
					type="button"
					onClick={() => void refreshEligibilityAudit()}
					disabled={isRefreshingAudit}
					className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-[10px] font-semibold text-slate-200 hover:bg-slate-800 disabled:opacity-50"
				>
					{isRefreshingAudit ? "Refreshing…" : "Refresh eligibility"}
				</button>
			</div>
			{surfaceMode === "HYBRID" ? (
				<div className="rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-[10px] text-blue-100">
					Hybrid uses F2V frame eligibility.
				</div>
			) : null}
			<div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
				<div className="space-y-2">
					<select
						value=""
						onChange={(e) => void handlePickComposite(e.target.value, "start")}
						className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
					>
						<option value="">
							{getFramePickerPlaceholder(
								startFrameAudit,
								startFrameAuditError,
								"START",
							)}
						</option>
						{startCompositeAssets.map((c) => (
							<option key={c.asset_id} value={c.asset_id}>
								{c.display_name}
							</option>
						))}
					</select>
					{renderFrameAuditCard("START", startFrameAudit, startFrameAuditError)}
				</div>
				<div className="space-y-2">
					<select
						value=""
						onChange={(e) => void handlePickComposite(e.target.value, "end")}
						className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
					>
						<option value="">
							{getFramePickerPlaceholder(
								endFrameAudit,
								endFrameAuditError,
								"END",
							)}
						</option>
						{endCompositeAssets.map((c) => (
							<option key={c.asset_id} value={c.asset_id}>
								{c.display_name}
							</option>
						))}
					</select>
					{renderFrameAuditCard("END", endFrameAudit, endFrameAuditError)}
				</div>
			</div>
			<p className="text-[9px] text-slate-500">
				COMPOSITE_FRAME_REFERENCE assets only. The backend audit mirrors the
				resolver truth: approval, slot, mode, rendered-text poster, archive, and
				missing-source gates all fail closed here.
			</p>
		</div>
	);

	return (
		<div
			className={`space-y-6 ${compact ? "" : "xl:grid xl:grid-cols-[minmax(0,1fr)_18rem] xl:items-start xl:gap-6 xl:space-y-0"}`}
		>
			<div className="space-y-6 pb-12">
				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						{surfaceMode === "HYBRID"
							? "1. Product Anchor + AI Presenter"
							: "1. Visual Assets (F2V Slots)"}
					</h3>
					{surfaceMode === "HYBRID" ? (
						<div className="grid gap-3">
							<div className="rounded-xl border border-blue-500/20 bg-blue-500/5 px-3 py-3 text-[11px] text-blue-200/70 space-y-1">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-blue-300/80">
									HYBRID — Product + AI Presenter
								</div>
								<p>
									<strong className="text-blue-200">
										No composite frame is required.
									</strong>{" "}
									The selected product image / product truth is used as the
									product anchor. AI presenter/avatar behaviour is generated by
									the prompt compiler.
								</p>
							</div>
							{workspacePackage ? (
								<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-3 text-[11px] text-emerald-100 space-y-1.5">
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-200/80">
										Auto Product Anchor
									</div>
									<ul className="list-disc list-inside space-y-0.5">
										<li>
											Product:{" "}
											<strong className="text-emerald-200">
												{workspacePackage.product_name}
											</strong>
										</li>
										<li>
											Product truth locked (Section 2 — Product Truth Lock).
										</li>
										<li>
											Product image resolved by package → default Start-Frame
											anchor.
										</li>
										<li>
											AI presenter/avatar behaviour generated by the prompt
											compiler
											{workspacePackage.character_presence
												? ` (presence: ${workspacePackage.character_presence}${
														workspacePackage.creator_persona
															? `, persona: ${workspacePackage.creator_persona}`
															: ""
													})`
												: ""}
											.
										</li>
									</ul>
								</div>
							) : (
								<div className="rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-3 text-[11px] text-slate-300">
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
										Select a product to arm the anchor
									</div>
									<div className="mt-1">
										Choose a product and load its approved package — the
										product image/truth becomes the anchor automatically. No
										composite frame is required.
									</div>
								</div>
							)}
						</div>
					) : (
						<div className="grid gap-3">
							<div className="rounded-xl border border-blue-500/20 bg-blue-500/5 px-3 py-3 text-[11px] text-blue-200/70 space-y-1">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-blue-300/80">
									F2V — Reference Image Logic
								</div>
								<p>
									Every image uploaded here becomes a{" "}
									<strong className="text-blue-200">reference image</strong>. The
									model SEES the image — your prompt describes{" "}
									<strong className="text-blue-200">what happens to it</strong>,
									not what it looks like.
								</p>
								<ul className="list-disc list-inside space-y-0.5 text-blue-300/50 mt-1">
									<li>
										Start = avatar photo → describe action + product details
										on-the-fly (no product ref, so describe size/scale/name)
									</li>
									<li>
										Start = product photo → describe avatar fully on-the-fly
										(appearance, wardrobe) + action
									</li>
									<li>
										Start + End both uploaded → describe the transition/event
										between them
									</li>
								</ul>
							</div>
							{workspacePackage ? (
								<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-3 text-[11px] text-emerald-100">
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-200/80">
										Auto Asset Baseline
									</div>
									<div className="mt-1">
										Resolved product image loads by default as the Start Frame
										reference. End Frame is optional.
									</div>
								</div>
							) : (
								<div className="rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-3 text-[11px] text-slate-300">
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
										Manual Asset Upload
									</div>
									<div className="mt-1">
										No approved package loaded. Upload your reference image(s)
										manually.
									</div>
								</div>
							)}
						</div>
					)}
					{surfaceMode === "HYBRID" ? (
						<details className="group">
							<summary className="cursor-pointer list-none rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[10px] font-bold uppercase tracking-[0.18em] text-amber-200">
								▸ Advanced override: use a pre-composited frame instead of auto
								product-anchor behaviour
							</summary>
							<div className="mt-2">{compositePicker}</div>
						</details>
					) : (
						compositePicker
					)}
					<div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
						<WorkspaceImageAssetSlot
							key={
								startAsset?.assetFingerprint ??
								startAsset?.previewUrl ??
								"start-empty"
							}
							title={
								surfaceMode === "HYBRID"
									? "Product Anchor (Start Frame)"
									: "Start Frame (Reference Image)"
							}
							description={
								workspacePackage
									? "Resolved product image — reference image for this generation"
									: "Upload reference image: avatar photo OR product photo"
							}
							asset={startAsset}
							isUploading={isUploading}
							accentClassName="group-hover:bg-blue-500/10 group-hover:text-blue-400"
							uploadTitle="Upload start frame"
							onFileChange={(e) => handleFileChange("start", e)}
							onPreviewStateChange={setStartPreviewFailed}
						/>
						<WorkspaceImageAssetSlot
							key={
								endAsset?.assetFingerprint ??
								endAsset?.previewUrl ??
								"end-empty"
							}
							title="End Frame (Optional)"
							description="Upload a second reference image — model generates the transition between start and end"
							asset={endAsset}
							isUploading={isUploading}
							accentClassName="group-hover:bg-purple-500/10 group-hover:text-purple-400"
							uploadTitle="Upload end frame"
							onFileChange={(e) => handleFileChange("end", e)}
						/>
					</div>
				</section>

				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						2. Prompt Injection
					</h3>
					<div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
						{workspacePackage ? (
							<div className="grid gap-3">
								<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-3 text-[11px] text-emerald-100">
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-200/80">
										Auto Package Baseline
									</div>
									<div className="mt-1">
										Approved package loaded. Start Frame defaults to the cached
										product image; End Frame stays optional.
									</div>
								</div>
								<div
									className={`rounded-xl border px-3 py-3 text-[11px] ${isManualOverride ? "border-amber-500/30 bg-amber-500/10 text-amber-100" : "border-slate-800 bg-slate-950/40 text-slate-300"}`}
								>
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
										Manual Override
									</div>
									<div className="mt-1">
										Editing the prompt below overrides the auto-compiled package
										prompt for this run only.
									</div>
									{isManualOverride ? (
										<div className="mt-2 text-amber-100">
											Manual override active. Start Frame can still fall back to
											the cached product image.
										</div>
									) : null}
								</div>
							</div>
						) : (
							<div className="rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-3 text-[11px] text-slate-300">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
									Manual Prompt Injection
								</div>
								<div className="mt-1">
									No approved package is loaded. The prompt below is 100%
									manual.
								</div>
							</div>
						)}
						{startPreviewFailed ? (
							<div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-100">
								Image preview failed. Upload a manual Start Frame replacement
								before sending this F2V job.
							</div>
						) : null}
						{/* Multi-block (EXTEND): show each block in its own separate box */}
						{workspacePackage?.prompt_blocks &&
						workspacePackage.prompt_blocks.length > 1 ? (
							<div className="space-y-4">
								{workspacePackage.prompt_blocks.map((block) => (
									<PromptAuditCard
										key={block.block_index}
										label={`Block ${block.block_index} Audit`}
										text={block.engine_prompt_text}
										block={block}
									/>
								))}
								<div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
									EXTEND mode — copy each block separately into the video
									engine. Do NOT paste both blocks into one generation.
								</div>
							</div>
						) : (
							/* Single block (SINGLE mode): editable prompt */
							<div className="space-y-3">
								{workspacePackage && packagePromptText ? (
									<PromptAuditCard
										label="Approved Package Baseline"
										text={packagePromptText}
									/>
								) : null}
								<textarea
									id="f2v-manual-prompt"
									name="f2v_manual_prompt"
									className="w-full h-40 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
									placeholder="Describe WHAT HAPPENS to the reference image(s). The model sees the image — don't re-describe it. Instead: action (character holds product, walks into scene), any on-the-fly subject details not in the image (e.g. product size if start frame is avatar), camera movement..."
									value={manualPrompt}
									onChange={(e) => {
										const next = e.target.value;
										setManualPrompt(next);
										setIsManualOverride(
											Boolean(workspacePackage?.prompt_text) &&
												next !== workspacePackage?.prompt_text,
										);
									}}
								/>
							</div>
						)}
					</div>
				</section>

				<div className="pt-4 space-y-3">
					<CopyBindingGate
						copyBound={copyBound}
						ready={copyReady}
						fallbackConfirmed={copyFallbackConfirmed}
						onToggleFallback={setCopyFallbackConfirmed}
					/>
					<button
						type="button"
						onClick={handleExecute}
						disabled={
							isExecuting ||
							isUploading ||
							!manualPrompt ||
							!startAsset ||
							startPreviewFailed ||
							copyGateBlocked
						}
						className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
					>
						{isUploading
							? "Preparing Assets..."
							: isExecuting
								? "Sending to Flow Editor..."
								: "SEND TO FLOW EDITOR"}
						{!isExecuting && !isUploading && <ArrowRight size={18} />}
					</button>
					<p className="mt-2 text-center text-xs text-slate-400">
						Uploads the start frame and inserts the prompt in the Flow editor,
						then stops before Generate — does not auto-generate.
					</p>
				</div>
			</div>

			<div
				className={`${compact ? "space-y-6" : "space-y-6 xl:sticky xl:top-4"}`}
			>
				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						Flow Mirror Settings
					</h3>
					<div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-6">
						<div className="space-y-3">
							<p className="text-xs font-bold text-slate-400">Aspect Ratio</p>
							<div className="grid grid-cols-2 gap-2">
								{["VERTICAL", "HORIZONTAL"].map((o) => (
									<button
										type="button"
										key={o}
										onClick={() => setOrientation(o as Orientation)}
										className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${orientation === o ? "bg-blue-600/20 border-blue-500 text-blue-400" : "bg-slate-950 border-slate-800 text-slate-500"}`}
									>
										{o === "VERTICAL" ? "9:16 (Vertical)" : "16:9 (Horizontal)"}
									</button>
								))}
							</div>
						</div>
						<div className="space-y-3">
							<p className="text-xs font-bold text-slate-400">Count</p>
							<div className="grid grid-cols-4 gap-2">
								{[1, 2, 3, 4].map((v) => (
									<button
										type="button"
										key={v}
										onClick={() => setCount(v)}
										className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${count === v ? "bg-purple-600/20 border-purple-500 text-purple-400" : "bg-slate-950 border-slate-800 text-slate-500"}`}
									>
										{v}x
									</button>
								))}
							</div>
						</div>
					</div>
				</section>

				<section className="p-6 rounded-2xl border border-blue-500/10 bg-blue-500/5 space-y-3">
					<h4 className="text-[10px] font-bold text-blue-400 uppercase tracking-widest">
						F2V — Prompt Guide
					</h4>
					<div className="text-[10px] text-blue-300/55 leading-relaxed space-y-2">
						<p>
							<strong className="text-blue-300/80">
								Image uploaded = reference.
							</strong>{" "}
							Model sees it — describe the <em>action</em>, not the appearance.
						</p>
						<p>
							<strong className="text-blue-300/80">
								Subject not in any image (on the fly)
							</strong>{" "}
							→ describe fully: look, skin tone, wardrobe, body type.
						</p>
						<p>
							<strong className="text-blue-300/80">Product size</strong> →
							always state scale explicitly (e.g. "lip balm, palm-sized, fits
							between two fingers") — Google Flow struggles with size without a
							verbal anchor.
						</p>
						<p>
							<strong className="text-blue-300/80">Both frames uploaded</strong>{" "}
							→ describe the event/transition between them.
						</p>
					</div>
				</section>
			</div>
		</div>
	);
}
