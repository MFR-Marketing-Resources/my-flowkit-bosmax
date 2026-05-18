/**
 * WorkspaceGenerationPackagesPage — Prompt Handoff Bank
 *
 * Central page listing all saved workspace generation packages (F2V and I2V).
 * Manual handoff actions: Copy Prompt, Open Image, Download Image, Upload Order.
 * DOM handoff: stored scaffold only — dom_handoff_ready remains FALSE.
 * "Send to Google Flow" button is visible but disabled with an explanation.
 */
import {
	AlertTriangle,
	CheckCircle,
	ChevronDown,
	ChevronRight,
	ClipboardCopy,
	Download,
	ExternalLink,
	Filter,
	Layers,
	RefreshCw,
	Search,
	XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
	getWorkspaceGenerationPackage,
	listWorkspaceGenerationPackages,
} from "../api/workspaceGenerationPackages";
import type {
	WorkspaceGenerationPackage,
	WorkspaceGenerationPackageAsset,
} from "../types";

// ─── Status badge ─────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
	const map: Record<string, string> = {
		READY_MANUAL: "bg-green-100 text-green-800",
		READY_DOM_STAGED: "bg-blue-100 text-blue-800",
		BLOCKED: "bg-red-100 text-red-800",
		DRAFT: "bg-gray-100 text-gray-800",
	};
	return (
		<span
			className={`px-2 py-0.5 rounded text-xs font-semibold ${map[status] ?? "bg-gray-100 text-gray-600"}`}
		>
			{status}
		</span>
	);
}

// ─── Image slot row ───────────────────────────────────────────

function ImageSlotRow({
	asset,
	index,
}: {
	asset: WorkspaceGenerationPackageAsset;
	index: number;
}) {
	return (
		<div className="flex items-center gap-3 py-2 border-b border-gray-100 last:border-0">
			<span className="text-xs font-mono text-gray-500 w-6">{index + 1}.</span>
			<span className="flex-1 text-sm font-medium text-gray-800">
				{asset.label || asset.slot_key}
			</span>
			<span className="text-xs text-gray-400 font-mono truncate max-w-[160px]">
				{asset.slot_key}
			</span>
			{asset.preview_url ? (
				<a
					href={asset.preview_url}
					target="_blank"
					rel="noopener noreferrer"
					className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
				>
					<ExternalLink size={12} />
					Open
				</a>
			) : (
				<span className="text-xs text-gray-400">No preview</span>
			)}
			{asset.download_url ? (
				<a
					href={asset.download_url}
					download
					className="flex items-center gap-1 text-xs text-indigo-600 hover:underline"
				>
					<Download size={12} />
					Download
				</a>
			) : (
				<span className="text-xs text-gray-400">No download</span>
			)}
		</div>
	);
}

// ─── Detail panel ─────────────────────────────────────────────

