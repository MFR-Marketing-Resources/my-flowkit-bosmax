import type { AssetCatalogEntry } from "../../types";
import AssetSourceStatusBadge from "./AssetSourceStatusBadge";

export default function AssetCatalogSummary({
	entries,
	selectedAssetType,
	onSelect,
}: {
	entries: AssetCatalogEntry[];
	selectedAssetType: string;
	onSelect: (assetType: string) => void;
}) {
	return (
		<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
			{entries.map((entry) => (
				<button
					key={entry.asset_type}
					type="button"
					onClick={() => onSelect(entry.asset_type)}
					className={`rounded-2xl border p-4 text-left transition-all ${
						selectedAssetType === entry.asset_type
							? "border-blue-500/50 bg-blue-500/10"
							: "border-slate-800 bg-slate-900/50 hover:border-slate-600 hover:bg-slate-900/80"
					}`}
				>
					<div className="flex items-start justify-between gap-3">
						<div>
							<div className="text-sm font-semibold text-slate-100">
								{entry.display_name}
							</div>
							<div className="mt-1 text-[11px] text-slate-400">
								{entry.description}
							</div>
						</div>
						<AssetSourceStatusBadge status={entry.source_status} />
					</div>
					<div className="mt-3 flex items-center justify-between text-[11px] text-slate-300">
						<span>Items</span>
						<span className="font-semibold">{entry.item_count}</span>
					</div>
					{entry.empty_reason ? (
						<div className="mt-3 rounded-xl border border-slate-800 bg-slate-950/70 p-2 text-[10px] text-slate-400">
							Empty Reason: {entry.empty_reason}
						</div>
					) : null}
					{entry.warnings.length > 0 ? (
						<div className="mt-3 space-y-1">
							{entry.warnings.slice(0, 2).map((warning) => (
								<div
									key={warning}
									className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-200"
								>
									{warning}
								</div>
							))}
						</div>
					) : null}
				</button>
			))}
		</div>
	);
}
