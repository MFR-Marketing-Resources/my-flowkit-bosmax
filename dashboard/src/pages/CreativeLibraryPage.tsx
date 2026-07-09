import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
	archiveCreativeAsset,
	fetchCreativeAssets,
	updateCreativeAsset,
} from "../api/creativeAssets";
import SaveToCreativeLibraryPanel from "../components/creative-library/SaveToCreativeLibraryPanel";
import { Badge, ConfirmActionModal, DataTable } from "../components/ui";
import type { BadgeTone } from "../components/ui";
import type {
	CreativeAsset,
	CreativeAssetSemanticRole,
	CreativeAssetStatus,
	WorkspaceMode,
} from "../types";

const ROLE_OPTIONS: CreativeAssetSemanticRole[] = [
	"PRODUCT_REFERENCE",
	"CHARACTER_REFERENCE",
	"SCENE_CONTEXT_REFERENCE",
	"STYLE_REFERENCE",
	"COMPOSITE_FRAME_REFERENCE",
];
const STATUS_OPTIONS: Array<CreativeAssetStatus | "ALL"> = [
	"ALL",
	"ACTIVE",
	"ARCHIVED",
];
const MODE_OPTIONS: WorkspaceMode[] = ["T2V", "HYBRID", "F2V", "I2V", "IMG"];
const MODE_LABELS: Record<WorkspaceMode, string> = {
	T2V: "T2V",
	HYBRID: "HYBRID",
	F2V: "FRAMES",
	I2V: "I2V",
	IMG: "IMG",
};

// Review lifecycle is SEPARATE from asset lifecycle (ACTIVE/ARCHIVED). ACTIVE does
// NOT mean APPROVED — reuse pickers (F2V frames, I2V references) gate on
// review_status === APPROVED, so the operator needs to see and drive it here.
type ReviewStatus = "DRAFT" | "PENDING_REVIEW" | "APPROVED" | "REJECTED";
const REVIEW_OPTIONS: Array<ReviewStatus | "ALL"> = [
	"ALL",
	"PENDING_REVIEW",
	"APPROVED",
	"REJECTED",
	"DRAFT",
];
const REVIEW_TONE: Record<string, BadgeTone> = {
	APPROVED: "success",
	PENDING_REVIEW: "warn",
	REJECTED: "danger",
	DRAFT: "neutral",
};

function formatTimestamp(value: string): string {
	const parsed = new Date(value);
	if (Number.isNaN(parsed.getTime())) return value || "—";
	return parsed.toLocaleString();
}

