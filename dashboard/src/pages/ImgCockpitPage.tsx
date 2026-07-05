import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
	archiveCreativeAsset,
	fetchCreativeAssets,
} from "../api/creativeAssets";
import {
	type ImageArtifact,
	type ImgAssetLane,
	type ImgGenerationJob,
	fetchImageArtifacts,
	fetchImgAssetLanes,
	pollImgGenerationJob,
	saveImgOutputToLibrary,
	startImgGeneration,
} from "../api/imgFactory";
import { compileWorkspacePromptPreview } from "../api/workspacePackages";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { CreativeAsset, Product } from "../types";
import {
	canApprove,
	isReusableAsset,
	resolveGenerationInputs,
} from "./imgCockpitLogic";

// Honesty labels — surfaced verbatim in the Generate step. Live generation is
// credit-spending / live Google Flow and is NOT fired or verified in the build
// session; the register-output → review → save path is credit-free.
const GEN_NOT_FIRED = "NOT_FIRED_IN_SESSION";
const GEN_RUNTIME_UNVERIFIED = "EXTERNAL_RUNTIME_NOT_VERIFIED";

type TruthStatus = "UNVERIFIED" | "PASS" | "FAIL";
type ReviewDecision = "PENDING_REVIEW" | "APPROVED" | "REJECTED";
type OutputMode = "artifact" | "upload";

function fileToDataUrl(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ""));
		reader.onerror = reject;
		reader.readAsDataURL(file);
	});
}

function Section({
	step,
	title,
	children,
}: {
	step: string;
	title: string;
	children: React.ReactNode;
}) {
	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 space-y-3">
			<h3 className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-400">
				<span className="mr-2 rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-slate-300">
					{step}
				</span>
				{title}
			</h3>
			{children}
		</section>
	);
}

function AssetSelect({
	label,
	assets,
	value,
	onChange,
	emptyHint,
}: {
	label: string;
	assets: CreativeAsset[];
	value: string;
	onChange: (v: string) => void;
	emptyHint: string;
}) {
	return (
		<label className="block text-[11px] text-slate-300 space-y-1">
			<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
				{label}
			</span>
			<select
				value={value}
				onChange={(e) => onChange(e.target.value)}
				className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
			>
				<option value="">
					{assets.length === 0 ? emptyHint : "None (optional)"}
				</option>
				{assets.map((a) => (
					<option key={a.asset_id} value={a.asset_id}>
						{a.display_name}
					</option>
				))}
			</select>
		</label>
	);
}