function PackageDetailPanel({ pkg }: { pkg: WorkspaceGenerationPackage }) {
	const [copied, setCopied] = useState(false);

	const handleCopyPrompt = useCallback(() => {
		navigator.clipboard.writeText(pkg.final_prompt_text || "").then(() => {
			setCopied(true);
			setTimeout(() => setCopied(false), 2000);
		});
	}, [pkg.final_prompt_text]);

	const handoff = pkg.manual_handoff_json;
	const domScaffold = pkg.dom_handoff_payload_json;
	const uploadOrder: string[] = handoff?.upload_order ?? [];
	const blockers: string[] = pkg.blockers_json ?? [];
	const warnings: string[] = pkg.warnings_json ?? [];
	const imageAssets = pkg.image_assets_json ?? {};
	const domReady: boolean = domScaffold?.readiness?.dom_handoff_ready ?? false;

	// Build ordered asset list from upload order
	const orderedAssets: WorkspaceGenerationPackageAsset[] = uploadOrder
		.map((slot) => imageAssets[slot])
		.filter(Boolean) as WorkspaceGenerationPackageAsset[];

	// Also include any assets not in upload order
	const extraAssets = Object.entries(imageAssets)
		.filter(([k, v]) => v && !uploadOrder.includes(k))
		.map(([, v]) => v as WorkspaceGenerationPackageAsset);

	const allDisplayAssets = [...orderedAssets, ...extraAssets];

	return (
		<div className="space-y-5">
			{/* Lineage */}
			<div className="bg-gray-50 rounded-lg p-3 space-y-1 text-xs font-mono text-gray-600">
				<div>
					<span className="text-gray-400">package_id:</span>{" "}
					{pkg.workspace_generation_package_id}
				</div>
				<div>
					<span className="text-gray-400">product_id:</span> {pkg.product_id}
				</div>
				<div>
					<span className="text-gray-400">mode:</span> {pkg.mode} /{" "}
					{pkg.source_lane}
				</div>
				<div>
					<span className="text-gray-400">prompt_package_snapshot_id:</span>{" "}
					{pkg.prompt_package_snapshot_id || "—"}
				</div>
				<div>
					<span className="text-gray-400">workspace_execution_package_id:</span>{" "}
					{pkg.workspace_execution_package_id || "—"}
				</div>
				<div>
					<span className="text-gray-400">generation_mode:</span>{" "}
					{pkg.generation_mode}
				</div>
				<div>
					<span className="text-gray-400">created_at:</span> {pkg.created_at}
				</div>
			</div>

			{/* Blockers */}
			{blockers.length > 0 && (
				<div className="bg-red-50 border border-red-200 rounded-lg p-3">
					<div className="flex items-center gap-2 mb-2">
						<XCircle size={14} className="text-red-600" />
						<span className="text-sm font-semibold text-red-700">Blockers</span>
					</div>
					<ul className="space-y-1">
						{blockers.map((b) => (
							<li key={b} className="text-xs text-red-600">
								• {b}
							</li>
						))}
					</ul>
				</div>
			)}

			{/* Warnings */}
			{warnings.length > 0 && (
				<div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
					<div className="flex items-center gap-2 mb-2">
						<AlertTriangle size={14} className="text-yellow-600" />
						<span className="text-sm font-semibold text-yellow-700">
							Warnings
						</span>
					</div>
					<ul className="space-y-1">
						{warnings.map((w) => (
							<li key={w} className="text-xs text-yellow-700">
								• {w}
							</li>
						))}
					</ul>
				</div>
			)}

			{/* Final Prompt */}
			<div>
				<div className="flex items-center justify-between mb-2">
					<span className="text-sm font-semibold text-gray-700">
						Final Prompt
					</span>
					<button
						type="button"
						onClick={handleCopyPrompt}
						className="flex items-center gap-1.5 text-xs bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1.5 rounded"
					>
						<ClipboardCopy size={12} />
						{copied ? "Copied!" : "Copy Final Prompt"}
					</button>
				</div>
				<pre className="bg-gray-900 text-gray-100 text-xs rounded-lg p-4 whitespace-pre-wrap overflow-auto max-h-64">
					{pkg.final_prompt_text || "(no prompt text)"}
				</pre>
			</div>

			{/* Image Slots / Upload Order */}
			<div>
				<div className="flex items-center gap-2 mb-2">
					<span className="text-sm font-semibold text-gray-700">
						Image Slots
					</span>
					{uploadOrder.length > 0 && (
						<span className="text-xs text-gray-500">
							Upload order: {uploadOrder.join(" → ")}
						</span>
					)}
				</div>
				{allDisplayAssets.length > 0 ? (
					<div className="border border-gray-200 rounded-lg px-3">
						{allDisplayAssets.map((asset, i) => (
							<ImageSlotRow key={asset.slot_key} asset={asset} index={i} />
						))}
					</div>
				) : (
					<p className="text-xs text-gray-400 italic">
						No image assets stored in this package.
					</p>
				)}
			</div>

			{/* DOM Scaffold Readiness */}
			<div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
				<div className="flex items-center gap-2 mb-1">
					<Layers size={14} className="text-gray-500" />
					<span className="text-sm font-semibold text-gray-700">
						DOM Handoff Scaffold
					</span>
				</div>
				<div className="flex items-center gap-2 mt-2">
					<CheckCircle size={12} className="text-green-500" />
					<span className="text-xs text-gray-600">
						manual_handoff_ready:{" "}
						{String(
							domScaffold?.readiness?.manual_handoff_ready ??
								blockers.length === 0,
						)}
					</span>
				</div>
				<div className="flex items-center gap-2 mt-1">
					<XCircle size={12} className="text-red-400" />
					<span className="text-xs text-gray-600">
						dom_handoff_ready: {String(domReady)} (locked — not enabled in this
						wave)
					</span>
				</div>

				{/* Send to Google Flow — disabled */}
				<button
					type="button"
					disabled
					className="mt-3 w-full flex items-center justify-center gap-2 text-xs bg-gray-200 text-gray-400 px-3 py-2 rounded cursor-not-allowed"
					title="DOM handoff not enabled in this wave."
				>
					Send to Google Flow
					<span className="text-[10px] italic">
						(DOM handoff not enabled in this wave.)
					</span>
				</button>
			</div>
		</div>
	);
}

