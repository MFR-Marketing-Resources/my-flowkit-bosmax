import type { PromptPreviewResponse } from "../../types";

function JsonBlock({ value }: { value: unknown }) {
	return (
		<pre className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/80 p-3 text-[11px] text-slate-300">
			{JSON.stringify(value, null, 2)}
		</pre>
	);
}

function Flag({ label, value }: { label: string; value: boolean }) {
	return (
		<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
				{label}
			</div>
			<div
				className={`mt-2 text-xs font-semibold ${value ? "text-red-200" : "text-emerald-200"}`}
			>
				{String(value)}
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
		<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
			<div className="text-sm font-semibold text-slate-100">
				Prompt Preview Result
			</div>
			<div className="mt-1 text-[11px] text-slate-400">
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
					<div className="grid gap-3 md:grid-cols-4">
						{[
							["Preview Status", result.preview_status],
							["Source Route", result.source_route || "NOT_PROVIDED"],
							["Destination Mode", result.destination_mode || "NOT_PROVIDED"],
							["Output Type", result.output_type || "NOT_PROVIDED"],
						].map(([label, value]) => (
							<div
								key={label}
								className="rounded-xl border border-slate-800 bg-slate-950/70 p-3"
							>
								<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
									{label}
								</div>
								<div className="mt-2 text-xs font-semibold text-slate-200 break-all">
									{value}
								</div>
							</div>
						))}
					</div>

					<div className="grid gap-3 md:grid-cols-4">
						<Flag label="execution_allowed" value={result.execution_allowed} />
						<Flag
							label="flow_execution_allowed"
							value={result.flow_execution_allowed}
						/>
						<Flag
							label="batch_execution_allowed"
							value={result.batch_execution_allowed}
						/>
						<Flag
							label="dry_run_only"
							value={result.dry_run_only}
						/>
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

					<div className="grid gap-4 xl:grid-cols-2">
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Planner Output
							</div>
							<JsonBlock value={result.planner_output} />
						</div>
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Adapter Output
							</div>
							<JsonBlock value={result.adapter_output} />
						</div>
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Composer Output
							</div>
							<JsonBlock value={result.composer_output} />
						</div>
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Temporal Output
							</div>
							<JsonBlock value={result.temporal_output} />
						</div>
					</div>

					<div>
						<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
							Provenance
						</div>
						<JsonBlock value={result.provenance} />
					</div>
				</div>
			)}
		</section>
	);
}
