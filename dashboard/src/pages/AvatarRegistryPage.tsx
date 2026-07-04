import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

// AVATAR REGISTRY — read-only view of the approved presenter pool (ADR-008
// avatar law). The pool is TEXT authority: the canonical prompt compiler reads
// it directly at compile time (Section 3 presenter identity). This tab only
// displays it and accepts a validated CSV sync; image assets live in the
// Creative Library tab, generation wiring is a separate mission.

interface AvatarProfile {
	avatar_code: string;
	character_name: string;
	variant: string;
	skin_tone: string;
	hair_style: string;
	wardrobe: string;
	environment: string;
	lighting: string;
	camera: string;
	expression: string;
	usage_tags: string[];
	image_generated: boolean;
	generated_asset_id: string | null;
}

interface AvatarGenerationState {
	jobId: string;
	stage: string;
}

interface AvatarPoolResponse {
	avatars: AvatarProfile[];
	count: number;
	source: string;
	bridge_active: boolean;
}

// CSV Factory — staged seed-schema candidate batches (validate -> review ->
// approve/reject -> export/sync). Candidates never write the bridge directly.
interface CsvFactoryIssue {
	code: string;
	message: string;
	row?: number;
}

interface CsvFactoryReport {
	status: string;
	row_count: number;
	errors: CsvFactoryIssue[];
	warnings: CsvFactoryIssue[];
	summary: Record<string, unknown>;
}

interface CsvFactoryRow {
	row_index: number;
	data: Record<string, string>;
	valid: boolean;
	errors: string[];
	warnings: string[];
	review_status: string;
}

interface CsvFactoryBatchSummary {
	batch_id: string;
	created_at: string;
	source_filename: string | null;
	status: string;
	validation_status: string;
	row_count: number;
	valid_rows: number;
	pending_rows: number;
	approved_rows: number;
	rejected_rows: number;
}

interface CsvFactoryBatchDetail {
	batch_id: string;
	status: string;
	report: CsvFactoryReport;
	rows: CsvFactoryRow[];
	summary: CsvFactoryBatchSummary;
}

const PAGE_SIZE_AVATARS = 25;

