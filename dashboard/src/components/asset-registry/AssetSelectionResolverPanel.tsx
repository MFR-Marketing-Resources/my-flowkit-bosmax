import type { AssetOptionsResponse, AssetSelectionResponse } from "../../types";

function JsonBlock({ value }: { value: unknown }) {
	return (
		<pre className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/80 p-3 text-[11px] text-slate-300">
			{JSON.stringify(value, null, 2)}
		</pre>
	);
}

export default function AssetSelectionResolverPanel({
	listingsByType,
	selections,
	onChange,
	onResolve,
	result,
	loading,
}: {
	listingsByType: Record<string, AssetOptionsResponse>;
	selections: Record<string, string>;
	onChange: (assetType: string, assetId: string) => void;
	onResolve: () => void;
	result: AssetSelectionResponse | null;
	loading: boolean;
}) {
	const assetTypes = Object.keys(listingsByType);

	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
			<div className="flex items-start justify-between gap-3">
				<div>
					<div className="text-sm font-semibold text-slate-100">
						Selection Resolver
					</div>
					<div className="mt-1 text-[11px] text-slate-400">
						This only validates and reports. It does not write canonical
						registry state.
					</div>
					<div className="mt-2 text-[10px] text-slate-500">
						Returned warnings such as FULL_TUPLE_LEGALITY_NOT_PROVEN and
						CANONICAL_VS_PREVIEW_ISOLATION_NOT_PROVEN must stay visible.
					</div>
				</div>
				<button
					type="button"
					onClick={onResolve}
					disabled={loading}
					className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-xs font-semibold text-blue-200 disabled:opacity-50"
				>
					{loading ? "Resolving..." : "Resolve Selection"}
				</button>
			</div>

			<div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
				{assetTypes.map((assetType) => {
					const listing = listingsByType[assetType];
					return (
						<label
							key={assetType}
							className="block rounded-xl border border-slate-800 bg-slate-950/70 p-3"
						>
							<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								{assetType}
							</div>
							<select
								value={selections[assetType] || ""}
								onChange={(event) => onChange(assetType, event.target.value)}
								className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
							>
								<option value="">No selection</option>
								{listing.options.map((option) => (
									<option key={option.asset_id} value={option.asset_id}>
										{option.label} | {option.source_status}
									</option>
								))}
							</select>
							<div className="mt-2 text-[10px] text-slate-500">
								{listing.options.length} option(s)
							</div>
						</label>
					);
				})}
			</div>

			{result ? (
				<div className="mt-4 space-y-3">
					<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-200">
						Selection Status:{" "}
						<span className="font-semibold">{result.selection_status}</span>
					</div>
					{result.warnings.length > 0 ? (
						<div className="space-y-2">
							{result.warnings.map((warning) => (
								<div
									key={warning}
									className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200"
								>
									{warning}
								</div>
							))}
						</div>
					) : null}
					{result.errors.length > 0 ? (
						<div className="space-y-2">
							{result.errors.map((error) => (
								<div
									key={error}
									className="rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-200"
								>
									{error}
								</div>
							))}
						</div>
					) : null}
					<div>
						<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Resolved Assets
						</div>
						<JsonBlock value={result.resolved_assets} />
					</div>
					<div>
						<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Provenance
						</div>
						<JsonBlock value={result.provenance} />
					</div>
				</div>
			) : null}
		</section>
	);
}
