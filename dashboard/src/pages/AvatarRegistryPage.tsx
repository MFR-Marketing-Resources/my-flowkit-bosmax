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
							onClick={() => fileInputRef.current?.click()}
							className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-2.5 text-sm font-semibold text-blue-100 hover:bg-blue-500/20 disabled:opacity-50"
						>
							{isSyncing ? "Syncing..." : "⇪ Sync CSV"}
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
