import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useImageGenSettings } from "../api/imageGenSettings";

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
	// "Back" must return to wherever the registry was opened from (Fastlane,
	// Cockpit, …) rather than a hardcoded page. Callers pass ?from=<path>;
	// default to IMG Cockpit for direct/legacy entry.
	const [searchParams] = useSearchParams();
	const backTo = searchParams.get("from") || "/assets/img-cockpit";
	const backLabel = backTo.includes("img-fastlane")
		? "← Back to IMG Fastlane"
		: backTo.includes("img-cockpit")
			? "← Back to IMG Cockpit"
			: "← Back";
	const imgGen = useImageGenSettings();
	const [aspect, setAspect] = useState<string>("9:16");
	const [count, setCount] = useState<number>(1);
	const [imageModel, setImageModel] = useState<string>("Nano Banana 2");
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

	// Create Avatar — manual add + AI auto-generate (wired to add-manual /
	// auto-generate). Both add through the fail-closed pool door; redundancy
	// fails closed (409) and the AI lane can be unconfigured (503).
	const [manualForm, setManualForm] = useState({
		character_name: "",
		gender: "F",
		skin_tone: "",
		hair_style: "",
		wardrobe: "",
		hijab: false,
		expression: "",
	});
	const [isAddingManual, setIsAddingManual] = useState(false);
	const [autoBrief, setAutoBrief] = useState("");
	const [autoGender, setAutoGender] = useState("");
	const [autoHijab, setAutoHijab] = useState(false);
	const [isAutoGenerating, setIsAutoGenerating] = useState(false);

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

	const handleAddManualAvatar = async () => {
		if (!manualForm.character_name.trim()) {
			setError("Nama karakter (character_name) wajib diisi.");
			return;
		}
		setIsAddingManual(true);
		setError(null);
		setSuccessMsg(null);
		try {
			const response = await fetch(
				"/api/workspace/avatar-registry/add-manual",
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({
						character_name: manualForm.character_name.trim(),
						gender: manualForm.gender,
						skin_tone: manualForm.skin_tone.trim(),
						hair_style: manualForm.hair_style.trim(),
						wardrobe: manualForm.wardrobe.trim(),
						hijab: manualForm.hijab,
						expression: manualForm.expression.trim(),
					}),
				},
			);
			const data = await response.json();
			if (!response.ok) {
				const detail = String(data?.detail || `HTTP ${response.status}`);
				if (response.status === 409 && detail.startsWith("AVATAR_REDUNDANT")) {
					const code = detail.split(":")[1] || "";
					throw new Error(
						`Avatar serupa sudah wujud (${code}) — ubah ciri (muka/pakaian).`,
					);
				}
				throw new Error(detail);
			}
			setSuccessMsg(`Avatar ${data.avatar_code} ditambah`);
			setManualForm({
				character_name: "",
				gender: "F",
				skin_tone: "",
				hair_style: "",
				wardrobe: "",
				hijab: false,
				expression: "",
			});
			await refresh();
		} catch (err) {
			setError(err instanceof Error ? err.message : "Manual avatar add failed.");
		} finally {
			setIsAddingManual(false);
		}
	};

	const handleAutoGenerateAvatar = async () => {
		setIsAutoGenerating(true);
		setError(null);
		setSuccessMsg(null);
		try {
			const body: Record<string, unknown> = {};
			if (autoBrief.trim()) body.brief = autoBrief.trim();
			if (autoGender) body.gender = autoGender;
			if (autoHijab) body.hijab = true;
			const response = await fetch(
				"/api/workspace/avatar-registry/auto-generate",
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify(body),
				},
			);
			const data = await response.json();
			if (!response.ok) {
				const detail = String(data?.detail || `HTTP ${response.status}`);
				if (response.status === 503) {
					throw new Error(
						"AI text provider belum diset. Set di AI Provider Settings (lane text_assist) dahulu.",
					);
				}
				if (response.status === 409) {
					throw new Error(
						"AI hasilkan avatar yang serupa sedia ada — cuba brief lain.",
					);
				}
				if (response.status === 502) {
					throw new Error("Penjanaan AI gagal / respons tak sah.");
				}
				throw new Error(detail);
			}
			setSuccessMsg(`Avatar ${data.avatar_code} dijana`);
			setAutoBrief("");
			await refresh();
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "AI avatar auto-generate failed.",
			);
		} finally {
			setIsAutoGenerating(false);
		}
	};

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
						aspect,
						count,
						image_model: imageModel,
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
				<a
					href={backTo}
					className="mb-3 inline-block text-[11px] font-semibold text-slate-400 hover:text-slate-200"
				>
					{backLabel}
				</a>
				<div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
					<label className="text-[10px] text-slate-400">
						<span className="mb-1 block font-semibold uppercase tracking-[0.14em] text-slate-500">Aspect</span>
						<select value={aspect} onChange={(e) => setAspect(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200">
							{imgGen.aspect_options.map((a) => (<option key={a} value={a}>{a}</option>))}
						</select>
					</label>
					<label className="text-[10px] text-slate-400">
						<span className="mb-1 block font-semibold uppercase tracking-[0.14em] text-slate-500">Count</span>
						<input type="number" min="1" max="4" value={count} onChange={(e) => setCount(Math.max(1, Math.min(4, parseInt(e.target.value) || 1)))} className="w-16 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" />
					</label>
					<label className="text-[10px] text-slate-400">
						<span className="mb-1 block font-semibold uppercase tracking-[0.14em] text-slate-500">Image Model</span>
						<select value={imageModel} onChange={(e) => setImageModel(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200">
							{imgGen.models.map((m) => (<option key={m.label} value={m.label}>{m.label}{m.pending ? " (id pending)" : ""}</option>))}
						</select>
					</label>
					<span className="text-[10px] text-slate-500">Shared image-gen settings — applied to every avatar generate below.</span>
				</div>
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
				<div className="mb-4">
					<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
						Create Avatar
					</div>
					<div className="mt-1 text-xs text-slate-400">
						Tambah avatar tunggal secara manual, atau biar AI jana satu
						profil baharu (bukan duplikat) terus ke pool.
					</div>
				</div>
				<div className="grid gap-4 md:grid-cols-2">
					{/* A) Manual add */}
					<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
						<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
							Manual add
						</div>
						<div className="grid grid-cols-2 gap-3">
							<label className="col-span-2 text-[10px] text-slate-400">
								<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
									Character name
								</span>
								<input
									value={manualForm.character_name}
									onChange={(e) =>
										setManualForm((f) => ({
											...f,
											character_name: e.target.value,
										}))
									}
									className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
								/>
							</label>
							<label className="text-[10px] text-slate-400">
								<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
									Gender
								</span>
								<select
									value={manualForm.gender}
									onChange={(e) =>
										setManualForm((f) => ({ ...f, gender: e.target.value }))
									}
									className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
								>
									<option value="F">F</option>
									<option value="M">M</option>
								</select>
							</label>
							<label className="flex items-center gap-2 pt-5 text-[10px] text-slate-400">
								<input
									type="checkbox"
									checked={manualForm.hijab}
									onChange={(e) =>
										setManualForm((f) => ({ ...f, hijab: e.target.checked }))
									}
									className="rounded border-slate-700 bg-slate-950"
								/>
								<span className="font-semibold uppercase tracking-[0.12em] text-slate-500">
									Hijab
								</span>
							</label>
							<label className="text-[10px] text-slate-400">
								<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
									Skin tone
								</span>
								<input
									value={manualForm.skin_tone}
									onChange={(e) =>
										setManualForm((f) => ({ ...f, skin_tone: e.target.value }))
									}
									className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
								/>
							</label>
							<label className="text-[10px] text-slate-400">
								<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
									Hair style
								</span>
								<input
									value={manualForm.hair_style}
									onChange={(e) =>
										setManualForm((f) => ({ ...f, hair_style: e.target.value }))
									}
									className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
								/>
							</label>
							<label className="text-[10px] text-slate-400">
								<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
									Wardrobe
								</span>
								<input
									value={manualForm.wardrobe}
									onChange={(e) =>
										setManualForm((f) => ({ ...f, wardrobe: e.target.value }))
									}
									className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
								/>
							</label>
							<label className="text-[10px] text-slate-400">
								<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
									Expression
								</span>
								<input
									value={manualForm.expression}
									onChange={(e) =>
										setManualForm((f) => ({ ...f, expression: e.target.value }))
									}
									className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
								/>
							</label>
						</div>
						<button
							type="button"
							disabled={isAddingManual}
							onClick={() => void handleAddManualAvatar()}
							className="mt-3 w-full rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-sm font-semibold text-blue-100 hover:bg-blue-500/20 disabled:opacity-50"
						>
							{isAddingManual ? "Menambah..." : "+ Tambah Avatar"}
						</button>
					</div>

					{/* B) AI auto-generate */}
					<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
						<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
							AI auto-generate
						</div>
						<label className="block text-[10px] text-slate-400">
							<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
								Brief
							</span>
							<textarea
								value={autoBrief}
								onChange={(e) => setAutoBrief(e.target.value)}
								rows={3}
								placeholder="Ringkasan: cth 'wanita muda ceria untuk UGC kecantikan'"
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
							/>
						</label>
						<div className="mt-3 flex flex-wrap items-end gap-3">
							<label className="text-[10px] text-slate-400">
								<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
									Gender
								</span>
								<select
									value={autoGender}
									onChange={(e) => setAutoGender(e.target.value)}
									className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
								>
									<option value="">Auto</option>
									<option value="F">F</option>
									<option value="M">M</option>
								</select>
							</label>
							<label className="flex items-center gap-2 pb-1.5 text-[10px] text-slate-400">
								<input
									type="checkbox"
									checked={autoHijab}
									onChange={(e) => setAutoHijab(e.target.checked)}
									className="rounded border-slate-700 bg-slate-950"
								/>
								<span className="font-semibold uppercase tracking-[0.12em] text-slate-500">
									Hijab
								</span>
							</label>
						</div>
						<button
							type="button"
							disabled={isAutoGenerating}
							onClick={() => void handleAutoGenerateAvatar()}
							className="mt-3 w-full rounded-xl border border-purple-500/30 bg-purple-500/10 px-4 py-2 text-sm font-semibold text-purple-100 hover:bg-purple-500/20 disabled:opacity-50"
						>
							{isAutoGenerating
								? "Menjana avatar..."
								: "🤖 Auto-generate Avatar"}
						</button>
						<div className="mt-2 text-[10px] text-slate-500">
							Guna lane text_assist (AI Provider Settings). Boleh ambil masa
							beberapa saat.
						</div>
					</div>
				</div>
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
