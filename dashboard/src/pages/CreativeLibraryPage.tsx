import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
	archiveCreativeAsset,
	fetchCreativeAssets,
} from "../api/creativeAssets";
import type {
	CreativeAsset,
	CreativeAssetSemanticRole,
	CreativeAssetStatus,
	WorkspaceMode,
} from "../types";

const PAGE_SIZE_ASSETS = 20;

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
	const [currentPage, setCurrentPage] = useState(1);
	const [archiving, setArchiving] = useState<string | null>(null);

	useEffect(() => {
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
	}, [roleFilter, statusFilter, search]);

	const paginationResetKey = `${roleFilter}|${statusFilter}|${modeFilter}|${search}`;

	useEffect(() => {
		if (paginationResetKey) {
			setCurrentPage(1);
		}
	}, [paginationResetKey]);

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

	const totalPages = Math.ceil(displayedItems.length / PAGE_SIZE_ASSETS);
	const safePage = Math.min(Math.max(1, currentPage), totalPages || 1);
	const paginatedItems = displayedItems.slice(
		(safePage - 1) * PAGE_SIZE_ASSETS,
		safePage * PAGE_SIZE_ASSETS,
	);

	return (
		<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
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

				<div className="overflow-x-auto rounded-2xl border border-slate-800">
					<table className="min-w-full divide-y divide-slate-800 text-sm">
						<thead className="bg-slate-900/70 text-[10px] uppercase tracking-[0.18em] text-slate-500">
							<tr>
								<th className="px-4 py-3 text-left">Asset</th>
								<th className="px-4 py-3 text-left">Semantic Role</th>
								<th className="px-4 py-3 text-left">Status</th>
								<th className="px-4 py-3 text-left">Modes</th>
								<th className="px-4 py-3 text-left">Edit</th>
								<th className="px-4 py-3 text-left">Archive</th>
							</tr>
						</thead>
						<tbody className="divide-y divide-slate-800 bg-slate-950/40 text-slate-200">
							{displayedItems.length === 0 ? (
								<tr>
									<td
										colSpan={6}
										className="px-4 py-8 text-center text-xs text-slate-500"
									>
										{isLoading ? "Loading assets..." : "No assets found."}
									</td>
								</tr>
							) : (
								paginatedItems.map((item) => (
									<tr key={item.asset_id} className="hover:bg-slate-900/50">
										<td className="px-4 py-3">
											<div className="font-semibold">{item.display_name}</div>
											<div className="text-xs text-slate-500">
												{item.asset_id}
											</div>
										</td>
										<td className="px-4 py-3 text-xs">{item.semantic_role}</td>
										<td className="px-4 py-3 text-xs">
											<span
												className={`rounded-full border px-2 py-1 ${
													item.status === "ACTIVE"
														? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
														: "border-amber-500/30 bg-amber-500/10 text-amber-100"
												}`}
											>
												{item.status}
											</span>
										</td>
										<td className="px-4 py-3 text-xs text-slate-400">
											{item.allowed_modes
												.map((mode) => MODE_LABELS[mode] ?? mode)
												.join(", ") || "ALL"}
										</td>
										<td className="px-4 py-3">
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
										</td>
										<td className="px-4 py-3">
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
										</td>
									</tr>
								))
							)}
						</tbody>
					</table>
				</div>
				{totalPages > 1 && (
					<div className="mt-4 flex items-center justify-center gap-1">
						<button
							type="button"
							onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
							disabled={safePage === 1}
							className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
						>
							Prev
						</button>
						{Array.from({ length: totalPages }, (_, i) => i + 1).map((pg) => (
							<button
								key={pg}
								type="button"
								onClick={() => setCurrentPage(pg)}
								className={`w-8 h-8 rounded-lg border text-xs font-semibold ${safePage === pg ? "border-blue-500/50 bg-blue-500/20 text-blue-200" : "border-slate-700 bg-slate-900 text-slate-400 hover:bg-slate-800"}`}
							>
								{pg}
							</button>
						))}
						<button
							type="button"
							onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
							disabled={safePage === totalPages}
							className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
						>
							Next
						</button>
					</div>
				)}
			</section>
		</div>
	);
}