// ─── Package row ──────────────────────────────────────────────

function PackageRow({
	pkg,
	isSelected,
	onSelect,
}: {
	pkg: WorkspaceGenerationPackage;
	isSelected: boolean;
	onSelect: () => void;
}) {
	return (
		<tr
			className={`cursor-pointer border-b border-gray-100 hover:bg-indigo-50 transition-colors ${isSelected ? "bg-indigo-50" : ""}`}
			onClick={onSelect}
		>
			<td className="py-2 px-3">
				{isSelected ? (
					<ChevronDown size={14} className="text-indigo-600" />
				) : (
					<ChevronRight size={14} className="text-gray-400" />
				)}
			</td>
			<td className="py-2 px-3 font-mono text-xs text-gray-700 max-w-[200px] truncate">
				{pkg.workspace_generation_package_id}
			</td>
			<td className="py-2 px-3 text-xs font-semibold text-gray-800">
				{pkg.mode}
			</td>
			<td className="py-2 px-3 text-xs text-gray-600 max-w-[160px] truncate">
				{pkg.product_name_snapshot || pkg.product_id}
			</td>
			<td className="py-2 px-3">
				<StatusBadge status={pkg.status} />
			</td>
			<td className="py-2 px-3 text-xs text-gray-400">
				{pkg.created_at?.slice(0, 16).replace("T", " ")}
			</td>
		</tr>
	);
}

// ─── Main page ────────────────────────────────────────────────

