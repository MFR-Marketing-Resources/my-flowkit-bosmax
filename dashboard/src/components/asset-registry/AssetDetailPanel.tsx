import type { AssetDetailResponse } from "../../types";
import AssetSourceStatusBadge from "./AssetSourceStatusBadge";

function JsonBlock({ value }: { value: unknown }) {
	return (
		<pre className="bosmax-json-block rounded-xl border border-slate-800 bg-slate-950/80 p-3 text-[11px] text-slate-300">
			{JSON.stringify(value, null, 2)}
		</pre>
	);
}

function DetailCard({ label, value }: { label: string; value: string }) {
	return (
		<div className="min-w-0 rounded-xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
				{label}
			</div>
			<div className="bosmax-pre-wrap-safe mt-2 text-[11px] text-slate-200">
				{value}
			</div>
		</div>
	);
}

function WarningList({ items }: { items: string[] }) {
	return (
		<div className="bosmax-warning-list">
			{items.map((warning) => (
				<div
					key={warning}
					className="bosmax-warning-chip rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200"
					title={warning}
				>
					{warning}
				</div>
			))}
		</div>
	);
}

function ProvenanceList({ value }: { value: unknown }) {
	const entries =
		value && typeof value === "object"
			? Object.entries(value as Record<string, unknown>)
			: [];

	return (
		<div className="bosmax-provenance-list">
			{entries.length > 0 ? (
				entries.map(([key, entry]) => (
					<div
						key={key}
						className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2"
					>
						<div className="bosmax-kv-list">
							<div className="bosmax-kv-row">
								<div className="bosmax-kv-label text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
									key
								</div>
								<div className="bosmax-kv-value text-[11px] text-slate-200">
									{key}
								</div>
							</div>
							<div className="bosmax-kv-row">
								<div className="bosmax-kv-label text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
									value
								</div>
								<div className="bosmax-kv-value text-[11px] text-slate-300">
									{typeof entry === "string"
										? entry
										: JSON.stringify(entry, null, 2)}
								</div>
							</div>
						</div>
					</div>
				))
			) : (
				<div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 text-[11px] text-slate-300">
					No provenance returned.
				</div>
			)}
		</div>
	);
}

export default function AssetDetailPanel({
	detail,
}: {
	detail: AssetDetailResponse | null;
}) {
	return (
		<section className="min-w-0 rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
			<div className="flex items-start justify-between gap-3">
				<div className="min-w-0">
					<div className="text-sm font-semibold text-slate-100">
						Asset Detail
					</div>
					<div className="bosmax-wrap-safe mt-1 text-[11px] text-slate-400">
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
					<div className="bosmax-auto-fit-grid">
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
							<DetailCard key={label} label={label} value={String(value)} />
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
										className="bosmax-warning-chip rounded-full border border-slate-700 bg-slate-950 px-2 py-1 text-[10px] text-slate-300"
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
							<WarningList items={[...detail.asset.warnings, ...detail.warnings]} />
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
						<ProvenanceList value={detail.provenance} />
					</div>
				</div>
			)}
		</section>
	);
}
