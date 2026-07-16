import { useCallback, useEffect, useState } from "react";
import { useImageGenSettings } from "../api/imageGenSettings";
import {
	getRegistryCoverage,
	getRegistryReconciliation,
	type RegistryCoverage,
	type RegistryReconciliation,
} from "../api/creativeIntelligence";

interface SceneProfile {
	scene_code: string;
	scene_name: string;
	background_prompt: string;
	route_fit: string[];
	usage_tags: string[];
	generated_asset_id?: string | null;
	image_generated: boolean;
}

interface ScenePoolResponse {
	scenes: SceneProfile[];
	count: number;
	generated_count: number;
	source: string;
	bridge_active: boolean;
}

type GenStage = { jobId: string; stage: string };

export default function SceneContextRegistryPage() {
	const imgGen = useImageGenSettings();
	const [pool, setPool] = useState<ScenePoolResponse | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [successMsg, setSuccessMsg] = useState<string | null>(null);
	const [generating, setGenerating] = useState<Record<string, GenStage>>({});
	const [coverage, setCoverage] = useState<RegistryCoverage | null>(null);
	const [recon, setRecon] = useState<RegistryReconciliation | null>(null);

	const [aspect, setAspect] = useState<string>("9:16");
	const [count, setCount] = useState<number>(1);
	const [imageModel, setImageModel] = useState<string>("Nano Banana 2");

	// Create Scene — manual add + AI auto-generate (mirror of avatar registry).
	const [manualScene, setManualScene] = useState({
		scene_name: "",
		background_prompt: "",
		usage_tags: "",
	});
	const [isAddingManual, setIsAddingManual] = useState(false);
	const [autoBrief, setAutoBrief] = useState("");
	const [isAutoGenerating, setIsAutoGenerating] = useState(false);
	const [deletingCode, setDeletingCode] = useState<string | null>(null);
	const [sceneSearch, setSceneSearch] = useState("");

	const refresh = useCallback(async () => {
		setLoading(true);
		try {
			const response = await fetch("/api/workspace/scene-context-registry/pool");
			const data = await response.json();
			if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
			setPool(data);
			getRegistryCoverage()
				.then(setCoverage)
				.catch(() => {});
			getRegistryReconciliation()
				.then(setRecon)
				.catch(() => {});
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to load scene pool.");
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		void refresh();
	}, [refresh]);

	const pollGenerationJob = async (sceneCode: string, jobId: string) => {
		for (let attempt = 0; attempt < 150; attempt++) {
			await new Promise((resolve) => setTimeout(resolve, 4000));
			try {
				const response = await fetch(`/api/flow/generate-job/${jobId}`);
				if (!response.ok) continue;
				const job = await response.json();
				setGenerating((prev) =>
					prev[sceneCode]
						? { ...prev, [sceneCode]: { jobId, stage: job.stage || job.status } }
						: prev,
				);
				if (job.status === "DONE" && job.media_id) {
					const registerResponse = await fetch(
						"/api/workspace/scene-context-registry/register-generated",
						{
							method: "POST",
							headers: { "Content-Type": "application/json" },
							body: JSON.stringify({ scene_code: sceneCode, media_id: job.media_id }),
						},
					);
					const registerData = await registerResponse.json();
					if (!registerResponse.ok) {
						throw new Error(registerData?.detail || `HTTP ${registerResponse.status}`);
					}
					setSuccessMsg(
						`${sceneCode}: imej scene siap dan didaftarkan (${registerData.asset_id}) — kini boleh dipilih di IMG Fastlane + I2V.`,
					);
					setGenerating((prev) => {
						const next = { ...prev };
						delete next[sceneCode];
						return next;
					});
					await refresh();
					return;
				}
				if (job.status === "FAILED" || job.status === "REJECTED") {
					throw new Error(`${sceneCode}: generation ${job.status} — ${job.error || "unknown"}`);
				}
			} catch (err) {
				setError(err instanceof Error ? err.message : "Scene generation polling failed.");
				setGenerating((prev) => {
					const next = { ...prev };
					delete next[sceneCode];
					return next;
				});
				return;
			}
		}
		setError(`${sceneCode}: generation timed out — semak Video Jobs / Library.`);
		setGenerating((prev) => {
			const next = { ...prev };
			delete next[sceneCode];
			return next;
		});
	};

	const handleAddManualScene = async () => {
		if (!manualScene.scene_name.trim() || !manualScene.background_prompt.trim()) {
			setError("scene_name dan background_prompt wajib diisi.");
			return;
		}
		setIsAddingManual(true);
		setError(null);
		setSuccessMsg(null);
		try {
			const response = await fetch(
				"/api/workspace/scene-context-registry/add-manual",
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({
						scene_name: manualScene.scene_name.trim(),
						background_prompt: manualScene.background_prompt.trim(),
						usage_tags: manualScene.usage_tags.trim() || undefined,
					}),
				},
			);
			const data = await response.json();
			if (!response.ok) {
				const detail = String(data?.detail || `HTTP ${response.status}`);
				if (response.status === 409 && detail.startsWith("SCENE_REDUNDANT")) {
					throw new Error("Scene serupa sudah wujud");
				}
				throw new Error(detail);
			}
			setSuccessMsg(`Scene ${data.scene_code} ditambah`);
			setManualScene({ scene_name: "", background_prompt: "", usage_tags: "" });
			await refresh();
			// One press = scene + a generated empty-plate background image in the
			// Library (immediately selectable in Fastlane/I2V), not just a text row.
			// Image gen is FREE, so chain straight into the IMG lane; failures degrade
			// gracefully (scene stays, image can be retried from the card).
			await handleGenerateImage(
				{
					scene_code: data.scene_code,
					scene_name: data.scene_name,
				} as SceneProfile,
				true,
			);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Manual scene add failed.");
		} finally {
			setIsAddingManual(false);
		}
	};

	const handleAutoGenerateScene = async () => {
		setIsAutoGenerating(true);
		setError(null);
		setSuccessMsg(null);
		try {
			const body: Record<string, unknown> = {};
			if (autoBrief.trim()) body.brief = autoBrief.trim();
			const response = await fetch(
				"/api/workspace/scene-context-registry/auto-generate",
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
						"AI hasilkan scene yang serupa sedia ada — cuba brief lain.",
					);
				}
				if (response.status === 502) {
					throw new Error("Penjanaan AI gagal / respons tak sah.");
				}
				throw new Error(detail);
			}
			setSuccessMsg(`Scene ${data.scene_code} dijana`);
			setAutoBrief("");
			await refresh();
			// Auto-chain into the free IMG lane so the new scene arrives with a
			// generated background image in the Library, not just a text row.
			await handleGenerateImage(
				{
					scene_code: data.scene_code,
					scene_name: data.scene_name,
				} as SceneProfile,
				true,
			);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "AI scene auto-generate failed.",
			);
		} finally {
			setIsAutoGenerating(false);
		}
	};

	const handleDeleteScene = async (scene: SceneProfile) => {
		const confirmed = window.confirm(
			`Padam scene "${scene.scene_name}" (${scene.scene_code}) dari registry?\n\n` +
				"Profil dibuang dari pool dan imej background-nya (jika ada) diarkibkan " +
				"(boleh pulih semula dari Creative Library). Tiada kesan pada video/kredit.",
		);
		if (!confirmed) return;
		setDeletingCode(scene.scene_code);
		setError(null);
		setSuccessMsg(null);
		try {
			const response = await fetch(
				`/api/workspace/scene-context-registry/${encodeURIComponent(scene.scene_code)}`,
				{ method: "DELETE" },
			);
			const data = await response.json();
			if (!response.ok) {
				throw new Error(data?.detail || `HTTP ${response.status}`);
			}
			setSuccessMsg(
				`Scene ${scene.scene_code} dipadam (baki ${data.remaining} scene).`,
			);
			await refresh();
		} catch (err) {
			setError(err instanceof Error ? err.message : "Gagal padam scene.");
		} finally {
			setDeletingCode(null);
		}
	};

	const handleGenerateImage = async (
		scene: SceneProfile,
		skipConfirm = false,
	) => {
		if (!skipConfirm) {
			const confirmed = window.confirm(
				`Generate imej background untuk "${scene.scene_name}" (${scene.scene_code})?\n\n` +
					"Ini akan hantar 1 job IMG ke Google Flow (imej PERCUMA — hanya video yang " +
					"dicaj kredit). Imej scene siap akan disimpan kekal sebagai " +
					"SCENE_CONTEXT_REFERENCE dan terus boleh dipilih di IMG Fastlane + I2V.",
			);
			if (!confirmed) return;
		}
		setError(null);
		setSuccessMsg(null);
		try {
			const response = await fetch(
				"/api/workspace/scene-context-registry/generate-image",
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({
						scene_code: scene.scene_code,
						confirm_credit_burn: true,
						aspect,
						count,
						image_model: imageModel,
					}),
				},
			);
			const data = await response.json();
			if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
			setGenerating((prev) => ({
				...prev,
				[scene.scene_code]: { jobId: data.job_id, stage: "SUBMITTED" },
			}));
			void pollGenerationJob(scene.scene_code, data.job_id);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Scene image generation failed.");
		}
	};

	return (
		<div className="mx-auto max-w-6xl space-y-6 p-6">
			<header className="space-y-1">
				<div className="flex items-center gap-2">
					<a href="/operator" className="text-xs text-slate-400 hover:text-slate-200">
						← Operator
					</a>
				</div>
				<div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-emerald-400/80">
					Live Scene / Context Authority Pool
				</div>
				<h1 className="text-2xl font-bold text-slate-100">Scene Context Registry</h1>
				<p className="text-sm text-slate-400">
					Bank scene/background yang boleh guna semula. Jana imej scene (credit-free)
					→ ia terus boleh dipilih sebagai reference di IMG Fastlane (scene) dan
					video I2V (scene/style) — ganti upload manual.
				</p>
				{pool && (
					<p className="text-xs text-slate-500">
						{pool.count} scene · {pool.generated_count} sudah ada imej ·
						{pool.bridge_active ? " bridge aktif" : " seed repo"}
					</p>
				)}
			</header>

			{coverage && (
				<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
					<div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Scene Pool
							</div>
							<div className="mt-1 text-lg font-bold text-slate-100">
								{coverage.scene.pool_total}
							</div>
							<div className="text-[11px] text-slate-400">
								{coverage.scene.bridge_active ? "synced bridge CSV" : "repo seed"} ·{" "}
								{coverage.scene.prompt_total} scene prompts
							</div>
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Scene-Prompt Coverage
							</div>
							<div className="mt-1 text-lg font-bold text-slate-100">
								{coverage.scene.clusters_covered.length}/{coverage.cluster_total}{" "}
								clusters
							</div>
							<div className="text-[11px] text-slate-400">
								{coverage.product_total} products
							</div>
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Coverage Gaps
							</div>
							<div
								className={`mt-1 text-sm font-semibold ${coverage.scene.clusters_missing.length ? "text-amber-400" : "text-emerald-400"}`}
							>
								{coverage.scene.clusters_missing.length
									? `Missing: ${coverage.scene.clusters_missing.join(", ")}`
									: "Full 12/12 clusters"}
							</div>
						</div>
					</div>
					<div className="mt-3 text-[11px] text-slate-500">
						Used by scene reference lanes (IMG Fastlane · I2V scene/style) and
						Creative Intelligence context. Read-only — editing here changes the live
						pool those lanes resolve against.
					</div>
				</div>
			)}

			{recon && (
				<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
					<div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300">
						Registry Reconciliation
					</div>
					<div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Pool
							</div>
							<div className="mt-1 text-lg font-bold text-slate-100">
								{recon.scene.pool_total}
							</div>
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Scene Prompts
							</div>
							<div className="mt-1 text-lg font-bold text-emerald-400">
								{recon.scene.prompt_template_total}
							</div>
							<div className="text-[10px] text-slate-500">templates</div>
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Referenced
							</div>
							<div className="mt-1 text-lg font-bold text-sky-400">
								{recon.scene.referenced_by_selection}
							</div>
							<div className="text-[10px] text-slate-500">saved selections</div>
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
								Review candidates
							</div>
							<div className="mt-1 text-lg font-bold text-amber-400">
								{recon.scene.review_candidate_count}
							</div>
							<div className="text-[10px] text-slate-500">pool plates</div>
						</div>
					</div>
					<div className="mt-2 text-[11px] text-slate-500">
						Pool ↔ prompt:{" "}
						{recon.scene.pool_to_prompt_mapping === "NOT_DIRECTLY_MAPPED"
							? "not directly mapped (separate id spaces)"
							: recon.scene.pool_to_prompt_mapping}
						. Scene plates also feed the IMG/I2V reference lane.
					</div>
					<div className="mt-2 text-[11px] text-slate-500">{recon.disclaimer}</div>
				</div>
			)}
			{/* Image-gen settings (shared SSOT) */}
			<div className="flex flex-wrap items-end gap-4 rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
				<label className="text-[11px] text-slate-300">
					<span className="mb-1 block font-semibold uppercase tracking-[0.14em] text-slate-500">
						Aspect
					</span>
					<select
						value={aspect}
						onChange={(e) => setAspect(e.target.value)}
						className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
					>
						{imgGen.aspect_options.map((a) => (
							<option key={a} value={a}>
								{a}
							</option>
						))}
					</select>
				</label>
				<label className="text-[11px] text-slate-300">
					<span className="mb-1 block font-semibold uppercase tracking-[0.14em] text-slate-500">
						Count
					</span>
					<input
						type="number"
						min="1"
						max="4"
						value={count}
						onChange={(e) => setCount(Math.max(1, Math.min(4, parseInt(e.target.value) || 1)))}
						className="w-16 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
					/>
				</label>
				<label className="text-[11px] text-slate-300">
					<span className="mb-1 block font-semibold uppercase tracking-[0.14em] text-slate-500">
						Image Model
					</span>
					<select
						value={imageModel}
						onChange={(e) => setImageModel(e.target.value)}
						className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
					>
						{imgGen.models.map((m) => (
							<option key={m.label} value={m.label}>
								{m.label}
								{m.pending ? " (id pending)" : ""}
							</option>
						))}
					</select>
				</label>
			</div>

			{error && (
				<div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-200">
					{error}
				</div>
			)}
			{successMsg && (
				<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200">
					{successMsg}
				</div>
			)}

			{/* Create Scene — manual add + AI auto-generate */}
			<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
				<div className="mb-3">
					<h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
						Create Scene
					</h2>
					<p className="mt-1 text-xs text-slate-400">
						Tambah scene tunggal secara manual, atau biar AI jana satu scene
						baharu (bukan duplikat) terus ke pool.
					</p>
				</div>
				<div className="grid gap-4 md:grid-cols-2">
					{/* A) Manual add */}
					<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
						<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
							Manual add
						</div>
						<label className="block text-[10px] text-slate-400">
							<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
								Scene name
							</span>
							<input
								value={manualScene.scene_name}
								onChange={(e) =>
									setManualScene((s) => ({ ...s, scene_name: e.target.value }))
								}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
							/>
						</label>
						<label className="mt-3 block text-[10px] text-slate-400">
							<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
								Background prompt
							</span>
							<textarea
								value={manualScene.background_prompt}
								onChange={(e) =>
									setManualScene((s) => ({
										...s,
										background_prompt: e.target.value,
									}))
								}
								rows={3}
								placeholder="Background: ..."
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
							/>
						</label>
						<label className="mt-3 block text-[10px] text-slate-400">
							<span className="mb-1 block font-semibold uppercase tracking-[0.12em] text-slate-500">
								Usage tags (optional)
							</span>
							<input
								value={manualScene.usage_tags}
								onChange={(e) =>
									setManualScene((s) => ({ ...s, usage_tags: e.target.value }))
								}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
							/>
						</label>
						<button
							type="button"
							disabled={isAddingManual}
							onClick={() => void handleAddManualScene()}
							className="mt-3 w-full rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-sm font-semibold text-blue-100 hover:bg-blue-500/20 disabled:opacity-50"
						>
							{isAddingManual ? "Menambah..." : "+ Tambah Scene"}
						</button>
					</div>

					{/* B) AI auto-generate */}
					<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
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
								placeholder="Ringkasan: cth 'dapur moden cerah untuk demo produk penjagaan kulit'"
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
							/>
						</label>
						<button
							type="button"
							disabled={isAutoGenerating}
							onClick={() => void handleAutoGenerateScene()}
							className="mt-3 w-full rounded-xl border border-purple-500/30 bg-purple-500/10 px-4 py-2 text-sm font-semibold text-purple-100 hover:bg-purple-500/20 disabled:opacity-50"
						>
							{isAutoGenerating
								? "Menjana scene..."
								: "🤖 Auto-generate Scene"}
						</button>
						<div className="mt-2 text-[10px] text-slate-500">
							Guna lane text_assist (AI Provider Settings). Boleh ambil masa
							beberapa saat.
						</div>
					</div>
				</div>
			</section>

			<div className="mb-2">
				<input
					value={sceneSearch}
					onChange={(e) => setSceneSearch(e.target.value)}
					placeholder="Cari scene (nama, kod, tag)…"
					className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 md:w-96"
				/>
			</div>

			{loading ? (
				<div className="text-sm text-slate-400">Loading scene contexts…</div>
			) : (
				<div className="grid gap-4 md:grid-cols-2">
					{(pool?.scenes ?? [])
						.filter((scene) => {
							const q = sceneSearch.trim().toLowerCase();
							if (!q) return true;
							return [
								scene.scene_name,
								scene.scene_code,
								scene.usage_tags.join(" "),
								scene.route_fit.join(" "),
							]
								.join(" ")
								.toLowerCase()
								.includes(q);
						})
						.map((scene) => {
						const gen = generating[scene.scene_code];
						return (
							<div
								key={scene.scene_code}
								className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 space-y-3"
							>
								<div className="flex items-start justify-between gap-2">
									<div>
										<h3 className="text-sm font-semibold text-slate-100">
											{scene.scene_name}
										</h3>
										<div className="font-mono text-[10px] text-slate-500">
											{scene.scene_code}
										</div>
									</div>
									{scene.image_generated ? (
										<span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-200">
											IMAGE READY
										</span>
									) : (
										<span className="rounded-full border border-slate-600 bg-slate-950 px-2 py-0.5 text-[10px] text-slate-400">
											TEXT ONLY
										</span>
									)}
								</div>
								<p className="text-[11px] leading-relaxed text-slate-400">
									{scene.background_prompt}
								</p>
								<div className="flex flex-wrap gap-1">
									{scene.usage_tags.map((t) => (
										<span
											key={t}
											className="rounded-md border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[9px] text-slate-400"
										>
											{t}
										</span>
									))}
								</div>
								<div className="flex items-center justify-between gap-2 pt-1">
									<span className="text-[9px] text-slate-600">
										{scene.route_fit.join(" · ")}
									</span>
									<div className="flex items-center gap-2">
									{gen ? (
										<span className="text-[11px] text-blue-300">
											Generating… {gen.stage}
										</span>
									) : scene.image_generated ? (
										<button
											type="button"
											onClick={() => handleGenerateImage(scene)}
											className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-[11px] font-semibold text-slate-300 hover:border-blue-500 hover:text-white"
										>
											Regenerate
										</button>
									) : (
										<button
											type="button"
											onClick={() => handleGenerateImage(scene)}
											className="rounded-lg border border-blue-500/50 bg-blue-500/10 px-3 py-1 text-[11px] font-semibold text-blue-200 hover:bg-blue-500/20"
										>
											Generate scene image
										</button>
									)}
										<button
											type="button"
											onClick={() => void handleDeleteScene(scene)}
											disabled={deletingCode === scene.scene_code}
											className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-1 text-[11px] font-semibold text-red-200 hover:bg-red-500/20 disabled:opacity-40 disabled:cursor-not-allowed"
										>
											{deletingCode === scene.scene_code ? "..." : "Delete"}
										</button>
									</div>
								</div>
							</div>
						);
					})}
				</div>
			)}
		</div>
	);
}