export default function AvatarRegistryPage() {
	const navigate = useNavigate();
	const [avatars, setAvatars] = useState<AvatarProfile[]>([]);
	const [bridgeActive, setBridgeActive] = useState(false);
	const [search, setSearch] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [successMsg, setSuccessMsg] = useState<string | null>(null);
	const [isLoading, setIsLoading] = useState(false);
	const [isSyncing, setIsSyncing] = useState(false);
	const [currentPage, setCurrentPage] = useState(1);
	const [generating, setGenerating] = useState<
		Record<string, AvatarGenerationState>
	>({});
	const fileInputRef = useRef<HTMLInputElement>(null);
	const factoryFileInputRef = useRef<HTMLInputElement>(null);
	const [factoryBatches, setFactoryBatches] = useState<
		CsvFactoryBatchSummary[]
	>([]);
	const [factoryBatch, setFactoryBatch] = useState<CsvFactoryBatchDetail | null>(
		null,
	);
	const [factoryReport, setFactoryReport] = useState<CsvFactoryReport | null>(
		null,
	);
	const [isImporting, setIsImporting] = useState(false);
	const [isFactoryBusy, setIsFactoryBusy] = useState(false);

	const refresh = useCallback(async () => {
		setIsLoading(true);
		setError(null);
		try {
			const response = await fetch("/api/workspace/avatar-registry/pool");
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			const data = (await response.json()) as AvatarPoolResponse;
			setAvatars(data.avatars || []);
			setBridgeActive(Boolean(data.bridge_active));
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to load avatar registry.",
			);
		} finally {
			setIsLoading(false);
		}
	}, []);

	useEffect(() => {
		void refresh();
	}, [refresh]);

	useEffect(() => {
		setCurrentPage(1);
	}, []);

	const handleSyncUpload = async (file: File) => {
		const confirmed = window.confirm(
			"⚠️ Legacy Direct Sync — this BYPASSES the CSV Factory.\n\n" +
				"It replaces the runtime avatar bridge through the legacy path " +
				"WITHOUT staging, per-row review, seed-schema validation, PromptV1 " +
				"leak checks, or approval gating.\n\n" +
				"The recommended path is: Import Candidate CSV → review → Sync " +
				"approved → pool.\n\nProceed with legacy direct sync anyway?",
		);
		if (!confirmed) return;
		setIsSyncing(true);
		setError(null);
		setSuccessMsg(null);
		try {
			const body = await file.text();
			const response = await fetch("/api/workspace/avatar-registry/sync", {
				method: "POST",
				headers: { "Content-Type": "text/csv" },
				body,
			});
			const data = await response.json();
			if (!response.ok) {
				throw new Error(data?.detail || `HTTP ${response.status}`);
			}
			setSuccessMsg(
				`Sync OK — ${data.approved_loaded} approved avatar(s) loaded from ${data.rows} row(s).`,
			);
			await refresh();
		} catch (err) {
			setError(err instanceof Error ? err.message : "Avatar CSV sync failed.");
		} finally {
			setIsSyncing(false);
			if (fileInputRef.current) fileInputRef.current.value = "";
		}
	};

	const loadFactoryBatches = useCallback(async () => {
		try {
			const response = await fetch(
				"/api/workspace/avatar-registry/csv-factory/batches",
			);
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			const data = await response.json();
			setFactoryBatches(data.batches || []);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to load CSV Factory batches.",
			);
		}
	}, []);

	useEffect(() => {
		void loadFactoryBatches();
	}, [loadFactoryBatches]);

	const selectFactoryBatch = async (batchId: string) => {
		setIsFactoryBusy(true);
		setError(null);
		try {
			const response = await fetch(
				`/api/workspace/avatar-registry/csv-factory/batches/${batchId}`,
			);
			const data = await response.json();
			if (!response.ok) {
				throw new Error(data?.detail || `HTTP ${response.status}`);
			}
			setFactoryBatch(data as CsvFactoryBatchDetail);
			setFactoryReport((data as CsvFactoryBatchDetail).report);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to load staged batch.",
			);
		} finally {
			setIsFactoryBusy(false);
		}
	};

	const handleFactoryImport = async (file: File) => {
		setIsImporting(true);
		setError(null);
		setSuccessMsg(null);
		setFactoryReport(null);
		try {
			const body = await file.text();
			const response = await fetch(
				`/api/workspace/avatar-registry/csv-factory/import?filename=${encodeURIComponent(file.name)}`,
				{
					method: "POST",
					headers: { "Content-Type": "text/csv" },
					body,
				},
			);
			const data = await response.json();
			if (!response.ok) {
				throw new Error(data?.detail || `HTTP ${response.status}`);
			}
			setFactoryReport(data.report as CsvFactoryReport);
			if (data.staged && data.batch) {
				setSuccessMsg(
					`Staged batch ${data.batch.batch_id} — ${data.batch.valid_rows}/${data.batch.row_count} row(s) valid, awaiting review.`,
				);
				await loadFactoryBatches();
				await selectFactoryBatch(data.batch.batch_id);
			} else {
				setError(
					"CSV rejected at header level — nothing staged. Fix the seed schema and re-import.",
				);
			}
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "CSV Factory import failed.",
			);
		} finally {
			setIsImporting(false);
			if (factoryFileInputRef.current) factoryFileInputRef.current.value = "";
		}
	};

	const reviewFactoryRows = async (
		decisions: { row_index: number; decision: string }[],
	) => {
		if (!factoryBatch || decisions.length === 0) return;
		setIsFactoryBusy(true);
		setError(null);
		try {
			const response = await fetch(
				`/api/workspace/avatar-registry/csv-factory/batches/${factoryBatch.batch_id}/review`,
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ decisions }),
				},
			);
			const data = await response.json();
			if (!response.ok) {
				throw new Error(data?.detail || `HTTP ${response.status}`);
			}
			await loadFactoryBatches();
			await selectFactoryBatch(factoryBatch.batch_id);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Row review failed.");
			setIsFactoryBusy(false);
		}
	};

	const handleApproveAllValid = () => {
		if (!factoryBatch) return;
		const decisions = factoryBatch.rows
			.filter((r) => r.valid && r.review_status === "PENDING")
			.map((r) => ({ row_index: r.row_index, decision: "APPROVE" }));
		void reviewFactoryRows(decisions);
	};

	const handleFactorySync = async () => {
		if (!factoryBatch) return;
		const approvedCount = factoryBatch.rows.filter(
			(r) => r.review_status === "APPROVED",
		).length;
		const confirmed = window.confirm(
			`Sync ${approvedCount} approved row(s) from batch ${factoryBatch.batch_id} into the runtime avatar pool?\n\n` +
				"Existing pool rows are preserved; approved rows are appended through the fail-closed registry sync.",
		);
		if (!confirmed) return;
		setIsFactoryBusy(true);
		setError(null);
		setSuccessMsg(null);
		try {
			const response = await fetch(
				`/api/workspace/avatar-registry/csv-factory/batches/${factoryBatch.batch_id}/sync`,
				{ method: "POST" },
			);
			const data = await response.json();
			if (!response.ok) {
				throw new Error(data?.detail || `HTTP ${response.status}`);
			}
			setSuccessMsg(
				`Synced ${data.synced_rows} row(s) — pool ${data.pool_rows_before} → ${data.pool_rows_after}.`,
			);
			await loadFactoryBatches();
			await selectFactoryBatch(factoryBatch.batch_id);
			await refresh();
		} catch (err) {
			setError(err instanceof Error ? err.message : "CSV Factory sync failed.");
			setIsFactoryBusy(false);
		}
	};

	const handleGenerateImage = async (avatar: AvatarProfile) => {
		const confirmed = window.confirm(
			`Generate imej untuk ${avatar.character_name} (${avatar.avatar_code})?\n\n` +
				"Ini akan hantar 1 job IMG ke Google Flow (imej PERCUMA — hanya video " +
				"yang dicaj kredit). Imej siap akan disimpan kekal dalam Creative " +
				"Library sebagai CHARACTER_REFERENCE.",
		);
		if (!confirmed) return;
		setError(null);
		setSuccessMsg(null);
		try {
			const response = await fetch(
				"/api/workspace/avatar-registry/generate-image",
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({
						avatar_code: avatar.avatar_code,
						confirm_credit_burn: true,
					}),
				},
			);
			const data = await response.json();
			if (!response.ok) {
				throw new Error(data?.detail || `HTTP ${response.status}`);
			}
			setGenerating((prev) => ({
				...prev,
				[avatar.avatar_code]: { jobId: data.job_id, stage: "SUBMITTED" },
			}));
			void pollGenerationJob(avatar.avatar_code, data.job_id);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Avatar image generation failed.",
			);
		}
	};

	const pollGenerationJob = async (avatarCode: string, jobId: string) => {
		for (let attempt = 0; attempt < 150; attempt++) {
			await new Promise((resolve) => setTimeout(resolve, 4000));
			try {
				const response = await fetch(`/api/flow/generate-job/${jobId}`);
				if (!response.ok) continue;
				const job = await response.json();
				setGenerating((prev) =>
					prev[avatarCode]
						? {
								...prev,
								[avatarCode]: { jobId, stage: job.stage || job.status },
							}
						: prev,
				);
				if (job.status === "DONE" && job.media_id) {
					const registerResponse = await fetch(
						"/api/workspace/avatar-registry/register-generated",
						{
							method: "POST",
							headers: { "Content-Type": "application/json" },
							body: JSON.stringify({
								avatar_code: avatarCode,
								media_id: job.media_id,
							}),
						},
					);
					const registerData = await registerResponse.json();
					if (!registerResponse.ok) {
						throw new Error(
							registerData?.detail || `HTTP ${registerResponse.status}`,
						);
					}
					setSuccessMsg(
						`${avatarCode}: imej siap dan didaftarkan dalam Creative Library (${registerData.asset_id}).`,
					);
					setGenerating((prev) => {
						const next = { ...prev };
						delete next[avatarCode];
						return next;
					});
					await refresh();
					return;
				}
				if (job.status === "FAILED" || job.status === "REJECTED") {
					throw new Error(
						`${avatarCode}: generation ${job.status} — ${job.error || "unknown"}`,
					);
				}
			} catch (err) {
				setError(
					err instanceof Error ? err.message : "Avatar generation polling failed.",
				);
				setGenerating((prev) => {
					const next = { ...prev };
					delete next[avatarCode];
					return next;
				});
				return;
			}
		}
		setError(`${avatarCode}: generation timed out — semak Video Jobs / Library.`);
		setGenerating((prev) => {
			const next = { ...prev };
			delete next[avatarCode];
			return next;
		});
	};

	const query = search.trim().toLowerCase();
	const displayed = query
		? avatars.filter((a) =>
				[
					a.avatar_code,
					a.character_name,
					a.variant,
					a.environment,
					a.wardrobe,
					a.usage_tags.join(" "),
				]
					.join(" ")
					.toLowerCase()
					.includes(query),
			)
		: avatars;

	const totalPages = Math.ceil(displayed.length / PAGE_SIZE_AVATARS);
	const safePage = Math.min(Math.max(1, currentPage), totalPages || 1);
	const paginated = displayed.slice(
		(safePage - 1) * PAGE_SIZE_AVATARS,
		safePage * PAGE_SIZE_AVATARS,
	);

	return (
		<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="mb-4 flex items-center justify-between gap-3">
					<div>
						<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
							Avatar Registry
						</div>
						<div className="mt-1 text-xs text-slate-400">
							{isLoading
								? "Loading..."
								: `${displayed.length} approved avatar${displayed.length !== 1 ? "s" : ""} · ${avatars.filter((a) => a.image_generated).length} generated · source: ${bridgeActive ? "synced bridge CSV" : "repo seed"}`}
						</div>
					</div>
					<div>
						<input
							ref={fileInputRef}
							type="file"
							accept=".csv,text/csv"
							className="hidden"
							onChange={(e) => {
								const file = e.target.files?.[0];
								if (file) void handleSyncUpload(file);
							}}
						/>
						<button
							type="button"
							disabled={isSyncing}
							title="Advanced / Legacy — bypasses CSV Factory validation and staging"
							onClick={() => fileInputRef.current?.click()}
							className="rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-2 text-[11px] font-semibold text-slate-400 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-50"
						>
							{isSyncing ? "Syncing..." : "⚠ Legacy Direct Sync"}
						</button>
					</div>
				</div>
				{/* Sub-tab switcher */}
				<div className="flex gap-1 rounded-xl border border-slate-800 bg-slate-950 p-1">
					<button
						type="button"
						onClick={() => navigate("/assets/creative-library")}
						className="flex-1 rounded-lg py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 hover:bg-slate-800/60 hover:text-slate-200 transition-colors"
					>
						Library — Asset Database
					</button>
					<button
						type="button"
						onClick={() => navigate("/assets/creative-library/workspace")}
						className="flex-1 rounded-lg py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 hover:bg-slate-800/60 hover:text-slate-200 transition-colors"
					>
						Workspace — Create / Edit
					</button>
					<button
						type="button"
						className="flex-1 rounded-lg bg-slate-800 py-2 text-[11px] font-bold uppercase tracking-[0.16em] text-slate-100 shadow-sm"
					>
						Avatar Registry
					</button>
				</div>
				{error && (
					<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
						{error}
					</div>
				)}
				{successMsg && (
					<div className="mt-4 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-200">
						{successMsg}
					</div>
				)}
			</section>

			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="mb-4 flex items-center justify-between gap-3">
					<div>
						<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
							CSV Factory — Staging &amp; Review
						</div>
						<div className="mt-1 text-xs text-slate-400">
							Import seed-schema candidate rows, review, then sync only
							approved rows into the runtime pool.
						</div>
					</div>
					<div>
						<input
							ref={factoryFileInputRef}
							type="file"
							accept=".csv,text/csv"
							className="hidden"
							onChange={(e) => {
								const file = e.target.files?.[0];
								if (file) void handleFactoryImport(file);
							}}
						/>
						<button
							type="button"
							disabled={isImporting}
							onClick={() => factoryFileInputRef.current?.click()}
							className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-sm font-semibold text-amber-100 hover:bg-amber-500/20 disabled:opacity-50"
						>
							{isImporting ? "Importing..." : "⇪ Import Candidate CSV"}
						</button>
					</div>
				</div>

				{factoryReport && (
					<div
						className={`mb-4 rounded-xl border px-3 py-2 text-[11px] ${
							factoryReport.status === "FAIL"
								? "border-red-500/20 bg-red-500/10 text-red-200"
								: factoryReport.status === "PASS_WITH_WARNINGS"
									? "border-amber-500/20 bg-amber-500/10 text-amber-200"
									: "border-emerald-500/20 bg-emerald-500/10 text-emerald-200"
						}`}
					>
						<div className="font-semibold">
							Validation: {factoryReport.status} · {factoryReport.row_count}{" "}
							row(s) · {factoryReport.errors.length} error(s) ·{" "}
							{factoryReport.warnings.length} warning(s)
						</div>
						{factoryReport.errors.slice(0, 8).map((issue) => (
							<div key={`${issue.code}-${issue.row ?? "hdr"}`}>
								{issue.row ? `Row ${issue.row}: ` : ""}
								{issue.code} — {issue.message}
							</div>
						))}
						{factoryReport.errors.length > 8 && (
							<div>… {factoryReport.errors.length - 8} more error(s)</div>
						)}
					</div>
				)}

				{factoryBatches.length > 0 && (
					<div className="mb-4 flex flex-wrap items-center gap-2">
						{factoryBatches.map((b) => (
							<button
								key={b.batch_id}
								type="button"
								onClick={() => void selectFactoryBatch(b.batch_id)}
								className={`rounded-lg border px-3 py-1.5 text-[11px] font-semibold ${
									factoryBatch?.batch_id === b.batch_id
										? "border-amber-500/40 bg-amber-500/15 text-amber-100"
										: "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"
								}`}
							>
								{b.batch_id} · {b.status} · {b.approved_rows}✓ {b.rejected_rows}✗{" "}
								{b.pending_rows}⏳
							</button>
						))}
					</div>
				)}

				{factoryBatch && (
					<div>
						<div className="mb-3 flex flex-wrap items-center gap-2">
							<button
								type="button"
								disabled={isFactoryBusy || factoryBatch.status === "SYNCED"}
								onClick={handleApproveAllValid}
								className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-100 hover:bg-emerald-500/20 disabled:opacity-50"
							>
								Approve all valid
							</button>
							<a
								href={`/api/workspace/avatar-registry/csv-factory/batches/${factoryBatch.batch_id}/export`}
								className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-100 hover:bg-blue-500/20"
							>
								⇓ Export approved CSV
							</a>
							<button
								type="button"
								disabled={isFactoryBusy || factoryBatch.status === "SYNCED"}
								onClick={() => void handleFactorySync()}
								className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-100 hover:bg-amber-500/20 disabled:opacity-50"
							>
								{factoryBatch.status === "SYNCED"
									? "✓ Synced to pool"
									: "Sync approved → pool"}
							</button>
						</div>
						<div className="overflow-x-auto rounded-2xl border border-slate-800">
							<table className="min-w-full divide-y divide-slate-800 text-sm">
								<thead className="bg-slate-900/70 text-[10px] uppercase tracking-[0.18em] text-slate-500">
									<tr>
										<th className="px-4 py-3 text-left">Row</th>
										<th className="px-4 py-3 text-left">Avatar Code</th>
										<th className="px-4 py-3 text-left">Character</th>
										<th className="px-4 py-3 text-left">Validation</th>
										<th className="px-4 py-3 text-left">Review</th>
									</tr>
								</thead>
								<tbody className="divide-y divide-slate-800 bg-slate-950/40 text-slate-200">
									{factoryBatch.rows.map((row) => (
										<tr key={row.row_index} className="hover:bg-slate-900/50">
											<td className="px-4 py-3 text-xs text-slate-500">
												{row.row_index}
											</td>
											<td className="px-4 py-3 text-xs font-semibold">
												{row.data.AvatarCode || "—"}
											</td>
											<td className="px-4 py-3 text-xs">
												<div className="font-semibold text-slate-100">
													{row.data.CharacterName}
												</div>
												<div className="text-slate-500">{row.data.Variant}</div>
											</td>
											<td className="px-4 py-3 text-xs">
												{row.valid ? (
													<span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold text-emerald-200">
														VALID
													</span>
												) : (
													<span
														className="rounded-full border border-red-500/30 bg-red-500/10 px-2 py-1 text-[10px] font-semibold text-red-200"
														title={row.errors.join(", ")}
													>
														{row.errors.join(", ")}
													</span>
												)}
											</td>
											<td className="px-4 py-3">
												{factoryBatch.status === "SYNCED" ||
												row.review_status !== "PENDING" ? (
													<span
														className={`rounded-full border px-2 py-1 text-[10px] font-semibold ${
															row.review_status === "APPROVED"
																? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
																: row.review_status === "REJECTED"
																	? "border-red-500/30 bg-red-500/10 text-red-200"
																	: "border-slate-700 bg-slate-900 text-slate-400"
														}`}
													>
														{row.review_status}
													</span>
												) : (
													<div className="flex gap-1.5">
														<button
															type="button"
															disabled={isFactoryBusy || !row.valid}
															onClick={() =>
																void reviewFactoryRows([
																	{
																		row_index: row.row_index,
																		decision: "APPROVE",
																	},
																])
															}
															className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-100 hover:bg-emerald-500/20 disabled:opacity-40"
														>
															Approve
														</button>
														<button
															type="button"
															disabled={isFactoryBusy}
															onClick={() =>
																void reviewFactoryRows([
																	{
																		row_index: row.row_index,
																		decision: "REJECT",
																	},
																])
															}
															className="rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-[11px] font-semibold text-red-100 hover:bg-red-500/20 disabled:opacity-40"
														>
															Reject
														</button>
													</div>
												)}
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
					</div>
				)}
				{factoryBatches.length === 0 && !factoryBatch && !factoryReport && (
					<div className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-4 text-center text-xs text-slate-500">
						No staged batches yet. Import a seed-schema candidate CSV to start.
					</div>
				)}
			</section>

			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="mb-4">
					<input
						value={search}
						onChange={(e) => {
							setSearch(e.target.value);
							setCurrentPage(1);
						}}
						placeholder="Search code, name, environment, wardrobe, tags"
						className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 md:w-96"
					/>
				</div>

				<div className="overflow-x-auto rounded-2xl border border-slate-800">
					<table className="min-w-full divide-y divide-slate-800 text-sm">
						<thead className="bg-slate-900/70 text-[10px] uppercase tracking-[0.18em] text-slate-500">
							<tr>
								<th className="px-4 py-3 text-left">Avatar Code</th>
								<th className="px-4 py-3 text-left">Character</th>
								<th className="px-4 py-3 text-left">Appearance</th>
								<th className="px-4 py-3 text-left">Scene</th>
								<th className="px-4 py-3 text-left">Usage Tags</th>
								<th className="px-4 py-3 text-left">Image</th>
							</tr>
						</thead>
						<tbody className="divide-y divide-slate-800 bg-slate-950/40 text-slate-200">
							{displayed.length === 0 ? (
								<tr>
									<td
										colSpan={6}
										className="px-4 py-8 text-center text-xs text-slate-500"
									>
										{isLoading ? "Loading avatars..." : "No avatars found."}
									</td>
								</tr>
							) : (
								paginated.map((a) => (
									<tr key={a.avatar_code} className="hover:bg-slate-900/50">
										<td className="px-4 py-3">
											<div className="font-semibold">{a.avatar_code}</div>
										</td>
										<td className="px-4 py-3 text-xs">
											<div className="font-semibold text-slate-100">
												{a.character_name}
											</div>
											<div className="text-slate-500">{a.variant}</div>
										</td>
										<td className="px-4 py-3 text-xs text-slate-400">
											{[a.skin_tone, a.hair_style, a.wardrobe, a.expression]
												.filter(Boolean)
												.join(" · ")}
										</td>
										<td className="px-4 py-3 text-xs text-slate-400">
											{[a.environment, a.lighting, a.camera]
												.filter(Boolean)
												.join(" · ")}
										</td>
										<td className="px-4 py-3 text-xs text-slate-400">
											{a.usage_tags.join(", ") || "—"}
										</td>
										<td className="px-4 py-3">
											{a.image_generated && a.generated_asset_id ? (
												<a
													href={`/api/creative-assets/${a.generated_asset_id}/preview`}
													target="_blank"
													rel="noopener noreferrer"
													className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold text-emerald-200 hover:bg-emerald-500/20"
												>
													✓ Generated
												</a>
											) : generating[a.avatar_code] ? (
												<span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-[10px] font-semibold text-blue-200">
													⏳ {generating[a.avatar_code].stage}
												</span>
											) : (
												<button
													type="button"
													onClick={() => void handleGenerateImage(a)}
													className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-100 hover:bg-blue-500/20"
												>
													Generate
												</button>
											)}
										</td>
									</tr>
								))
							)}
						</tbody>
					</table>
				</div>
				{totalPages > 1 && (
					<div className="mt-4 flex items-center justify-center gap-1">
						<button
							type="button"
							onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
							disabled={safePage === 1}
							className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
						>
							Prev
						</button>
						<span className="px-3 text-xs text-slate-400">
							{safePage} / {totalPages}
						</span>
						<button
							type="button"
							onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
							disabled={safePage === totalPages}
							className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
						>
							Next
						</button>
					</div>
				)}
			</section>
		</div>
	);
}
