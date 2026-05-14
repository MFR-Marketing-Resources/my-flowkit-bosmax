import type { ProductAssetGeneratorResponse } from "../../types";

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

export default function ProductAssetGeneratorResultPanel({
	result,
}: {
	result: ProductAssetGeneratorResponse | null;
}) {
	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
			<div className="text-sm font-semibold text-slate-100">
				Product Asset Generator Result
			</div>
			<div className="mt-1 text-[11px] text-slate-400">
				This output is preview-only. It is not real image generation, not a
				Google Flow execution surface, and not a Chrome extension execution
				surface. It is also not a persisted readiness profile.
			</div>

			{!result ? (
				<div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-400">
					Submit a preview request to inspect product context, derived asset
					suggestions, prompt suggestions, and truth-status warnings.
				</div>
			) : (
				<div className="mt-4 space-y-4">
					<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
						{[
							["Preview Status", result.preview_status],
							[
								"Target Asset Intent",
								result.target_asset_intent || "NOT_PROVIDED",
							],
							["Warnings", String(result.warning_summary.length)],
							["Errors", String(result.errors.length)],
						].map(([label, value]) => (
							<div
								key={label}
								className="rounded-xl border border-slate-800 bg-slate-950/70 p-3"
							>
								<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
									{label}
								</div>
								<div className="mt-2 break-all text-xs font-semibold text-slate-200">
									{value}
								</div>
							</div>
						))}
					</div>

					<div className="grid gap-3 md:grid-cols-4">
						<Flag label="execution_allowed" value={result.execution_allowed} />
						<Flag
							label="image_generation_allowed"
							value={result.image_generation_allowed}
						/>
						<Flag
							label="flow_execution_allowed"
							value={result.flow_execution_allowed}
						/>
						<Flag
							label="batch_execution_allowed"
							value={result.batch_execution_allowed}
						/>
					</div>

					<div className="grid gap-3 md:grid-cols-2">
						<Flag label="dry_run_only" value={result.dry_run_only} />
						<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
							Unverified assets are not canonical truth. Preview outputs are not
							generated assets, not persisted readiness profiles, and remain
							offline-only.
						</div>
					</div>

					<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
						{[
							[
								"Profile Source Status",
								String(
									result.truth_status.profile_source_status ||
										"EPHEMERAL_PREVIEW",
								),
							],
							[
								"Copy Readiness",
								String(
									result.truth_status.copy_readiness_status || "COPY_MISSING",
								),
							],
							[
								"Execution Readiness",
								String(
									result.truth_status.execution_readiness_status ||
										"DRY_RUN_ONLY",
								),
							],
							[
								"Persistence Truth",
								String(
									result.truth_status.persistence_truth || "NOT_PERSISTED",
								),
							],
						].map(([label, value]) => (
							<div
								key={label}
								className="rounded-xl border border-slate-800 bg-slate-950/70 p-3"
							>
								<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
									{label}
								</div>
								<div className="mt-2 text-xs font-semibold text-slate-200">
									{value}
								</div>
							</div>
						))}
					</div>

					<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
						<div>
							Preview-only readiness profile. No persistence write happened.
						</div>
						<div className="mt-2">
							Not a generated asset. Not Chrome extension execution. Not Google
							Flow ready.
						</div>
						{result.truth_status.copy_readiness_status === "COPY_MISSING" ? (
							<div className="mt-2">
								COPY_MISSING — hook/USP/CTA must be generated before
								TEXT_TO_VIDEO can be READY.
							</div>
						) : null}
					</div>

					{result.warning_summary.length > 0 ? (
						<div className="space-y-2">
							{result.warning_summary.map((warning) => (
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
								Product Context
							</div>
							<JsonBlock value={result.product_context} />
						</div>
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Truth Status
							</div>
							<JsonBlock value={result.truth_status} />
						</div>
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Derived Asset Suggestions
							</div>
							<JsonBlock value={result.derived_asset_suggestions} />
						</div>
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Prompt Suggestions
							</div>
							<JsonBlock value={result.prompt_suggestions} />
						</div>
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Required Assets
							</div>
							<JsonBlock value={result.required_assets} />
						</div>
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Missing Assets
							</div>
							<JsonBlock value={result.missing_assets} />
						</div>
					</div>

					<div className="grid gap-4 xl:grid-cols-2">
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Handling Notes
							</div>
							<JsonBlock value={result.handling_notes} />
						</div>
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Physics Notes
							</div>
							<JsonBlock value={result.physics_notes} />
						</div>
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Scene Notes
							</div>
							<JsonBlock value={result.scene_notes} />
						</div>
						<div>
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Camera Notes
							</div>
							<JsonBlock value={result.camera_notes} />
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