export default function CreativeLibraryPage() {
	const navigate = useNavigate();
	const [items, setItems] = useState<CreativeAsset[]>([]);
	const [roleFilter, setRoleFilter] = useState<
		CreativeAssetSemanticRole | "ALL"
	>("ALL");
	const [statusFilter, setStatusFilter] = useState<CreativeAssetStatus | "ALL">(
		"ACTIVE",
	);
	const [modeFilter, setModeFilter] = useState<WorkspaceMode | "ALL">("ALL");
	const [reviewFilter, setReviewFilter] = useState<ReviewStatus | "ALL">("ALL");
	const [search, setSearch] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [isLoading, setIsLoading] = useState(false);
	const [archiving, setArchiving] = useState<string | null>(null);
	// Explicit review action awaiting confirmation — no silent auto-approval.
	const [reviewAction, setReviewAction] = useState<{
		asset: CreativeAsset;
		next: "APPROVED" | "REJECTED";
	} | null>(null);
	const [reviewBusy, setReviewBusy] = useState(false);

	const loadItems = useCallback(() => {
		setError(null);
		setIsLoading(true);
		void fetchCreativeAssets({
			semantic_role: roleFilter === "ALL" ? undefined : roleFilter,
			status: statusFilter === "ALL" ? undefined : statusFilter,
			search: search || undefined,
			limit: 500,
		})
			.then((response) => setItems(response.items))
			.catch((err: unknown) =>
				setError(
					err instanceof Error
						? err.message
						: "Failed to load Creative Library.",
				),
			)
			.finally(() => setIsLoading(false));
	}, [roleFilter, search, statusFilter]);

	useEffect(() => {
		loadItems();
	}, [loadItems]);

	const handleArchive = async (assetId: string) => {
		setArchiving(assetId);
		try {
			await archiveCreativeAsset(assetId);
			setItems((prev) =>
				prev.map((i) =>
					i.asset_id === assetId ? { ...i, status: "ARCHIVED" as const } : i,
				),
			);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to archive asset.");
		} finally {
			setArchiving(null);
		}
	};

	// Reuses the existing PATCH review_status contract (same call the IMG
	// Fastlane/Cockpit "approve generated" buttons fire) — no new approval backend.
	const handleReview = async () => {
		if (!reviewAction) return;
		const { asset, next } = reviewAction;
		setReviewBusy(true);
		try {
			const updated = await updateCreativeAsset(asset.asset_id, {
				review_status: next,
			});
			setItems((prev) =>
				prev.map((i) =>
					i.asset_id === asset.asset_id
						? { ...i, review_status: updated.review_status }
						: i,
				),
			);
			setReviewAction(null);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to update review status.",
			);
		} finally {
			setReviewBusy(false);
		}
	};

	const displayedItems = items.filter((item) => {
		if (modeFilter !== "ALL" && !item.allowed_modes.includes(modeFilter)) {
			return false;
		}
		if (reviewFilter !== "ALL" && item.review_status !== reviewFilter) {
			return false;
		}
		return true;
	});

	return (
		<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
			<SaveToCreativeLibraryPanel onSaved={() => loadItems()} />
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="mb-4 flex items-center justify-between gap-3">
					<div>
						<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
							Creative Library
						</div>
						<div className="mt-1 text-xs text-slate-400">
							{isLoading
								? "Loading..."
								: `${displayedItems.length} asset${displayedItems.length !== 1 ? "s" : ""}`}
						</div>
					</div>
					<button
						type="button"
						onClick={() => navigate("/assets/creative-library/workspace")}
						className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-2.5 text-sm font-semibold text-blue-100 hover:bg-blue-500/20"
					>
						+ New Asset
					</button>
				</div>
				{/* Sub-tab switcher */}
				<div className="flex gap-1 rounded-xl border border-slate-800 bg-slate-950 p-1">
					<button
						type="button"
						className="flex-1 rounded-lg bg-slate-800 py-2 text-[11px] font-bold uppercase tracking-[0.16em] text-slate-100 shadow-sm"
					>
						Library — Asset Database
					</button>
					<button
						type="button"
						onClick={() => navigate("/assets/creative-library/workspace")}
						className="flex-1 rounded-lg py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 hover:bg-slate-800/60 hover:text-slate-200 transition-colors"
					>
						Workspace — Create / Edit
					</button>
					<button
						type="button"
						onClick={() => navigate("/assets/avatar-registry")}
						className="flex-1 rounded-lg py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 hover:bg-slate-800/60 hover:text-slate-200 transition-colors"
					>
						Avatar Registry
					</button>
				</div>
				<p className="mt-3 text-[11px] text-slate-500">
					<strong className="text-slate-300">Lifecycle</strong> (ACTIVE /
					ARCHIVED) is separate from <strong className="text-slate-300">Review</strong>{" "}
					(PENDING_REVIEW / APPROVED / REJECTED). Only APPROVED clean composite
					frames are selectable in the F2V frame pickers — ACTIVE does not mean
					approved.
				</p>
				{error && (
					<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
						{error}
					</div>
				)}
			</section>

			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="mb-4 grid gap-3 md:grid-cols-3 lg:grid-cols-5">
					<select
						value={roleFilter}
						onChange={(e) =>
							setRoleFilter(e.target.value as CreativeAssetSemanticRole | "ALL")
						}
						className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
					>
						<option value="ALL">All Roles</option>
						{ROLE_OPTIONS.map((role) => (
							<option key={role} value={role}>
								{role}
							</option>
						))}
					</select>
					<select
						value={statusFilter}
						onChange={(e) =>
							setStatusFilter(e.target.value as CreativeAssetStatus | "ALL")
						}
						className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
					>
						{STATUS_OPTIONS.map((s) => (
							<option key={s} value={s}>
								{s === "ALL" ? "All Lifecycle" : s}
							</option>
						))}
					</select>
					<select
						value={reviewFilter}
						onChange={(e) =>
							setReviewFilter(e.target.value as ReviewStatus | "ALL")
						}
						className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
					>
						{REVIEW_OPTIONS.map((r) => (
							<option key={r} value={r}>
								{r === "ALL" ? "All Review" : r}
							</option>
						))}
					</select>
					<select
						value={modeFilter}
						onChange={(e) =>
							setModeFilter(e.target.value as WorkspaceMode | "ALL")
						}
						className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
					>
						<option value="ALL">All Modes</option>
						{MODE_OPTIONS.map((mode) => (
							<option key={mode} value={mode}>
								{MODE_LABELS[mode]}
							</option>
						))}
					</select>
					<input
						value={search}
						onChange={(e) => setSearch(e.target.value)}
						placeholder="Search assets"
						className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
					/>
				</div>

				<DataTable
					rows={displayedItems}
					getRowId={(item) => item.asset_id}
					pageSize={20}
					emptyLabel={isLoading ? "Loading assets..." : "No assets found."}
					initialSort={{ key: "updated", dir: "desc" }}
					columns={[
						{
							key: "asset",
							header: "Asset",
							sortValue: (item) => item.display_name,
							render: (item) => (
								<div>
									<div className="font-semibold">{item.display_name}</div>
									<div className="text-xs text-slate-500">{item.asset_id}</div>
								</div>
							),
						},
						{
							key: "role",
							header: "Semantic Role",
							sortValue: (item) => item.semantic_role,
							render: (item) => (
								<span className="text-xs">{item.semantic_role}</span>
							),
						},
						{
							key: "status",
							header: "Lifecycle",
							sortValue: (item) => item.status,
							render: (item) => (
								<Badge tone={item.status === "ACTIVE" ? "success" : "warn"}>
									{item.status}
								</Badge>
							),
						},
						{
							key: "review",
							header: "Review",
							sortValue: (item) => item.review_status,
							render: (item) => (
								<Badge tone={REVIEW_TONE[item.review_status] ?? "neutral"}>
									{item.review_status}
								</Badge>
							),
						},
						{
							key: "modes",
							header: "Modes",
							render: (item) => (
								<div className="text-xs text-slate-400">
									<div>
										{item.allowed_modes
											.map((mode) => MODE_LABELS[mode] ?? mode)
											.join(", ") || "ALL"}
									</div>
									{item.engine_slot_eligibility.length > 0 ? (
										<div className="mt-0.5 text-[10px] text-slate-500">
											slots: {item.engine_slot_eligibility.join(", ")}
										</div>
									) : null}
								</div>
							),
						},
						{
							key: "updated",
							header: "Updated",
							sortValue: (item) => new Date(item.updated_at).getTime(),
							render: (item) => (
								<div className="text-xs text-slate-400">
									<div>{formatTimestamp(item.updated_at)}</div>
									<div className="text-[10px] text-slate-600">
										created {formatTimestamp(item.created_at)}
									</div>
								</div>
							),
						},
					]}
					rowActions={(item) => (
						<div className="flex flex-wrap items-center justify-end gap-2">
							<button
								type="button"
								onClick={() =>
									navigate(
										`/assets/creative-library/workspace?id=${item.asset_id}`,
									)
								}
								className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800"
							>
								Edit
							</button>
							{item.review_status !== "APPROVED" && (
								<button
									type="button"
									onClick={() =>
										setReviewAction({ asset: item, next: "APPROVED" })
									}
									className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
								>
									Approve
								</button>
							)}
							{item.review_status !== "REJECTED" && (
								<button
									type="button"
									onClick={() =>
										setReviewAction({ asset: item, next: "REJECTED" })
									}
									className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-300 hover:bg-rose-500/20"
								>
									Reject
								</button>
							)}
							{item.status === "ACTIVE" && (
								<button
									type="button"
									onClick={() => handleArchive(item.asset_id)}
									disabled={archiving === item.asset_id}
									className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
								>
									{archiving === item.asset_id ? "..." : "Archive"}
								</button>
							)}
						</div>
					)}
				/>
				<ConfirmActionModal
					open={reviewAction !== null}
					title={
						reviewAction?.next === "APPROVED"
							? "Approve asset for reuse?"
							: "Reject asset?"
					}
					body={
						reviewAction?.next === "APPROVED" ? (
							<div className="space-y-1.5">
								<p>
									Marks{" "}
									<strong>{reviewAction?.asset.display_name}</strong> as{" "}
									<strong>APPROVED</strong>. Approved clean composite frames become
									selectable in the F2V start/end pickers (and approved references
									in the I2V pickers).
								</p>
								<p className="text-[10px] text-slate-500">
									This does not bypass safety gates: the F2V resolver still
									excludes rendered-text posters, wrong mode/slot, archived, and
									missing-source assets even after approval.
								</p>
							</div>
						) : (
							<p>
								Marks <strong>{reviewAction?.asset.display_name}</strong> as{" "}
								<strong>REJECTED</strong> and removes it from every reuse picker.
								You can approve it again later.
							</p>
						)
					}
					confirmLabel={reviewAction?.next === "APPROVED" ? "Approve" : "Reject"}
					busy={reviewBusy}
					onConfirm={() => void handleReview()}
					onCancel={() => setReviewAction(null)}
				/>
			</section>
		</div>
	);
}
