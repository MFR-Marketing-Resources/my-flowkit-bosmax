import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
	archiveCreativeAsset,
	fetchCreativeAssets,
} from "../api/creativeAssets";
import SaveToCreativeLibraryPanel from "../components/creative-library/SaveToCreativeLibraryPanel";
import { Badge, DataTable } from "../components/ui";
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
	const [search, setSearch] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [isLoading, setIsLoading] = useState(false);
	const [archiving, setArchiving] = useState<string | null>(null);

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

	const displayedItems =
		modeFilter === "ALL"
			? items
			: items.filter((item) => item.allowed_modes.includes(modeFilter));

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
				{error && (
					<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
						{error}
					</div>
				)}
			</section>

			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="mb-4 grid gap-3 md:grid-cols-4">
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
								{s}
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
					initialSort={{ key: "asset", dir: "asc" }}
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
							header: "Status",
							sortValue: (item) => item.status,
							render: (item) => (
								<Badge tone={item.status === "ACTIVE" ? "success" : "warn"}>
									{item.status}
								</Badge>
							),
						},
						{
							key: "modes",
							header: "Modes",
							render: (item) => (
								<span className="text-xs text-slate-400">
									{item.allowed_modes
										.map((mode) => MODE_LABELS[mode] ?? mode)
										.join(", ") || "ALL"}
								</span>
							),
						},
					]}
					rowActions={(item) => (
						<div className="flex items-center justify-end gap-2">
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
			</section>
		</div>
	);
}
