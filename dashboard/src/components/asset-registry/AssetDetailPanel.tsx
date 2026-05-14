import type { AssetDetailResponse } from "../../types";
import AssetSourceStatusBadge from "./AssetSourceStatusBadge";

function JsonBlock({ value }: { value: unknown }) {
	return (
		<pre className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/80 p-3 text-[11px] text-slate-300">
			{JSON.stringify(value, null, 2)}
		</pre>
	);
}

export default function AssetDetailPanel({
	detail,
}: {
	detail: AssetDetailResponse | null;
}) {
	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
			<div className="flex items-start justify-between gap-3">
				<div>
					<div className="text-sm font-semibold text-slate-100">
						Asset Detail
					</div>
					<div className="mt-1 text-[11px] text-slate-400">
						Truth status must remain explicit. Unverified assets are not
						canonical registry truth.
					</div>
				</div>
				{detail ? (
					<AssetSourceStatusBadge status={detail.asset.source_status} />
				) : null}
			</div>

			{!detail ? (
				<div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-400">
					Select an asset row to inspect metadata, provenance, and warnings.
				</div>
			) : (
				<div className="mt-4 space-y-4">
					<div className="grid gap-3 md:grid-cols-2">
						{[
							["Asset ID", detail.asset.asset_id],
							["Asset Type", detail.asset.asset_type],
							["Label", detail.asset.label],
							["Description", detail.asset.description],
							["Selectable", String(detail.asset.is_selectable)],
							["Canonical", String(detail.asset.is_canonical)],
							["Verified Level", detail.asset.verified_level],
							["Source File", detail.asset.source_file || "NOT_PROVIDED"],
							["Source Path", detail.asset.source_path || "NOT_PROVIDED"],
						].map(([label, value]) => (
							<div
								key={label}
								className="rounded-xl border border-slate-800 bg-slate-950/70 p-3"
							>
								<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
									{label}
								</div>
								<div className="mt-2 text-[11px] text-slate-200 break-all">
									{value}
								</div>
							</div>
						))}
					</div>

					<div>
						<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Compatibility Tags
						</div>
						<div className="flex flex-wrap gap-2">
							{detail.asset.compatibility_tags.length > 0 ? (
								detail.asset.compatibility_tags.map((tag) => (
									<span
										key={tag}
										className="rounded-full border border-slate-700 bg-slate-950 px-2 py-1 text-[10px] text-slate-300"
									>
										{tag}
									</span>
								))
							) : (
								<span className="text-[11px] text-slate-400">
									No compatibility tags.
								</span>
							)}
						</div>
					</div>

					<div>
						<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Warnings
						</div>
						{detail.asset.warnings.length > 0 || detail.warnings.length > 0 ? (
							<div className="space-y-2">
								{[...detail.asset.warnings, ...detail.warnings].map(
									(warning) => (
										<div
											key={warning}
											className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200"
										>
											{warning}
										</div>
									),
								)}
							</div>
						) : (
							<div className="text-[11px] text-slate-400">
								No warnings returned.
							</div>
						)}
					</div>

					<div>
						<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Metadata
						</div>
						<JsonBlock value={detail.asset.metadata} />
					</div>

					<div>
						<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Provenance
						</div>
						<JsonBlock value={detail.provenance} />
					</div>
				</div>
			)}
		</section>
	);
}
