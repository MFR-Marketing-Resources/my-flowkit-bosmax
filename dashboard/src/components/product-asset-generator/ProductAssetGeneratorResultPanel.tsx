import type { ProductAssetGeneratorResponse } from "../../types";

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
			<div className="bosmax-pre-wrap-safe mt-2 text-[11px] text-slate-200">
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
	tone: "truth" | "preview" | "error";
}) {
	const toneMap = {
		truth: "border-red-500/20 bg-red-500/10 text-red-100",
		preview: "border-amber-500/20 bg-amber-500/10 text-amber-100",
		error: "border-rose-500/20 bg-rose-500/10 text-rose-100",
	} as const;
	const titleTone = {
		truth: "text-red-200",
		preview: "text-amber-200",
		error: "text-rose-200",
	} as const;

	return (
		<div className={`min-w-0 rounded-xl border p-3 ${toneMap[tone]}`}>
			<div
				className={`text-[10px] font-semibold uppercase tracking-[0.14em] ${titleTone[tone]}`}
			>
				{title}
			</div>
			<div className="bosmax-warning-list mt-2">
				{items.length > 0 ? (
					items.map((item) => (
						<div
							key={`${title}:${item}`}
							className="bosmax-warning-chip rounded-lg border border-current/20 bg-black/10 px-3 py-2 text-[11px]"
							title={item}
						>
							{item}
						</div>
					))
				) : (
					<div className="bosmax-warning-chip rounded-lg border border-current/20 bg-black/10 px-3 py-2 text-[11px]">
						No items returned.
					</div>
				)}
			</div>
		</div>
	);
}

