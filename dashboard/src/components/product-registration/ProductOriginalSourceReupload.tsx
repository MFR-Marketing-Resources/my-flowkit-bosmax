import {
	useRef,
	useState,
	type ChangeEvent,
} from "react";
import {
	fetchProductVisualReadiness,
	saveProductVisualSetup,
	uploadOriginalSourceCandidate,
	type ProductOriginalSourceCandidate,
} from "../../api/productVisualOnboarding";
import type { ProductVisualReadiness } from "../../types";

interface Props {
	productId: string;
	readiness?: ProductVisualReadiness;
	onChanged?: (readiness: ProductVisualReadiness) => void;
}

const CONFIRMATIONS = [
	["identity", "I confirmed the product identity matches the replacement image."],
	["label-logo", "I confirmed the label and logo match the product."],
	["geometry-scale", "I confirmed the product geometry and scale are consistent."],
	["product-isolation", "I confirmed the product is isolated from unrelated objects."],
] as const;

function readLocalPreview(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ""));
		reader.onerror = () => reject(reader.error || new Error("Could not preview the selected image."));
		reader.readAsDataURL(file);
	});
}

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : "The image could not be uploaded. Try again.";
}

export default function ProductOriginalSourceReupload({
	productId,
	readiness,
	onChanged,
}: Props) {
	const inputRef = useRef<HTMLInputElement>(null);
	const [candidate, setCandidate] = useState<ProductOriginalSourceCandidate | null>(null);
	const [previewUrl, setPreviewUrl] = useState<string | null>(null);
	const [reviewer, setReviewer] = useState("");
	const [note, setNote] = useState("");
	const [confirmations, setConfirmations] = useState<Record<string, boolean>>({});
	const [busy, setBusy] = useState<"upload" | "save" | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [message, setMessage] = useState<string | null>(null);

	const previousSha = readiness?.canonical_source_sha256 || "";
	const officialVisualBroken = readiness?.official_visual_status === "INVALID";
	if (!previousSha) return null;

	const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
		const file = event.target.files?.[0];
		event.target.value = "";
		if (!file) return;
		setBusy("upload");
		setError(null);
		setMessage(null);
		try {
			const [uploaded, localPreview] = await Promise.all([
				uploadOriginalSourceCandidate(productId, file),
				readLocalPreview(file),
			]);
			setCandidate(uploaded);
			setPreviewUrl(localPreview);
			setConfirmations({});
			setMessage("Replacement uploaded for review. It is not current until you explicitly re-authorize it.");
			const nextReadiness = await fetchProductVisualReadiness(productId);
			onChanged?.(nextReadiness);
		} catch (uploadError) {
			setError(errorMessage(uploadError));
		} finally {
			setBusy(null);
		}
	};

	const handleSave = async () => {
		if (!candidate) {
			setError("Upload a replacement image before saving.");
			return;
		}
		if (!reviewer.trim() || !note.trim()) {
			setError("Reviewer identity and a reauthorization note are required.");
			return;
		}
		if (CONFIRMATIONS.some(([key]) => !confirmations[key])) {
			setError("Confirm identity, label/logo, geometry/scale, and product isolation before saving.");
			return;
		}
		setBusy("save");
		setError(null);
		setMessage(null);
		try {
			await saveProductVisualSetup(productId, {
				selected_visual: "ORIGINAL_SOURCE_REAUTHORIZE",
				reviewed_by: reviewer.trim(),
				review_note: note.trim(),
				confirm_identity: Boolean(confirmations.identity),
				confirm_label_logo: Boolean(confirmations["label-logo"]),
				confirm_geometry_scale: Boolean(confirmations["geometry-scale"]),
				confirm_product_isolation: Boolean(confirmations["product-isolation"]),
				expected_previous_canonical_sha256: previousSha,
				expected_replacement_sha256: candidate.sha256,
				replacement_media_id: candidate.media_id,
			});
			const nextReadiness = await fetchProductVisualReadiness(productId);
			onChanged?.(nextReadiness);
			setCandidate(null);
			setPreviewUrl(null);
			setMessage("Original Source reauthorized. The prior Product Truth history was preserved.");
		} catch (saveError) {
			setError(errorMessage(saveError));
		} finally {
			setBusy(null);
		}
	};

	return (
		<section
			className="mb-5 rounded-2xl border border-indigo-500/30 bg-indigo-950/20 p-5 shadow-xl"
			data-testid="original-source-reupload"
		>
			<div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
				<div>
					<h3 className="text-base font-semibold text-white">Original Source Image</h3>
					<p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-400">
						{officialVisualBroken
							? "The persisted Official Product Visual is broken or unavailable. Upload a product-bound replacement, then explicitly re-authorize it."
							: readiness?.original_source_reauthorization_required
							? "The previous Original Source bytes are unavailable or changed. Upload a replacement, then explicitly re-authorize it."
							: "Upload a newer product image. Saving it requires explicit source reauthorization and preserves the existing Product Truth history."}
					</p>
				</div>
				<button
					type="button"
					className="rounded-xl border border-indigo-400/40 bg-indigo-500/15 px-3 py-2 text-xs font-semibold text-indigo-200 transition hover:bg-indigo-500/25 disabled:cursor-not-allowed disabled:opacity-50"
					onClick={() => inputRef.current?.click()}
					disabled={busy !== null}
					data-testid="update-reupload-product-image"
				>
					{busy === "upload" ? "Uploading…" : "Update / Reupload Product Image"}
				</button>
			</div>

			<input
				ref={inputRef}
				type="file"
				accept="image/jpeg,image/png,image/webp,image/gif"
				className="hidden"
				onChange={handleFileChange}
				data-testid="original-source-upload-input"
			/>

			{candidate && (
				<div className="mt-4 grid gap-4 lg:grid-cols-[180px_1fr]">
					<div className="overflow-hidden rounded-xl border border-slate-700 bg-slate-950">
						{previewUrl && (
							<img
								src={previewUrl}
								alt="Replacement product source preview"
								className="h-44 w-full object-contain"
							/>
						)}
					</div>
					<div className="space-y-3">
						<div className="text-xs text-slate-300">
							<div className="font-semibold text-white">{candidate.filename}</div>
							<div className="mt-1 text-slate-500">
								{candidate.width}×{candidate.height} · SHA-256 {candidate.sha256}
							</div>
						</div>
						<label className="block text-[10px] font-bold uppercase tracking-widest text-slate-500">
							Reviewer identity
							<input
								className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm font-normal normal-case tracking-normal text-white outline-none focus:border-indigo-500/50"
								value={reviewer}
								onChange={(event) => setReviewer(event.target.value)}
								placeholder="Who reviewed this replacement?"
								data-testid="original-source-reviewer"
							/>
						</label>
						<label className="block text-[10px] font-bold uppercase tracking-widest text-slate-500">
							Reauthorization note
							<textarea
								className="mt-1 min-h-20 w-full rounded-xl border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm font-normal normal-case tracking-normal text-white outline-none focus:border-indigo-500/50"
								value={note}
								onChange={(event) => setNote(event.target.value)}
								placeholder="Why is this newer image the correct product source?"
								data-testid="original-source-note"
							/>
						</label>
						<div className="space-y-2">
							{CONFIRMATIONS.map(([key, text]) => (
								<label key={key} className="flex items-start gap-2 text-xs text-slate-300">
									<input
										type="checkbox"
										checked={Boolean(confirmations[key])}
										onChange={(event) =>
											setConfirmations((previous) => ({ ...previous, [key]: event.target.checked }))
										}
										data-testid={`original-confirm-${key}`}
									/>
									<span>{text}</span>
								</label>
							))}
						</div>
						<button
							type="button"
							className="rounded-xl bg-emerald-500/20 px-3 py-2 text-xs font-semibold text-emerald-200 transition hover:bg-emerald-500/30 disabled:cursor-not-allowed disabled:opacity-50"
							onClick={handleSave}
							disabled={busy !== null}
							data-testid="save-original-source-reauthorization"
						>
							{busy === "save" ? "Saving…" : "Replace / Re-authorize Original Source"}
						</button>
					</div>
				</div>
			)}

			{message && <p className="mt-4 text-xs text-emerald-300">{message}</p>}
			{error && <p className="mt-4 text-xs text-red-300" role="alert">{error}</p>}
		</section>
	);
}