export default function ImgCockpitPage() {
	const navigate = useNavigate();

	const [lanes, setLanes] = useState<ImgAssetLane[]>([]);
	const [laneId, setLaneId] = useState("");
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [characterAssets, setCharacterAssets] = useState<CreativeAsset[]>([]);
	const [sceneAssets, setSceneAssets] = useState<CreativeAsset[]>([]);
	const [styleAssets, setStyleAssets] = useState<CreativeAsset[]>([]);
	const [characterAssetId, setCharacterAssetId] = useState("");
	const [sceneAssetId, setSceneAssetId] = useState("");
	const [styleAssetId, setStyleAssetId] = useState("");

	const [prompt, setPrompt] = useState("");
	const [displayName, setDisplayName] = useState("");
	const [compiling, setCompiling] = useState(false);

	// Gated live generation (never auto-fires).
	const [showGenConfirm, setShowGenConfirm] = useState(false);
	const [generating, setGenerating] = useState(false);
	const [genJob, setGenJob] = useState<ImgGenerationJob | null>(null);

	// Register-output (credit-free).
	const [outputMode, setOutputMode] = useState<OutputMode>("artifact");
	const [artifacts, setArtifacts] = useState<ImageArtifact[]>([]);
	const [artifactMediaId, setArtifactMediaId] = useState("");
	const [uploadFile, setUploadFile] = useState<File | null>(null);

	// Review.
	const [identityStatus, setIdentityStatus] = useState<TruthStatus>("UNVERIFIED");
	const [scaleStatus, setScaleStatus] = useState<TruthStatus>("UNVERIFIED");
	const [claimStatus, setClaimStatus] = useState<TruthStatus>("UNVERIFIED");
	const [reviewDecision, setReviewDecision] = useState<ReviewDecision>("PENDING_REVIEW");

	const [saving, setSaving] = useState(false);
	const [savedAsset, setSavedAsset] = useState<CreativeAsset | null>(null);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		void fetchImgAssetLanes()
			.then((r) => setLanes(r.items))
			.catch(() => setError("Failed to load IMG lanes."));
		void fetchCreativeAssets({ semantic_role: "CHARACTER_REFERENCE", status: "ACTIVE", limit: 100 })
			.then((r) => setCharacterAssets(r.items))
			.catch(() => {});
		void fetchCreativeAssets({ semantic_role: "SCENE_CONTEXT_REFERENCE", status: "ACTIVE", limit: 100 })
			.then((r) => setSceneAssets(r.items))
			.catch(() => {});
		void fetchCreativeAssets({ semantic_role: "STYLE_REFERENCE", status: "ACTIVE", limit: 100 })
			.then((r) => setStyleAssets(r.items))
			.catch(() => {});
		void fetchImageArtifacts(50)
			.then(setArtifacts)
			.catch(() => {});
	}, []);

	const lane = useMemo(
		() => lanes.find((l) => l.lane_id === laneId) ?? null,
		[lanes, laneId],
	);

	// Reuse safety: only APPROVED, ACTIVE references may feed generation/lineage.
	const approvedCharacters = useMemo(
		() => characterAssets.filter(isReusableAsset),
		[characterAssets],
	);
	const approvedScenes = useMemo(
		() => sceneAssets.filter(isReusableAsset),
		[sceneAssets],
	);
	const approvedStyles = useMemo(
		() => styleAssets.filter(isReusableAsset),
		[styleAssets],
	);
	const selectedCharacter = useMemo(
		() => approvedCharacters.find((a) => a.asset_id === characterAssetId) ?? null,
		[approvedCharacters, characterAssetId],
	);
	const selectedScene = useMemo(
		() => approvedScenes.find((a) => a.asset_id === sceneAssetId) ?? null,
		[approvedScenes, sceneAssetId],
	);
	const selectedStyle = useMemo(
		() => approvedStyles.find((a) => a.asset_id === styleAssetId) ?? null,
		[approvedStyles, styleAssetId],
	);
	const genResolution = useMemo(
		() =>
			resolveGenerationInputs(lane, {
				product: selectedProduct,
				character: selectedCharacter,
				scene: selectedScene,
				style: selectedStyle,
			}),
		[lane, selectedProduct, selectedCharacter, selectedScene, selectedStyle],
	);

	const productMissing = Boolean(lane?.requires_product_id && !selectedProduct);
	const hasRealOutput =
		outputMode === "artifact" ? Boolean(artifactMediaId) : Boolean(uploadFile);
	const approvalBlocked =
		reviewDecision === "APPROVED" &&
		!canApprove({
			identity: identityStatus,
			scale: scaleStatus,
			claim: claimStatus,
		});
	const canSave = Boolean(
		lane && displayName.trim() && hasRealOutput && !productMissing && !approvalBlocked && !saving,
	);

	const handleCompilePrompt = async () => {
		if (!selectedProduct) return;
		setCompiling(true);
		setError(null);
		try {
			const preview = await compileWorkspacePromptPreview({
				product_id: selectedProduct.id,
				mode: "IMG",
				source_mode: "IMAGES",
			});
			setPrompt(preview.final_compiled_prompt_text || prompt);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to compile suggested prompt.",
			);
		} finally {
			setCompiling(false);
		}
	};

	// GATED: only ever runs after an explicit operator confirmation.
	const handleConfirmedGenerate = async () => {
		setShowGenConfirm(false);
		setGenerating(true);
		setError(null);
		try {
			const { job_id } = await startImgGeneration({
				prompt,
				image_media_ids: genResolution.mediaIds,
				aspect: "9:16",
			});
			const job = await pollImgGenerationJob(job_id);
			setGenJob(job);
			if (job.status === "DONE" && job.media_id) {
				setOutputMode("artifact");
				setArtifactMediaId(job.media_id);
				setArtifacts((prev) =>
					prev.some((a) => a.media_id === job.media_id)
						? prev
						: [{ media_id: job.media_id as string, artifact_kind: "image" }, ...prev],
				);
			}
		} catch (err) {
			setError(err instanceof Error ? err.message : "Generation call failed.");
		} finally {
			setGenerating(false);
		}
	};

	const handleSave = async () => {
		if (!lane) return;
		setSaving(true);
		setError(null);
		setSavedAsset(null);
		try {
			const base = {
				lane_id: lane.lane_id,
				display_name: displayName.trim(),
				product_id: selectedProduct?.id || null,
				source_character_asset_id: characterAssetId || null,
				source_scene_asset_id: sceneAssetId || null,
				source_style_asset_id: styleAssetId || null,
				identity_lock_status: identityStatus,
				scale_truth_status: scaleStatus,
				claim_safety_status: claimStatus,
				review_status: reviewDecision,
			};
			const output =
				outputMode === "artifact"
					? { generated_artifact_media_id: artifactMediaId }
					: { image_base64: await fileToDataUrl(uploadFile as File), file_name: uploadFile?.name };
			const asset = await saveImgOutputToLibrary({ ...base, ...output });

			// A REJECTED output must not be reusable. Archive it immediately via the
			// real archive endpoint so validate_selectable_asset blocks it
			// (ASSET_ARCHIVED) — on top of the review_status=APPROVED reuse gate that
			// already excludes non-approved assets downstream.
			if (reviewDecision === "REJECTED") {
				await archiveCreativeAsset(asset.asset_id);
			}
			setSavedAsset(asset);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to save to Creative Library.");
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="flex min-w-0 flex-col gap-5 p-4 md:p-6">
			<header className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
					IMG Cockpit
				</div>
				<div className="mt-1 text-xs text-slate-400">
					Operator workflow: pick a lane → product/avatar/scene/style → preview
					prompt → (gated) generate or register a real output → review → save to
					the Creative Library → reuse in I2V / F2V.
				</div>
			</header>

			{error ? (
				<div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
					{error}
				</div>
			) : null}

			{/* 1 — Lane */}
			<Section step="1" title="Select IMG lane">
				<select
					value={laneId}
					onChange={(e) => setLaneId(e.target.value)}
					className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
				>
					<option value="">Select a lane…</option>
					{lanes.map((l) => (
						<option key={l.lane_id} value={l.lane_id}>
							{l.label}
						</option>
					))}
				</select>
				{lane ? (
					<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
						<div className="flex flex-wrap gap-2">
							<span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-2.5 py-1 text-[10px] font-semibold text-blue-200">
								{lane.default_semantic_role}
							</span>
							{lane.default_allowed_modes.map((m) => (
								<span
									key={m}
									className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-[10px] font-semibold text-slate-300"
								>
									{m}
								</span>
							))}
							{lane.default_contains_rendered_text ? (
								<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold text-amber-200">
									Poster (rendered text) — not a clean video frame
								</span>
							) : (
								<span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold text-emerald-200">
									Clean frame — video-support eligible
								</span>
							)}
						</div>
						<div className="mt-2 text-[10px] text-slate-500">{lane.purpose}</div>
					</div>
				) : null}
			</Section>

			{/* 2 — Product */}
			<Section step="2" title="Select product (product picker, not a raw ID)">
				<SearchableProductSelect
					products={[]}
					selectedProduct={selectedProduct}
					onSelect={setSelectedProduct}
				/>
				{productMissing ? (
					<p className="text-[10px] text-amber-300/70">
						This lane requires a product to preserve product truth.
					</p>
				) : null}
			</Section>

			{/* 3 — Avatar */}
			<Section step="3" title="Generate / select avatar (character reference)">
				<AssetSelect
					label="Avatar (CHARACTER_REFERENCE · approved only)"
					assets={approvedCharacters}
					value={characterAssetId}
					onChange={setCharacterAssetId}
					emptyHint="No APPROVED avatars in Library — generate + approve one first"
				/>
				<button
					type="button"
					onClick={() => navigate("/assets/avatar-registry")}
					className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-[11px] font-semibold text-blue-100 hover:bg-blue-500/20"
				>
					Generate a new avatar in Avatar Registry →
				</button>
			</Section>

			{/* 4 — Scene / Style */}
			<Section step="4" title="Select scene / style references">
				<div className="grid gap-3 md:grid-cols-2">
					<AssetSelect
						label="Scene (SCENE_CONTEXT_REFERENCE · approved only)"
						assets={approvedScenes}
						value={sceneAssetId}
						onChange={setSceneAssetId}
						emptyHint="No APPROVED scene references in Library"
					/>
					<AssetSelect
						label="Style (STYLE_REFERENCE · approved only)"
						assets={approvedStyles}
						value={styleAssetId}
						onChange={setStyleAssetId}
						emptyHint="No APPROVED style references in Library"
					/>
				</div>
			</Section>

			{/* 5 — Prompt preview */}
			<Section step="5" title="Preview prompt">
				<textarea
					value={prompt}
					onChange={(e) => setPrompt(e.target.value)}
					className="h-32 w-full rounded-xl border border-slate-800 bg-slate-950 p-3 text-xs text-slate-200 font-mono"
					placeholder="Describe the IMG output, or compile a suggested prompt from the selected product."
				/>
				<button
					type="button"
					onClick={() => void handleCompilePrompt()}
					disabled={!selectedProduct || compiling}
					className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-[11px] font-semibold text-slate-200 disabled:opacity-40"
				>
					{compiling ? "Compiling…" : "Compile suggested prompt (uses product)"}
				</button>
			</Section>

			{/* 6 — Gated Generate */}
			<Section step="6" title="Generate image output (gated · credit-spending)">
				<div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100">
					Live generation calls the real one-door lane
					(<code>POST /api/flow/generate</code> mode:IMG) — it spends credits and
					uses live Google Flow. It only runs after an explicit confirmation and{" "}
					<strong>never auto-fires</strong>. Build-session status:{" "}
					<strong>{GEN_NOT_FIRED}</strong> · <strong>{GEN_RUNTIME_UNVERIFIED}</strong>.
				</div>
				<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
					<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
						Generate payload preview
					</div>
					<div className="mt-1">
						References sent as image_media_ids:{" "}
						<strong>
							{genResolution.mediaIds.length > 0
								? genResolution.mediaIds.join(", ")
								: "(none — text-only prompt)"}
						</strong>
					</div>
					{genResolution.refs.length > 0 ? (
						<ul className="mt-1 space-y-0.5">
							{genResolution.refs.map((r) => (
								<li key={`${r.role}:${r.label}`}>
									{r.role}: {r.label} —{" "}
									{r.mediaId ? (
										<span className="text-emerald-300">
											resolved ({r.mediaId})
										</span>
									) : (
										<span className="text-amber-300">
											unresolved (no media id — not sent)
										</span>
									)}
								</li>
							))}
						</ul>
					) : null}
					{genResolution.blocked ? (
						<div className="mt-2 rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-1 text-red-200">
							{genResolution.blockReason}
						</div>
					) : null}
				</div>
				<button
					type="button"
					onClick={() => setShowGenConfirm(true)}
					disabled={!prompt.trim() || generating || genResolution.blocked}
					className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-xs font-bold text-rose-100 disabled:opacity-40"
				>
					{generating ? "Generating (live)…" : "Generate (live · spends credits)"}
				</button>
				{genJob ? (
					<div className="text-[11px] text-slate-300">
						Job status: <strong>{genJob.status}</strong>
						{genJob.media_id ? ` · media ${genJob.media_id}` : ""}
					</div>
				) : null}
				<p className="text-[10px] text-slate-500">
					Prefer the credit-free path below: register a real output (a finished
					artifact or an upload), review, then save.
				</p>
			</Section>

			{/* 7 — Register output */}
			<Section step="7" title="Register a real output (credit-free)">
				<div className="flex gap-1 rounded-lg border border-slate-700 bg-slate-950 p-0.5 text-[10px] font-semibold uppercase tracking-[0.14em]">
					<button
						type="button"
						onClick={() => setOutputMode("artifact")}
						className={`flex-1 rounded-md px-3 py-1 ${outputMode === "artifact" ? "bg-blue-600 text-white" : "text-slate-400"}`}
					>
						Finished artifact
					</button>
					<button
						type="button"
						onClick={() => setOutputMode("upload")}
						className={`flex-1 rounded-md px-3 py-1 ${outputMode === "upload" ? "bg-blue-600 text-white" : "text-slate-400"}`}
					>
						Upload file
					</button>
				</div>
				{outputMode === "artifact" ? (
					<select
						value={artifactMediaId}
						onChange={(e) => setArtifactMediaId(e.target.value)}
						className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
					>
						<option value="">
							{artifacts.length === 0
								? "No finished image artifacts yet"
								: "Select a finished image artifact…"}
						</option>
						{artifacts.map((a) => (
							<option key={a.media_id} value={a.media_id}>
								{a.media_id}
								{a.size_mb ? ` · ${a.size_mb}MB` : ""}
							</option>
						))}
					</select>
				) : (
					<input
						type="file"
						accept="image/*"
						onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
						className="w-full text-[11px] text-slate-400 file:mr-3 file:rounded-md file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-slate-200"
					/>
				)}
			</Section>

			{/* 8 — Review / approve / reject */}
			<Section step="8" title="Review / approve / reject">
				<div className="grid gap-3 md:grid-cols-3">
					{(
						[
							["Identity lock", identityStatus, setIdentityStatus],
							["Scale truth", scaleStatus, setScaleStatus],
							["Claim safety", claimStatus, setClaimStatus],
						] as const
					).map(([label, val, set]) => (
						<label key={label} className="block text-[11px] text-slate-300 space-y-1">
							<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
								{label}
							</span>
							<select
								value={val}
								onChange={(e) => set(e.target.value as TruthStatus)}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
							>
								<option value="UNVERIFIED">UNVERIFIED</option>
								<option value="PASS">PASS</option>
								<option value="FAIL">FAIL</option>
							</select>
						</label>
					))}
				</div>
				<div className="flex flex-wrap gap-2">
					{(["PENDING_REVIEW", "APPROVED", "REJECTED"] as const).map((d) => (
						<button
							type="button"
							key={d}
							onClick={() => setReviewDecision(d)}
							className={`rounded-lg border px-3 py-1.5 text-[11px] font-semibold ${reviewDecision === d ? "border-blue-500 bg-blue-600/20 text-blue-100" : "border-slate-700 bg-slate-950 text-slate-400"}`}
						>
							{d}
						</button>
					))}
				</div>
				{approvalBlocked ? (
					<p className="text-[10px] text-amber-300/80">
						APPROVED requires Identity / Scale / Claim to ALL be PASS (UNVERIFIED
						or FAIL blocks approval) — mirrors the backend
						APPROVAL_REQUIRES_ALL_TRUTH_PASS gate.
					</p>
				) : null}
			</Section>

			{/* 9 — Save */}
			<Section step="9" title="Save to Creative Library">
				<label className="block text-[11px] text-slate-300 space-y-1">
					<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
						Display name
					</span>
					<input
						value={displayName}
						onChange={(e) => setDisplayName(e.target.value)}
						className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
						placeholder="e.g. Avatar A — front"
					/>
				</label>
				<button
					type="button"
					onClick={() => void handleSave()}
					disabled={!canSave}
					className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-purple-600 py-3 text-sm font-bold text-white disabled:opacity-50 disabled:grayscale"
				>
					{saving ? "Saving…" : "Save to Creative Library"}
				</button>
				{savedAsset ? (
					<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-100">
						Saved <strong>{savedAsset.display_name}</strong> as{" "}
						<strong>{savedAsset.semantic_role}</strong> ·{" "}
						<strong>{savedAsset.review_status}</strong>
						{savedAsset.allowed_modes.length > 0
							? ` · reusable in ${savedAsset.allowed_modes.join(", ")}`
							: " · terminal asset (no video reuse)"}
						.
					</div>
				) : null}
			</Section>

			{/* 10 — Reuse visibility */}
			<Section step="10" title="Reuse in I2V / F2V">
				<div className="text-[11px] text-slate-300 space-y-2">
					<p>
						Only <strong>APPROVED</strong>, ACTIVE references are reusable. Saved{" "}
						<strong>CHARACTER</strong> / <strong>SCENE</strong> /{" "}
						<strong>STYLE</strong> assets become selectable in the{" "}
						<strong>Ingredients (I2V)</strong> resolver once approved — it rejects{" "}
						PENDING_REVIEW and REJECTED assets (<code>NOT_APPROVED_FOR_REUSE</code>).
					</p>
					<p>
						Approved <strong>COMPOSITE_FRAME_REFERENCE</strong> assets are
						selectable as <strong>Frames (F2V)</strong> start / end frames via the
						composite frame picker (validated by the backend F2V resolver);
						posters (rendered text), archived, and non-approved assets are excluded.
					</p>
					<div className="flex gap-2">
						<button
							type="button"
							onClick={() => navigate("/operator/i2v")}
							className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-[11px] font-semibold text-slate-200"
						>
							Open I2V (Ingredients) →
						</button>
						<button
							type="button"
							onClick={() => navigate("/assets/creative-library")}
							className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-[11px] font-semibold text-slate-200"
						>
							Open Creative Library →
						</button>
					</div>
				</div>
			</Section>

			{showGenConfirm ? (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
					<div className="max-w-md rounded-2xl border border-rose-500/40 bg-slate-950 p-5 space-y-3">
						<div className="text-sm font-bold text-rose-100">
							Confirm live credit-spending generation
						</div>
						<div className="text-[11px] text-slate-300">
							This calls live Google Flow and <strong>spends credits</strong>. It
							will not run without this confirmation. (In the build session this
							path is <strong>{GEN_NOT_FIRED}</strong>.)
						</div>
						<div className="flex justify-end gap-2">
							<button
								type="button"
								onClick={() => setShowGenConfirm(false)}
								className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-[11px] font-semibold text-slate-300"
							>
								Cancel
							</button>
							<button
								type="button"
								onClick={() => void handleConfirmedGenerate()}
								className="rounded-lg border border-rose-500/40 bg-rose-500/20 px-3 py-1.5 text-[11px] font-bold text-rose-100"
							>
								Confirm &amp; Generate (live)
							</button>
						</div>
					</div>
				</div>
			) : null}
		</div>
	);
}