export default function WorkspaceGenerationPackagesPage() {
	const [packages, setPackages] = useState<WorkspaceGenerationPackage[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [detailPkg, setDetailPkg] = useState<WorkspaceGenerationPackage | null>(
		null,
	);
	const [detailLoading, setDetailLoading] = useState(false);

	// Filters
	const [modeFilter, setModeFilter] = useState("");
	const [statusFilter, setStatusFilter] = useState("");
	const [productFilter] = useState("");
	const [search, setSearch] = useState("");

	const loadPackages = useCallback(async () => {
		setLoading(true);
		setError(null);
		try {
			const resp = await listWorkspaceGenerationPackages({
				mode: modeFilter || undefined,
				status: statusFilter || undefined,
				product_id: productFilter || undefined,
				limit: 100,
			});
			setPackages(resp.packages ?? []);
		} catch (e) {
			setError(String(e));
		} finally {
			setLoading(false);
		}
	}, [modeFilter, statusFilter, productFilter]);

	useEffect(() => {
		void loadPackages();
	}, [loadPackages]);

	const handleSelect = useCallback(
		async (pkg: WorkspaceGenerationPackage) => {
			if (selectedId === pkg.workspace_generation_package_id) {
				setSelectedId(null);
				setDetailPkg(null);
				return;
			}
			setSelectedId(pkg.workspace_generation_package_id);
			setDetailPkg(pkg);
			setDetailLoading(true);
			try {
				const full = await getWorkspaceGenerationPackage(
					pkg.workspace_generation_package_id,
				);
				setDetailPkg(full);
			} catch {
				// keep inline data
			} finally {
				setDetailLoading(false);
			}
		},
		[selectedId],
	);

	// Client-side search filter
	const filtered = packages.filter((p) => {
		if (!search) return true;
		const q = search.toLowerCase();
		return (
			p.workspace_generation_package_id.toLowerCase().includes(q) ||
			(p.product_name_snapshot || "").toLowerCase().includes(q) ||
			p.product_id.toLowerCase().includes(q)
		);
	});

	return (
		<div className="p-6 max-w-7xl mx-auto">
			{/* Header */}
			<div className="mb-6">
				<h1 className="text-2xl font-bold text-gray-900">
					Prompt Handoff Bank
				</h1>
				<p className="text-sm text-gray-500 mt-1">
					Durable final operator handoff packages for F2V and I2V. Manual
					fallback actions available. DOM handoff scaffold stored —
					dom_handoff_ready remains false.
				</p>
			</div>

			{/* Filters */}
			<div className="flex flex-wrap gap-3 mb-5 items-center">
				<div className="flex items-center gap-1.5">
					<Filter size={14} className="text-gray-400" />
					<span className="text-xs text-gray-500">Filters:</span>
				</div>
				<select
					value={modeFilter}
					onChange={(e) => setModeFilter(e.target.value)}
					className="text-sm border border-gray-200 rounded px-2 py-1 bg-white"
				>
					<option value="">All Modes</option>
					<option value="F2V">F2V</option>
					<option value="I2V">I2V</option>
					<option value="T2V">T2V</option>
					<option value="IMG">IMG</option>
				</select>
				<select
					value={statusFilter}
					onChange={(e) => setStatusFilter(e.target.value)}
					className="text-sm border border-gray-200 rounded px-2 py-1 bg-white"
				>
					<option value="">All Statuses</option>
					<option value="READY_MANUAL">READY_MANUAL</option>
					<option value="BLOCKED">BLOCKED</option>
					<option value="DRAFT">DRAFT</option>
					<option value="READY_DOM_STAGED">READY_DOM_STAGED</option>
				</select>
				<div className="relative flex-1 min-w-[200px] max-w-sm">
					<Search
						size={13}
						className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400"
					/>
					<input
						type="text"
						value={search}
						onChange={(e) => setSearch(e.target.value)}
						placeholder="Search packages..."
						className="w-full text-sm border border-gray-200 rounded pl-7 pr-3 py-1 bg-white"
					/>
				</div>
				<button
					type="button"
					onClick={() => void loadPackages()}
					className="flex items-center gap-1.5 text-sm text-indigo-600 hover:text-indigo-700 px-2 py-1"
				>
					<RefreshCw size={13} />
					Refresh
				</button>
			</div>

			{error && (
				<div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4 text-sm text-red-700">
					{error}
				</div>
			)}

			<div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
				{/* Package list */}
				<div>
					{loading ? (
						<div className="text-sm text-gray-400 py-8 text-center">
							Loading packages…
						</div>
					) : filtered.length === 0 ? (
						<div className="text-sm text-gray-400 py-8 text-center">
							No packages found. Create a package from the F2V or I2V operator
							page.
						</div>
					) : (
						<div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
							<table className="w-full text-sm">
								<thead className="bg-gray-50 text-xs text-gray-500 uppercase">
									<tr>
										<th className="py-2 px-3 w-8"></th>
										<th className="py-2 px-3 text-left">Package ID</th>
										<th className="py-2 px-3 text-left">Mode</th>
										<th className="py-2 px-3 text-left">Product</th>
										<th className="py-2 px-3 text-left">Status</th>
										<th className="py-2 px-3 text-left">Created</th>
									</tr>
								</thead>
								<tbody>
									{filtered.map((pkg) => (
										<PackageRow
											key={pkg.workspace_generation_package_id}
											pkg={pkg}
											isSelected={
												selectedId === pkg.workspace_generation_package_id
											}
											onSelect={() => void handleSelect(pkg)}
										/>
									))}
								</tbody>
							</table>
						</div>
					)}
					<p className="text-xs text-gray-400 mt-2">
						{filtered.length} package(s) shown
					</p>
				</div>

				{/* Detail panel */}
				{detailPkg && (
					<div className="bg-white border border-gray-200 rounded-lg p-5">
						<div className="flex items-center justify-between mb-4">
							<span className="font-semibold text-gray-800">
								Package Detail
							</span>
							<StatusBadge status={detailPkg.status} />
						</div>
						{detailLoading ? (
							<div className="text-sm text-gray-400 py-8 text-center">
								Loading detail…
							</div>
						) : (
							<PackageDetailPanel pkg={detailPkg} />
						)}
					</div>
				)}
			</div>
		</div>
	);
}