function ProvenanceList({
	value,
}: {
	value: Record<string, unknown>;
}) {
	return (
		<div className="min-w-0 rounded-xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
				Provenance
			</div>
			<div className="bosmax-provenance-list mt-2">
				{Object.entries(value).length > 0 ? (
					Object.entries(value).map(([key, entry]) => (
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

export default function ProductAssetGeneratorResultPanel({
	result,
}: {
	result: ProductAssetGeneratorResponse | null;
}) {
	const imageAnalysis = (result?.product_context?.image_analysis ?? null) as
		| {
				status?: string;
				provider?: string;
				visual_confidence?: string;
				detected_package?: string | null;
				detected_size_text?: string | null;
				detected_text?: string[];
				warnings?: string[];
				evidence?: string[];
		  }
		| null;

	return (
		<section className="min-w-0 rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
			<div className="text-sm font-semibold text-slate-100">
				Product Asset Generator Result
			</div>
			<div className="bosmax-wrap-safe mt-1 text-[11px] text-slate-400">
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
					<div className="bosmax-auto-fit-grid">
						{[
							["Preview Status", result.preview_status],
							[
								"Target Asset Intent",
								result.target_asset_intent || "NOT_PROVIDED",
							],
							["Truth Warnings", String(result.truth_warnings.length)],
							["Preview Warnings", String(result.preview_warnings.length)],
							["Errors", String(result.errors.length)],
						].map(([label, value]) => (
							<DataCard key={label} label={label} value={String(value)} />
						))}
					</div>

					<div className="bosmax-auto-fit-grid">
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
						<Flag label="dry_run_only" value={result.dry_run_only} />
					</div>

					<div className="min-w-0 rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
						<div className="bosmax-wrap-safe">
							Preview-only readiness profile. No persistence write happened.
						</div>
						<div className="bosmax-wrap-safe mt-2">
							Not a generated asset. Not Chrome extension execution. Not Google
							Flow ready.
						</div>
						{result.truth_status.copy_quality_status ===
						"FALLBACK_COPY_DRAFT" ? (
							<div className="bosmax-wrap-safe mt-2">
								This copy is a fallback draft and must be improved before
								production video output.
							</div>
						) : null}
						{result.truth_status.copy_readiness_status === "COPY_MISSING" ? (
							<div className="bosmax-wrap-safe mt-2">
								COPY_MISSING — hook/USP/CTA must be generated before
								TEXT_TO_VIDEO can be READY.
							</div>
						) : null}
						{result.product_context.scale_warning ? (
							<div className="bosmax-wrap-safe mt-2">
								{String(result.product_context.scale_warning)}
							</div>
						) : null}
						<div className="bosmax-wrap-safe mt-2">
							PRODUCT_SCALE_DERIVED_NOT_DIMENSION_VERIFIED remains visible when
							the scale lock is inferred rather than dimension-verified.
						</div>
					</div>

					<div className="bosmax-auto-fit-grid">
						{[
							[
								"Profile Source Status",
								String(
									result.truth_status.profile_source_status ||
										"EPHEMERAL_PREVIEW",
								),
							],
							[
								"Copy Quality Status",
								String(
									result.truth_status.copy_quality_status || "COPY_MISSING",
								),
							],
							[
								"Group",
								String(
									result.truth_status.group ||
										result.product_context.group ||
										"UNKNOWN_REVIEW_REQUIRED",
								),
							],
							[
								"Sub Group",
								String(
									result.truth_status.sub_group ||
										result.product_context.sub_group ||
										"UNKNOWN_REVIEW_REQUIRED",
								),
							],
							[
								"Type Of Product",
								String(
									result.truth_status.type_of_product ||
										result.product_context.type_of_product ||
										"UNKNOWN_REVIEW_REQUIRED",
								),
							],
							[
								"BOSMAX Product Family",
								String(
									result.truth_status.bosmax_product_family ||
										result.product_context.bosmax_product_family ||
										"NOT_CLASSIFIED",
								),
							],
							[
								"Claim Gate",
								String(
									result.truth_status.claim_gate ||
										result.product_context.claim_gate ||
										"CLAIM_REVIEW_REQUIRED",
								),
							],
							[
								"Intelligence Confidence",
								String(
									result.truth_status.intelligence_confidence ||
										result.product_context.intelligence_confidence ||
										"LOW",
								),
							],
							[
								"Copy Route",
								String(result.product_context.copy_route || "NOT_FOUND"),
							],
							[
								"Copy Review Status",
								String(
									result.product_context.copy_review_status || "NOT_FOUND",
								),
							],
							[
								"Copy Readiness",
								String(
									result.truth_status.copy_readiness_status || "COPY_MISSING",
								),
							],
							[
								"Mapping Review Status",
								String(
									result.truth_status.mapping_review_status || "NOT_RECORDED",
								),
							],
							[
								"product_type_id",
								String(result.truth_status.product_type_id || "MISSING"),
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
							[
								"Scale Truth Status",
								String(
									result.truth_status.scale_truth_status ||
										result.product_context.scale_truth_status ||
										"SCALE_NOT_FOUND",
								),
							],
							[
								"Camera Capture Mode",
								String(
									result.product_context.camera_capture_mode ||
										"UGC_IPHONE_RAW",
								),
							],
							[
								"camera_truth_status",
								String(
									result.truth_status.camera_truth_status ||
										result.product_context.camera_truth_status ||
										"CAMERA_LOCK_MISSING",
								),
							],
							[
								"Image Analysis Status",
								String(
									result.truth_status.image_analysis_status ||
										result.product_context.image_analysis_status ||
										imageAnalysis?.status ||
										"NOT_AVAILABLE",
								),
							],
							[
								"Image Analysis Provider",
								String(
									result.truth_status.image_analysis_provider ||
										result.product_context.image_analysis_provider ||
										imageAnalysis?.provider ||
										"not_configured",
								),
							],
							[
								"Visual Confidence",
								String(
									result.truth_status.image_analysis_visual_confidence ||
										result.product_context.image_analysis_visual_confidence ||
										imageAnalysis?.visual_confidence ||
										"NOT_VERIFIED",
								),
							],
							[
								"Detected Package",
								String(
									imageAnalysis?.detected_package ||
										"NOT_DETECTED",
								),
							],
							[
								"Detected Size Text",
								String(
									imageAnalysis?.detected_size_text ||
										"NOT_DETECTED",
								),
							],
						].map(([label, value]) => (
							<DataCard key={label} label={label} value={String(value)} />
						))}
					</div>

					<div className="bosmax-auto-fit-grid">
						<DataCard
							label="Detected Text"
							value={Array.isArray(imageAnalysis?.detected_text)
								? imageAnalysis.detected_text.join(", ") || "NOT_DETECTED"
								: "NOT_DETECTED"}
						/>
						<DataCard
							label="Image Analysis Warnings"
							value={Array.isArray(imageAnalysis?.warnings)
								? imageAnalysis.warnings.join(", ") || "NO_WARNINGS"
								: "NO_WARNINGS"}
						/>
						<DataCard
							label="Image Analysis Evidence"
							value={Array.isArray(imageAnalysis?.evidence)
								? imageAnalysis.evidence.join(", ") || "NO_EVIDENCE"
								: "NO_EVIDENCE"}
						/>
					</div>

					<div className="bosmax-auto-fit-grid">
						{[
							["Hook", String(result.product_context.hook || "NOT_FOUND")],
							["USP 1", String(result.product_context.usp_1 || "NOT_FOUND")],
							["USP 2", String(result.product_context.usp_2 || "NOT_FOUND")],
							["USP 3", String(result.product_context.usp_3 || "NOT_FOUND")],
							["CTA", String(result.product_context.cta || "NOT_FOUND")],
							[
								"Dialogue Opening",
								String(result.product_context.dialogue_opening || "NOT_FOUND"),
							],
							[
								"Dialogue Body",
								String(result.product_context.dialogue_body || "NOT_FOUND"),
							],
							[
								"Dialogue CTA",
								String(result.product_context.dialogue_cta || "NOT_FOUND"),
							],
							[
								"Product Scale Prompt",
								String(
									result.product_context.product_scale_prompt || "NOT_FOUND",
								),
							],
							result.product_context.camera_capture_mode === "CINEMATIC_PRO"
								? [
										"Cinematic Camera Prompt",
										String(
											result.product_context.cinematic_camera_prompt ||
												"NOT_FOUND",
										),
									]
								: [
										"UGC iPhone Raw Camera Lock",
										String(
											result.product_context.ugc_camera_lock_prompt ||
												"NOT_FOUND",
										),
									],
						].map(([label, value]) => (
							<DataCard key={label} label={String(label)} value={String(value)} />
						))}
					</div>

					<div className="bosmax-auto-fit-grid">
						<WarningList
							title="truth_warnings"
							items={result.truth_warnings}
							tone="truth"
						/>
						<WarningList
							title="preview_warnings"
							items={result.preview_warnings}
							tone="preview"
						/>
						<WarningList title="errors" items={result.errors} tone="error" />
					</div>

					<div className="grid min-w-0 gap-4 xl:grid-cols-2">
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Product Context
							</div>
							<JsonBlock value={result.product_context} />
						</div>
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Truth Status
							</div>
							<JsonBlock value={result.truth_status} />
						</div>
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								warning_summary
							</div>
							<JsonBlock value={result.warning_summary} />
						</div>
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Derived Asset Suggestions
							</div>
							<JsonBlock value={result.derived_asset_suggestions} />
						</div>
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Prompt Suggestions
							</div>
							<JsonBlock value={result.prompt_suggestions} />
						</div>
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Required Assets
							</div>
							<JsonBlock value={result.required_assets} />
						</div>
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Missing Assets
							</div>
							<JsonBlock value={result.missing_assets} />
						</div>
					</div>

					<div className="grid min-w-0 gap-4 xl:grid-cols-2">
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Handling Notes
							</div>
							<JsonBlock value={result.handling_notes} />
						</div>
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Physics Notes
							</div>
							<JsonBlock value={result.physics_notes} />
						</div>
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Scene Notes
							</div>
							<JsonBlock value={result.scene_notes} />
						</div>
						<div className="min-w-0">
							<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
								Camera Notes
							</div>
							<JsonBlock value={result.camera_notes} />
						</div>
					</div>

					<ProvenanceList
						value={(result.provenance || {}) as Record<string, unknown>}
					/>
				</div>
			)}
		</section>
	);
}
