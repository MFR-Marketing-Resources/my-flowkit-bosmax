import type { AssetOption, AssetOptionsResponse } from "../../types";
import AssetSourceStatusBadge from "./AssetSourceStatusBadge";

function BoolBadge({
	value,
	yesLabel,
	noLabel,
}: {
	value: boolean;
	yesLabel: string;
	noLabel: string;
}) {
	return (
		<span
			className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${
				value
					? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
					: "border-slate-500/30 bg-slate-500/10 text-slate-200"
			}`}
		>
			{value ? yesLabel : noLabel}
		</span>
	);
}

function Row({
	option,
	isSelected,
	onSelect,
}: {
	option: AssetOption;
	isSelected: boolean;
	onSelect: (asset: AssetOption) => void;
}) {
	return (
		<button
			type="button"
			onClick={() => onSelect(option)}
			className={`grid w-full min-w-0 gap-3 border-b border-slate-800 px-4 py-3 text-left transition-colors last:border-0 md:grid-cols-[minmax(0,1.2fr)_160px_110px_110px] ${
				isSelected ? "bg-blue-500/10" : "hover:bg-slate-900/60"
			}`}
		>
			<div className="min-w-0">
				<div className="bosmax-wrap-safe text-xs font-semibold text-slate-100">
					{option.label}
				</div>
				<div className="bosmax-wrap-safe mt-1 text-[10px] text-slate-400">
					{option.asset_id}
				</div>
				<div className="bosmax-pre-wrap-safe mt-2 text-[11px] text-slate-300">
					{option.description}
				</div>
			</div>
			<div className="min-w-0 space-y-2">
				<AssetSourceStatusBadge status={option.source_status} />
				<div className="bosmax-wrap-safe text-[10px] text-slate-400">
					{option.verified_level}
				</div>
			</div>
			<div className="min-w-0 space-y-2">
				<BoolBadge
					value={option.is_selectable}
					yesLabel="Selectable"
					noLabel="Hidden"
				/>
				<div className="bosmax-wrap-safe text-[10px] text-slate-400">
					Warnings: {option.warnings.length}
				</div>
			</div>
			<div className="min-w-0 space-y-2">
				<BoolBadge
					value={option.is_canonical}
					yesLabel="Canonical"
					noLabel="Preview Only"
				/>
				<div className="bosmax-wrap-safe text-[10px] text-slate-400">
					{option.compatibility_tags.length} tags
				</div>
			</div>
		</button>
	);
}

export default function AssetOptionsTable({
	listing,
	selectedAssetId,
	onSelect,
}: {
	listing: AssetOptionsResponse | null;
	selectedAssetId: string | null;
	onSelect: (asset: AssetOption) => void;
}) {
	if (!listing) {
		return (
			<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 text-sm text-slate-400">
				Loading asset options...
			</div>
		);
	}

	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-900/50">
			<div className="border-b border-slate-800 px-4 py-4">
				<div className="flex flex-wrap items-start justify-between gap-4">
					<div className="min-w-0">
						<div className="text-sm font-semibold text-slate-100">
							{listing.asset_type}
						</div>
						<div className="bosmax-wrap-safe mt-1 text-[11px] text-slate-400">
							Source status: {listing.source_status}. Empty registries mean
							repo-verified datasets do not exist yet.
						</div>
					</div>
					<AssetSourceStatusBadge status={listing.source_status} />
				</div>
				{listing.empty_reason ? (
					<div className="bosmax-pre-wrap-safe mt-3 rounded-xl border border-slate-700 bg-slate-950/70 p-3 text-[11px] text-slate-300">
						{listing.empty_reason}
					</div>
				) : null}
				{listing.warnings.length > 0 ? (
					<div className="bosmax-warning-list mt-3">
						{listing.warnings.map((warning) => (
							<div
								key={warning}
								className="bosmax-warning-chip rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200"
								title={warning}
							>
								{warning}
							</div>
						))}
					</div>
				) : null}
			</div>

			<div className="hidden gap-3 border-b border-slate-800 px-4 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500 md:grid md:grid-cols-[minmax(0,1.2fr)_160px_110px_110px]">
				<span className="min-w-0">Asset</span>
				<span className="min-w-0">Status</span>
				<span className="min-w-0">Select</span>
				<span className="min-w-0">Truth</span>
			</div>

			{listing.options.length === 0 ? (
				<div className="px-4 py-6 text-sm text-slate-400">
					No repo-backed options for this category yet.
				</div>
			) : (
				listing.options.map((option) => (
					<Row
						key={option.asset_id}
						option={option}
						isSelected={selectedAssetId === option.asset_id}
						onSelect={onSelect}
					/>
				))
			)}
		</section>
	);
}
