import type { PromptPreviewResponse } from "../../types";

function JsonBlock({ value }: { value: unknown }) {
	return (
		<pre className="bosmax-json-block rounded-xl border border-slate-800 bg-slate-950/80 p-3 text-[11px] text-slate-300">
			{JSON.stringify(value, null, 2)}
		</pre>
	);
}

function Flag({ label, value }: { label: string; value: boolean }) {
	return (
		<div className="min-w-0 rounded-xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
				{label}
			</div>
			<div
				className={`bosmax-wrap-safe mt-2 text-xs font-semibold ${value ? "text-red-200" : "text-emerald-200"}`}
			>
				{String(value)}
			</div>
		</div>
	);
}

function DataCard({ label, value }: { label: string; value: string }) {
	return (
		<div className="min-w-0 rounded-xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
				{label}
			</div>
			<div className="bosmax-pre-wrap-safe mt-2 text-[11px] font-semibold text-slate-200">
				{value}
			</div>
		</div>
	);
}

function WarningList({
	title,
	items,
	tone,
}: {
	title: string;
	items: string[];
	tone: "warning" | "error";
}) {
	const toneClasses =
		tone === "warning"
			? "border-amber-500/20 bg-amber-500/10 text-amber-200"
			: "border-red-500/20 bg-red-500/10 text-red-200";

	return (
		<div className={`min-w-0 rounded-xl border p-3 ${toneClasses}`}>
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em]">
				{title}
			</div>
			<div className="bosmax-warning-list mt-2">
				{items.map((item) => (
					<div
						key={`${title}:${item}`}
						className="bosmax-warning-chip rounded-lg border border-current/20 bg-black/10 px-3 py-2 text-[11px]"
						title={item}
					>
						{item}
					</div>
				))}
			</div>
		</div>
	);
}

function ProvenanceList({ value }: { value: unknown }) {
	const entries =
		value && typeof value === "object"
			? Object.entries(value as Record<string, unknown>)
			: [];

	return (
		<div className="min-w-0 rounded-xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
				Provenance
			</div>
			<div className="bosmax-provenance-list mt-2">
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
		</div>
	);
}

export default function PromptPreviewResultPanel({
	result,
}: {
	result: PromptPreviewResponse | null;
}) {
	return (
		<section className="min-w-0 rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
			<div className="text-sm font-semibold text-slate-100">
				Prompt Preview Result
			</div>
			<div className="bosmax-wrap-safe mt-1 text-[11px] text-slate-400">
				This output is offline-only. It is not Flow-ready automation and does
				not trigger Chrome extension or batch execution.
			</div>

			{!result ? (
				<div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-400">
					Submit an offline prompt preview request to inspect planner, adapter,
					composer, and temporal outputs.
				</div>
			) : (
				<div className="mt-4 space-y-4">
					<div className="bosmax-auto-fit-grid">
						{[
							["Preview Status", result.preview_status],
							["Source Route", result.source_route || "NOT_PROVIDED"],
							["Destination Mode", result.destination_mode || "NOT_PROVIDED"],
							["Output Type", result.output_type || "NOT_PROVIDED"],
						].map(([label, value]) => (
							<DataCard key={label} label={String(label)} value={String(value)} />
						))}
					</div>

					<div className="bosmax-auto-fit-grid">
						<Flag label="execution_allowed" value={result.execution_allowed} />
						<Flag
							label="flow_execution_allowed"
							value={result.flow_execution_allowed}
						/>
						<Flag
							label="batch_execution_allowed"
							value={result.batch_execution_allowed}
						/>
						<Flag label="dry_run_only" value={result.dry_run_only} />
					</div>

					{result.warnings.length > 0 ? (
						<WarningList
							title="Warnings"
							items={result.warnings}
							tone="warning"
						/>
					) : null}

					{result.errors.length > 0 ? (
						<WarningList title="Errors" items={result.errors} tone="error" />
					) : null}

					<div className="grid min-w-0 gap-4 xl:grid-cols-2">
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Planner Output
							</div>
							<JsonBlock value={result.planner_output} />
						</div>
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Adapter Output
							</div>
							<JsonBlock value={result.adapter_output} />
						</div>
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Composer Output
							</div>
							<JsonBlock value={result.composer_output} />
						</div>
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Temporal Output
							</div>
							<JsonBlock value={result.temporal_output} />
						</div>
					</div>

					<ProvenanceList value={result.provenance} />
				</div>
			)}
		</section>
	);
}
