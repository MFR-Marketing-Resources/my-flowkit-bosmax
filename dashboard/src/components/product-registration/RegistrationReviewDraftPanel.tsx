import { useEffect, useMemo, useState } from "react";
import { patchAPI, postAPI } from "../../api/client";
import type {
	RegistrationCommitResponse,
	RegistrationReviewDraft,
	RegistrationReviewDraftEvidencePatchRequest,
} from "../../types";

interface Props {
	draft: RegistrationReviewDraft;
	onUpdate: (updated: RegistrationReviewDraft) => void;
	onClear: () => void;
}

interface EvidenceEditorState {
	product_name: string;
	product_knowledge_text: string;
	benefits_text: string;
	usage_text: string;
	target_customer_text: string;
	ingredients_text: string;
	warnings_text: string;
	paste_anything_about_product: string;
	price: string;
	currency: string;
	commission_amount: string;
	commission_rate: string;
	size_or_volume: string;
	package_notes: string;
	product_url: string;
	source_url: string;
	tiktok_product_url: string;
	tiktok_shop_url: string;
	image_url: string;
	hook_angles: string;
	cta_angles: string;
}

function toText(value: unknown): string {
	if (Array.isArray(value)) {
		return value
			.map((entry) => String(entry ?? "").trim())
			.filter(Boolean)
			.join("\n");
	}
	return String(value ?? "");
}

function trimOrEmpty(value: string): string {
	return value.trim();
}

function parseNumber(value: string): number | undefined {
	const normalized = value.trim();
	if (!normalized) return undefined;
	const parsed = Number(normalized);
	return Number.isFinite(parsed) ? parsed : undefined;
}

function splitLines(value: string): string[] {
	return value
		.split(/\r?\n/)
		.map((entry) => entry.trim())
		.filter(Boolean);
}

function readFileAsDataUrl(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ""));
		reader.onerror = () =>
			reject(reader.error || new Error("Failed to read image file"));
		reader.readAsDataURL(file);
	});
}

function buildEvidenceEditorState(
	draft: RegistrationReviewDraft,
): EvidenceEditorState {
	const evidence = draft.declared_evidence_fields;
	const candidates = draft.canonical_candidate_fields;
	return {
		product_name: toText(evidence.product_name),
		product_knowledge_text: toText(evidence.product_knowledge_text),
		benefits_text: toText(evidence.benefits_text),
		usage_text: toText(evidence.usage_text),
		target_customer_text: toText(
			evidence.target_customer_text || candidates.target_customer,
		),
		ingredients_text: toText(evidence.ingredients_text),
		warnings_text: toText(evidence.warnings_text),
		paste_anything_about_product: toText(evidence.paste_anything_about_product),
		price: toText(evidence.price),
		currency: toText(evidence.currency || "MYR"),
		commission_amount: toText(evidence.commission_amount),
		commission_rate: toText(evidence.commission_rate),
		size_or_volume: toText(
			evidence.size_or_volume || candidates.size_or_volume,
		),
		package_notes: toText(evidence.package_notes || candidates.package_notes),
		product_url: toText(evidence.product_url),
		source_url: toText(evidence.source_url),
		tiktok_product_url: toText(evidence.tiktok_product_url),
		tiktok_shop_url: toText(evidence.tiktok_shop_url),
		image_url: toText(evidence.image_url),
		hook_angles: toText(evidence.hook_angles || candidates.hook_angles),
		cta_angles: toText(evidence.cta_angles || candidates.cta_angles),
	};
}

function EvidenceInput({
	label,
	value,
	onChange,
	placeholder,
	type = "text",
}: {
	label: string;
	value: string;
	onChange: (value: string) => void;
	placeholder?: string;
	type?: "text" | "number" | "url";
}) {
	return (
		<div className="space-y-2">
			<p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
				{label}
			</p>
			<input
				type={type}
				value={value}
				onChange={(event) => onChange(event.target.value)}
				placeholder={placeholder}
				className="w-full rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-xs text-slate-100 outline-none transition-all focus:border-indigo-500/50"
			/>
		</div>
	);
}

function EvidenceTextarea({
	label,
	value,
	onChange,
	placeholder,
	rows = 4,
}: {
	label: string;
	value: string;
	onChange: (value: string) => void;
	placeholder?: string;
	rows?: number;
}) {
	return (
		<div className="space-y-2">
			<p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
				{label}
			</p>
			<textarea
				value={value}
				onChange={(event) => onChange(event.target.value)}
				placeholder={placeholder}
				rows={rows}
				className="w-full rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-xs text-slate-100 outline-none transition-all focus:border-indigo-500/50"
			/>
		</div>
	);
}

export default function RegistrationReviewDraftPanel({
	draft,
	onUpdate,
	onClear,
}: Props) {
	const [approvals, setApprovals] = useState<Record<string, boolean>>(
		draft.approval_checklist,
	);
	const [evidenceForm, setEvidenceForm] = useState<EvidenceEditorState>(() =>
		buildEvidenceEditorState(draft),
	);
	const [isCommitting, setIsCommitting] = useState(false);
	const [showConfirm, setShowConfirm] = useState(false);
	const [confirmPhrase, setConfirmPhrase] = useState("");
	const [commitResult, setCommitResult] =
		useState<RegistrationCommitResponse | null>(null);
	const [isUpdating, setIsUpdating] = useState(false);
	const [isSavingEvidence, setIsSavingEvidence] = useState(false);
	const [pendingImageBase64, setPendingImageBase64] = useState<string>("");
	const [pendingImageFilename, setPendingImageFilename] = useState<string>("");
	const [pendingImagePreview, setPendingImagePreview] = useState<string>("");
	const [saveMessage, setSaveMessage] = useState<string>("");

	useEffect(() => {
		setApprovals(draft.approval_checklist);
		setEvidenceForm(buildEvidenceEditorState(draft));
		setPendingImageBase64("");
		setPendingImageFilename("");
		setPendingImagePreview("");
	}, [draft]);

	const imagePreviewUrl = useMemo(() => {
		if (pendingImagePreview) return pendingImagePreview;
		const imageUrl = trimOrEmpty(evidenceForm.image_url);
		if (imageUrl) return imageUrl;
		const localImagePath = String(
			draft.declared_evidence_fields.local_image_path || "",
		).trim();
		if (localImagePath) {
			return `/api/product-registration/review-drafts/${draft.review_draft_id}/image?ts=${encodeURIComponent(draft.updated_at || draft.last_recomputed_at || "")}`;
		}
		return "";
	}, [draft, evidenceForm.image_url, pendingImagePreview]);

	const toggleApproval = async (field: string) => {
		if (isUpdating || draft.review_status === "COMMITTED") return;

		const newStatus = !approvals[field];
		setIsUpdating(true);

		try {
			const updated = await patchAPI<RegistrationReviewDraft>(
				`/api/product-registration/review-drafts/${draft.review_draft_id}/field-decisions`,
				{
					approved_fields: newStatus ? [field] : [],
					rejected_fields: !newStatus ? [field] : [],
					edited_declared_evidence: {},
					requested_more_evidence_fields: [],
				},
			);
			onUpdate(updated);
			setApprovals(updated.approval_checklist);
		} catch (err) {
			console.error("Failed to update field decision:", err);
		} finally {
			setIsUpdating(false);
		}
	};

	const handleImageUpload = async (
		event: React.ChangeEvent<HTMLInputElement>,
	) => {
		const file = event.target.files?.[0];
		if (!file) return;
		try {
			const imageBase64 = await readFileAsDataUrl(file);
			setPendingImageBase64(imageBase64);
			setPendingImageFilename(file.name);
			setPendingImagePreview(imageBase64);
			setSaveMessage(`Draft image queued: ${file.name}`);
		} catch (err) {
			console.error("Failed to read selected image:", err);
			setSaveMessage("Failed to read selected image.");
		}
	};

	const handleEvidenceSave = async (recompute: boolean) => {
		setIsSavingEvidence(true);
		setSaveMessage("");
		const payload: RegistrationReviewDraftEvidencePatchRequest = {
			product_name: trimOrEmpty(evidenceForm.product_name),
			product_knowledge_text: trimOrEmpty(evidenceForm.product_knowledge_text),
			benefits_text: trimOrEmpty(evidenceForm.benefits_text),
			usage_text: trimOrEmpty(evidenceForm.usage_text),
			target_customer_text: trimOrEmpty(evidenceForm.target_customer_text),
			ingredients_text: trimOrEmpty(evidenceForm.ingredients_text),
			warnings_text: trimOrEmpty(evidenceForm.warnings_text),
			paste_anything_about_product: trimOrEmpty(
				evidenceForm.paste_anything_about_product,
			),
			price: parseNumber(evidenceForm.price),
			currency: trimOrEmpty(evidenceForm.currency),
			commission_amount: parseNumber(evidenceForm.commission_amount),
			commission_rate: trimOrEmpty(evidenceForm.commission_rate),
			size_or_volume: trimOrEmpty(evidenceForm.size_or_volume),
			package_notes: trimOrEmpty(evidenceForm.package_notes),
			product_url: trimOrEmpty(evidenceForm.product_url),
			source_url: trimOrEmpty(evidenceForm.source_url),
			tiktok_product_url: trimOrEmpty(evidenceForm.tiktok_product_url),
			tiktok_shop_url: trimOrEmpty(evidenceForm.tiktok_shop_url),
			image_url: trimOrEmpty(evidenceForm.image_url),
			hook_angles: splitLines(evidenceForm.hook_angles),
			cta_angles: splitLines(evidenceForm.cta_angles),
			recompute,
		};
		if (pendingImageBase64) {
			payload.image_base64 = pendingImageBase64;
			payload.image_filename = pendingImageFilename;
		}

		try {
			const updated = await patchAPI<RegistrationReviewDraft>(
				`/api/product-registration/review-drafts/${draft.review_draft_id}/evidence`,
				payload,
			);
			onUpdate(updated);
			setSaveMessage(
				recompute
					? "Draft evidence saved and recomputed."
					: "Draft evidence saved. Recompute is still required before commit.",
			);
			setPendingImageBase64("");
			setPendingImageFilename("");
			setPendingImagePreview("");
		} catch (err) {
			console.error("Failed to update draft evidence:", err);
			setSaveMessage(
				err instanceof Error ? err.message : "Failed to save draft evidence.",
			);
		} finally {
			setIsSavingEvidence(false);
		}
	};

	const handleCommit = async () => {
		if (confirmPhrase !== "REGISTER_OWNED_PRODUCT") return;

		setIsCommitting(true);
		try {
			const result = await postAPI<RegistrationCommitResponse>(
				`/api/product-registration/review-drafts/${draft.review_draft_id}/commit`,
				{
					draft_id: draft.review_draft_id,
					write_back_confirmed: true,
					user_confirmation_phrase: confirmPhrase,
					commit_reason: "Manual registration approval",
				},
			);
			setCommitResult(result);
			if (result.commit_status === "COMMITTED") {
				const updated = await patchAPI<RegistrationReviewDraft>(
					`/api/product-registration/review-drafts/${draft.review_draft_id}/field-decisions`,
					{
						approved_fields: [],
						rejected_fields: [],
						edited_declared_evidence: {},
						requested_more_evidence_fields: [],
					},
				);
				onUpdate(updated);
				setShowConfirm(false);
			}
		} catch (err) {
			console.error("Commit failed:", err);
			setCommitResult({
				commit_status: "FAILED",
				write_back_performed: false,
				errors: ["Network or server error"],
			});
		} finally {
			setIsCommitting(false);
		}
	};

	const exportJSON = () => {
		const data = { ...draft, approval_checklist: approvals };
		const blob = new Blob([JSON.stringify(data, null, 2)], {
			type: "application/json",
		});
		const url = window.URL.createObjectURL(blob);
		const anchor = document.createElement("a");
		anchor.href = url;
		anchor.download = `${draft.review_draft_id}.json`;
		anchor.click();
	};

	const getStatusColor = (status: string) => {
		switch (status) {
			case "COMMITTED":
				return "text-blue-400 bg-blue-400/10";
			case "REVIEW_READY":
				return "text-emerald-400 bg-emerald-400/10";
			case "NEEDS_HUMAN_REVIEW":
				return "text-amber-400 bg-amber-400/10";
			case "BLOCKED":
				return "text-red-400 bg-red-400/10";
			default:
				return "text-slate-400 bg-slate-400/10";
		}
	};

	const isFresh = draft.draft_freshness_status === "FRESH";
	const unresolvedReviewFields = draft.human_review_fields.filter((field) => {
		if (approvals[field] === undefined) return false;
		return !approvals[field];
	});
	const isReadyToCommit =
		draft.review_status !== "BLOCKED" &&
		draft.review_status !== "COMMITTED" &&
		draft.claim_gate !== "CLAIM_BLOCKED" &&
		isFresh &&
		draft.missing_required_evidence.length === 0 &&
		approvals.normalized_name === true &&
		unresolvedReviewFields.length === 0;

	return (
		<div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
			<div className="flex flex-col gap-4 rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-xl md:flex-row md:items-center md:justify-between">
				<div className="flex items-center gap-4">
					<div className="rounded-xl border border-indigo-500/20 bg-indigo-500/10 p-3 text-indigo-400">
						<svg
							aria-hidden="true"
							className="h-6 w-6"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								strokeLinecap="round"
								strokeLinejoin="round"
								strokeWidth={2}
								d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"
							/>
						</svg>
					</div>
					<div>
						<div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
							Review Draft ID
						</div>
						<h3 className="text-lg font-bold text-white">
							{draft.review_draft_id}
						</h3>
					</div>
				</div>

				<div className="flex items-center gap-6">
					<div className="text-right">
						<div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">
							Status
						</div>
						<span
							className={`rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider ${getStatusColor(draft.review_status)}`}
						>
							{draft.review_status}
						</span>
					</div>
					<div className="hidden h-10 w-px bg-slate-800 md:block" />
					<button
						type="button"
						onClick={onClear}
						className="px-4 py-2 text-xs font-bold text-slate-400 transition-colors hover:text-white"
					>
						Clear Draft
					</button>
				</div>
			</div>

			<div
				className={`flex items-center gap-3 rounded-xl border p-4 ${
					draft.review_status === "COMMITTED"
						? "border-blue-500/30 bg-blue-500/10"
						: "border-blue-500/20 bg-blue-500/5"
				}`}
			>
				<svg
					aria-hidden="true"
					className="h-5 w-5 shrink-0 text-blue-400"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
				>
					<path
						strokeLinecap="round"
						strokeLinejoin="round"
						strokeWidth={2}
						d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
					/>
				</svg>
				<p className="text-xs font-medium text-blue-300">
					Governance:{" "}
					<span className="font-bold">{draft.write_back_status}</span>.
					{draft.review_status === "COMMITTED"
						? " This product has been committed to the canonical database."
						: " Controlled write-back now requires refreshed evidence, reviewed candidates, and the confirmation phrase."}
				</p>
			</div>

			<section className="rounded-2xl border border-indigo-500/20 bg-slate-900/60 p-6">
				<div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
					<div>
						<h4 className="text-sm font-bold uppercase tracking-wider text-white">
							Complete Missing Evidence
						</h4>
						<p className="mt-1 text-xs text-slate-400">
							Use this editor to complete evidence, attach draft image proof,
							and recompute the registration snapshot before commit.
						</p>
					</div>
					<div className="grid grid-cols-1 gap-2 text-[10px] uppercase tracking-widest text-slate-400 md:grid-cols-3">
						<div className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2">
							<div className="font-bold text-slate-500">Draft Freshness</div>
							<div className={isFresh ? "text-emerald-400" : "text-amber-400"}>
								{draft.draft_freshness_status}
							</div>
						</div>
						<div className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2">
							<div className="font-bold text-slate-500">Image Asset</div>
							<div
								className={
									draft.image_asset_status.includes("READY")
										? "text-emerald-400"
										: "text-amber-400"
								}
							>
								{draft.image_asset_status}
							</div>
						</div>
						<div className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2">
							<div className="font-bold text-slate-500">Vision Provider</div>
							<div className="text-sky-300">
								{String(
									draft.system_inferred_fields.image_analysis_status ||
										"UNKNOWN",
								)}
							</div>
						</div>
					</div>
				</div>

				{draft.missing_required_evidence.length > 0 ? (
					<div className="mb-4 rounded-xl border border-amber-500/20 bg-amber-500/10 p-4">
						<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-amber-400">
							Missing Evidence
						</div>
						<div className="mt-2 flex flex-wrap gap-2">
							{draft.missing_required_evidence.map((field) => (
								<span
									key={field}
									className="rounded-full border border-amber-500/20 bg-slate-900 px-2 py-1 text-[10px] font-bold uppercase text-amber-300"
								>
									{field}
								</span>
							))}
						</div>
					</div>
				) : null}

				<div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
					<div className="space-y-4">
						<EvidenceInput
							label="Product Name"
							value={evidenceForm.product_name}
							onChange={(value) =>
								setEvidenceForm((current) => ({
									...current,
									product_name: value,
								}))
							}
							placeholder="Bosmax Herbs"
						/>
						<EvidenceTextarea
							label="Product Knowledge Text"
							value={evidenceForm.product_knowledge_text}
							onChange={(value) =>
								setEvidenceForm((current) => ({
									...current,
									product_knowledge_text: value,
								}))
							}
							placeholder="Core product description, source facts, and owned narrative."
						/>
						<EvidenceTextarea
							label="Benefits Text"
							value={evidenceForm.benefits_text}
							onChange={(value) =>
								setEvidenceForm((current) => ({
									...current,
									benefits_text: value,
								}))
							}
							placeholder="Benefits and USP from the seller or product owner."
						/>
						<EvidenceTextarea
							label="Usage Text"
							value={evidenceForm.usage_text}
							onChange={(value) =>
								setEvidenceForm((current) => ({
									...current,
									usage_text: value,
								}))
							}
							placeholder="How the product is used."
						/>
						<EvidenceTextarea
							label="Target Customer Text"
							value={evidenceForm.target_customer_text}
							onChange={(value) =>
								setEvidenceForm((current) => ({
									...current,
									target_customer_text: value,
								}))
							}
							placeholder="Who this product is for."
							rows={3}
						/>
						<EvidenceTextarea
							label="Ingredients Text"
							value={evidenceForm.ingredients_text}
							onChange={(value) =>
								setEvidenceForm((current) => ({
									...current,
									ingredients_text: value,
								}))
							}
							placeholder="Ingredients, materials, or formulation notes."
							rows={3}
						/>
						<EvidenceTextarea
							label="Warnings Text"
							value={evidenceForm.warnings_text}
							onChange={(value) =>
								setEvidenceForm((current) => ({
									...current,
									warnings_text: value,
								}))
							}
							placeholder="Warnings, pantang, or restrictions."
							rows={3}
						/>
						<EvidenceTextarea
							label="Paste Anything About Product"
							value={evidenceForm.paste_anything_about_product}
							onChange={(value) =>
								setEvidenceForm((current) => ({
									...current,
									paste_anything_about_product: value,
								}))
							}
							placeholder="Raw seller text, scraped notes, or manual paste for re-extraction."
							rows={4}
						/>
					</div>

					<div className="space-y-4">
						<div className="grid grid-cols-1 gap-4 md:grid-cols-2">
							<EvidenceInput
								label="Price"
								type="number"
								value={evidenceForm.price}
								onChange={(value) =>
									setEvidenceForm((current) => ({ ...current, price: value }))
								}
								placeholder="0.00"
							/>
							<EvidenceInput
								label="Currency"
								value={evidenceForm.currency}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										currency: value,
									}))
								}
								placeholder="MYR"
							/>
							<EvidenceInput
								label="Commission Amount"
								type="number"
								value={evidenceForm.commission_amount}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										commission_amount: value,
									}))
								}
								placeholder="0.00"
							/>
							<EvidenceInput
								label="Commission Rate"
								value={evidenceForm.commission_rate}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										commission_rate: value,
									}))
								}
								placeholder="15%"
							/>
							<EvidenceInput
								label="Size / Volume"
								value={evidenceForm.size_or_volume}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										size_or_volume: value,
									}))
								}
								placeholder="5 ML"
							/>
							<EvidenceInput
								label="Package Notes"
								value={evidenceForm.package_notes}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										package_notes: value,
									}))
								}
								placeholder="Dropper bottle, trial size, etc."
							/>
						</div>

						<div className="grid grid-cols-1 gap-4 md:grid-cols-2">
							<EvidenceInput
								label="Product URL"
								type="url"
								value={evidenceForm.product_url}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										product_url: value,
									}))
								}
								placeholder="https://"
							/>
							<EvidenceInput
								label="Source URL"
								type="url"
								value={evidenceForm.source_url}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										source_url: value,
									}))
								}
								placeholder="https://"
							/>
							<EvidenceInput
								label="TikTok Product URL"
								type="url"
								value={evidenceForm.tiktok_product_url}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										tiktok_product_url: value,
									}))
								}
								placeholder="https://shop.tiktok.com/..."
							/>
							<EvidenceInput
								label="TikTok Shop URL"
								type="url"
								value={evidenceForm.tiktok_shop_url}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										tiktok_shop_url: value,
									}))
								}
								placeholder="https://shop.tiktok.com/..."
							/>
						</div>

						<div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
							<div className="grid grid-cols-1 gap-4 md:grid-cols-2">
								<EvidenceInput
									label="Image URL"
									type="url"
									value={evidenceForm.image_url}
									onChange={(value) =>
										setEvidenceForm((current) => ({
											...current,
											image_url: value,
										}))
									}
									placeholder="https://example.com/product.jpg"
								/>
								<div className="space-y-2">
									<p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
										Upload Product Image
									</p>
									<input
										type="file"
										accept="image/*"
										onChange={handleImageUpload}
										className="block w-full cursor-pointer text-xs text-slate-400 file:mr-4 file:rounded-lg file:border-0 file:bg-indigo-500/10 file:px-4 file:py-2 file:text-xs file:font-semibold file:text-indigo-300 hover:file:bg-indigo-500/20"
									/>
									<p className="text-[11px] text-slate-500">
										{pendingImageFilename
											? `Queued draft image: ${pendingImageFilename}`
											: "Optional. Upload here to cache draft image evidence before commit."}
									</p>
								</div>
							</div>

							<div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[240px_1fr]">
								<div className="space-y-2">
									<p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
										Image Preview
									</p>
									<div className="flex h-48 items-center justify-center overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
										{imagePreviewUrl ? (
											<img
												src={imagePreviewUrl}
												alt="Draft preview"
												className="h-full w-full object-contain"
											/>
										) : (
											<span className="px-4 text-center text-xs text-slate-500">
												No draft image attached yet.
											</span>
										)}
									</div>
								</div>
								<div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
									<div className="min-w-0 rounded-xl border border-slate-800 bg-slate-900/70 p-3">
										<div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
											Image Asset Status
										</div>
										<div className="mt-1 break-words text-sm font-semibold text-emerald-300">
											{draft.image_asset_status}
										</div>
										<p className="mt-2 break-words text-xs text-slate-400">
											{draft.image_asset_detail}
										</p>
									</div>
									<div className="min-w-0 rounded-xl border border-slate-800 bg-slate-900/70 p-3">
										<div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
											Semantic Vision Status
										</div>
										<div className="mt-1 break-words text-sm font-semibold text-sky-300">
											{String(
												draft.system_inferred_fields.image_analysis_status ||
													"UNKNOWN",
											)}
										</div>
										<p className="mt-2 break-words text-xs text-slate-400">
											Provider:{" "}
											{String(
												draft.system_inferred_fields.image_analysis_provider ||
													"not_configured",
											)}
										</p>
									</div>
								</div>
							</div>
						</div>

						<div className="grid grid-cols-1 gap-4 md:grid-cols-2">
							<EvidenceTextarea
								label="Hook Angles"
								value={evidenceForm.hook_angles}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										hook_angles: value,
									}))
								}
								placeholder="One hook angle per line."
								rows={6}
							/>
							<EvidenceTextarea
								label="CTA Angles"
								value={evidenceForm.cta_angles}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										cta_angles: value,
									}))
								}
								placeholder="One CTA angle per line."
								rows={6}
							/>
						</div>

						<div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
							<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
								Claim-Safe Review Notes
							</div>
							<p className="mt-2 text-xs leading-relaxed text-slate-300">
								{draft.copy_safety_notes ||
									"No additional claim-safe note stored for this draft."}
							</p>
						</div>
					</div>
				</div>

				<div className="mt-6 flex flex-col gap-3 border-t border-slate-800 pt-4 md:flex-row md:items-center md:justify-between">
					<div className="space-y-1 text-xs text-slate-400">
						<div>
							Last evidence edit:{" "}
							<span className="text-slate-200">
								{draft.last_evidence_edit_at || "N/A"}
							</span>
						</div>
						<div>
							Last recompute:{" "}
							<span className="text-slate-200">
								{draft.last_recomputed_at || "N/A"}
							</span>
						</div>
						{saveMessage ? (
							<div className="text-indigo-300">{saveMessage}</div>
						) : null}
					</div>
					<div className="flex flex-col gap-3 md:flex-row">
						<button
							type="button"
							onClick={() => handleEvidenceSave(false)}
							disabled={isSavingEvidence || draft.review_status === "COMMITTED"}
							className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-xs font-bold uppercase tracking-widest text-slate-200 transition-all hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{isSavingEvidence ? "Saving..." : "Save Draft Only"}
						</button>
						<button
							type="button"
							onClick={() => handleEvidenceSave(true)}
							disabled={isSavingEvidence || draft.review_status === "COMMITTED"}
							className="rounded-xl border border-indigo-500/40 bg-indigo-500 px-4 py-2 text-xs font-bold uppercase tracking-widest text-white transition-all hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{isSavingEvidence ? "Recomputing..." : "Save & Recompute"}
						</button>
					</div>
				</div>
			</section>

			<div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
				<div className="space-y-8">
					<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6">
						<h4 className="mb-4 flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-white">
							<span className="h-1.5 w-1.5 rounded-full bg-slate-500" />
							Declared Evidence
						</h4>
						<div className="space-y-3">
							{Object.entries(draft.declared_evidence_fields).map(
								([key, value]) => (
									<div
										key={key}
										className="flex items-start justify-between gap-4 rounded-lg border border-slate-700/50 bg-slate-800/30 p-3"
									>
										<span className="mt-1 shrink-0 text-[10px] font-bold uppercase text-slate-500">
											{key.replace(/_/g, " ")}
										</span>
										<span className="line-clamp-4 text-right text-xs text-slate-300">
											{Array.isArray(value) ? value.join(", ") : String(value)}
										</span>
									</div>
								),
							)}
						</div>
					</section>

					<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6">
						<h4 className="mb-4 flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-white">
							<span className="h-1.5 w-1.5 rounded-full bg-cyan-500" />
							System Inferred Fields
						</h4>
						<div className="space-y-3">
							{Object.entries(draft.system_inferred_fields).map(
								([key, value]) => (
									<div
										key={key}
										className="flex items-start justify-between gap-4 rounded-lg border border-slate-700/50 bg-slate-800/30 p-3"
									>
										<span className="mt-1 shrink-0 text-[10px] font-bold uppercase text-slate-500">
											{key.replace(/_/g, " ")}
										</span>
										<span className="line-clamp-4 text-right text-xs text-slate-300">
											{Array.isArray(value) ? value.join(", ") : String(value)}
										</span>
									</div>
								),
							)}
						</div>
					</section>

					<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6">
						<h4 className="mb-4 flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-white">
							<span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
							Canonical Candidates
						</h4>
						<div className="space-y-3">
							{Object.entries(draft.canonical_candidate_fields).map(
								([key, value]) => {
									const isReviewRequired =
										draft.human_review_fields.includes(key);
									if (
										(value === null ||
											value === undefined ||
											value === "" ||
											(Array.isArray(value) && value.length === 0)) &&
										!isReviewRequired
									) {
										return null;
									}

									const isApproved = approvals[key];
									const isRejected = draft.rejection_checklist[key];
									return (
										<div
											key={key}
											className={`flex items-center justify-between rounded-lg border p-3 transition-all ${
												isApproved
													? "border-emerald-500/30 bg-emerald-500/5"
													: isRejected
														? "border-red-500/30 bg-red-500/5 opacity-60"
														: "border-slate-700/50 bg-slate-800/30"
											}`}
										>
											<div className="flex flex-col gap-1 overflow-hidden">
												<div className="flex items-center gap-2">
													<span className="text-[10px] font-bold uppercase text-slate-500">
														{key.replace(/_/g, " ")}
													</span>
													{isReviewRequired && !isApproved ? (
														<span className="rounded bg-amber-500/10 px-1 text-[8px] font-bold text-amber-500">
															REVIEW REQ
														</span>
													) : null}
												</div>
												<span className="truncate text-sm font-medium text-white">
													{Array.isArray(value)
														? value.join(", ")
														: String(value)}
												</span>
											</div>
											{draft.review_status !== "COMMITTED" ? (
												<button
													type="button"
													onClick={() => toggleApproval(key)}
													disabled={isUpdating}
													className={`ml-4 rounded-lg p-2 transition-all ${
														isApproved
															? "bg-emerald-500 text-white"
															: "bg-slate-700 text-slate-400 hover:bg-slate-600"
													} ${isUpdating ? "cursor-wait opacity-50" : ""}`}
												>
													{isApproved ? (
														<svg
															aria-hidden="true"
															className="h-4 w-4"
															fill="none"
															viewBox="0 0 24 24"
															stroke="currentColor"
														>
															<path
																strokeLinecap="round"
																strokeLinejoin="round"
																strokeWidth={2}
																d="M5 13l4 4L19 7"
															/>
														</svg>
													) : (
														<svg
															aria-hidden="true"
															className="h-4 w-4"
															fill="none"
															viewBox="0 0 24 24"
															stroke="currentColor"
														>
															<path
																strokeLinecap="round"
																strokeLinejoin="round"
																strokeWidth={2}
																d="M12 4v16m8-8H4"
															/>
														</svg>
													)}
												</button>
											) : null}
										</div>
									);
								},
							)}
						</div>
					</section>
				</div>

				<div className="space-y-8">
					<section
						className={`rounded-2xl border p-6 ${
							draft.claim_gate === "CLAIM_SAFE"
								? "border-emerald-500/20 bg-emerald-500/5"
								: draft.claim_gate === "CLAIM_BLOCKED"
									? "border-red-500/20 bg-red-500/5"
									: "border-amber-500/20 bg-amber-500/5"
						}`}
					>
						<h4 className="mb-4 text-sm font-bold uppercase tracking-wider text-white">
							Claim Safety Check
						</h4>
						<div className="space-y-4">
							<div className="flex items-center justify-between">
								<span className="text-[10px] font-bold uppercase text-slate-500">
									Status
								</span>
								<span
									className={`text-xs font-bold uppercase ${
										draft.claim_gate === "CLAIM_SAFE"
											? "text-emerald-400"
											: draft.claim_gate === "CLAIM_BLOCKED"
												? "text-red-400"
												: "text-amber-400"
									}`}
								>
									{draft.claim_gate}
								</span>
							</div>
							{draft.claim_tokens.length > 0 ? (
								<div>
									<span className="mb-2 block text-[10px] font-bold uppercase text-slate-500">
										Detected Tokens
									</span>
									<div className="flex flex-wrap gap-2">
										{draft.claim_tokens.map((token) => (
											<span
												key={token}
												className="rounded border border-slate-700 bg-slate-800 px-2 py-0.5 text-[10px] text-slate-300"
											>
												{token}
											</span>
										))}
									</div>
								</div>
							) : null}
							{draft.copy_safety_notes ? (
								<div className="rounded-lg bg-black/20 p-3 text-xs italic leading-relaxed text-slate-400">
									{draft.copy_safety_notes}
								</div>
							) : null}
						</div>
					</section>

					<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6">
						<h4 className="mb-4 text-sm font-bold uppercase tracking-wider text-white">
							Authority Risks
						</h4>
						<div className="space-y-4">
							{draft.blocked_fields.length > 0 ? (
								<div className="space-y-2">
									<span className="text-[10px] font-bold uppercase text-red-500">
										Blocked Fields
									</span>
									<div className="flex flex-wrap gap-2">
										{draft.blocked_fields.map((field) => (
											<span
												key={field}
												className="rounded border border-red-500/20 bg-red-500/10 px-2 py-1 text-[10px] font-bold uppercase text-red-400"
											>
												{field}
											</span>
										))}
									</div>
								</div>
							) : null}
							{draft.human_review_fields.length > 0 ? (
								<div className="space-y-2">
									<span className="text-[10px] font-bold uppercase text-amber-500">
										Review Required ({unresolvedReviewFields.length} Remaining)
									</span>
									<div className="flex flex-wrap gap-2">
										{draft.human_review_fields.map((field) => (
											<span
												key={field}
												className={`rounded border px-2 py-1 text-[10px] font-bold uppercase ${
													approvals[field]
														? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400"
														: "border-amber-500/20 bg-amber-500/10 text-amber-400"
												}`}
											>
												{field}
											</span>
										))}
									</div>
								</div>
							) : null}
						</div>
					</section>

					<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6">
						<h4 className="mb-4 text-sm font-bold uppercase tracking-wider text-white">
							Mode Readiness
						</h4>
						<div className="space-y-4">
							{Object.entries(draft.readiness_by_mode).map(([mode, data]) => (
								<div key={mode} className="flex flex-col gap-1">
									<div className="flex items-center justify-between">
										<span className="text-[10px] font-bold uppercase text-slate-500">
											{mode.replace(/_/g, " ")}
										</span>
										<span
											className={`text-[10px] font-bold uppercase ${
												data.status === "READY"
													? "text-emerald-400"
													: "text-amber-400"
											}`}
										>
											{data.status}
										</span>
									</div>
									<div className="text-[10px] text-slate-500">
										{data.detail}
									</div>
									<div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-slate-800">
										<div
											className={`h-full transition-all duration-1000 ${
												data.status === "READY"
													? "w-full bg-emerald-500"
													: "w-1/2 bg-amber-500"
											}`}
										/>
									</div>
								</div>
							))}
						</div>
					</section>

					<div className="flex flex-col gap-4 pt-4">
						{!isFresh ? (
							<div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-200">
								Commit is blocked until this draft is recomputed. Current
								blocker: <strong>DRAFT_RECOMPUTE_REQUIRED</strong>.
							</div>
						) : null}

						<div className="flex gap-4">
							<button
								type="button"
								onClick={exportJSON}
								className="flex-1 rounded-xl border border-slate-700 bg-slate-800 px-4 py-3 text-xs font-bold uppercase tracking-widest text-white transition-all hover:bg-slate-700"
							>
								Export Draft JSON
							</button>
							<button
								type="button"
								onClick={() => setShowConfirm(true)}
								disabled={
									!isReadyToCommit || draft.review_status === "COMMITTED"
								}
								className={`flex-1 rounded-xl border px-4 py-3 text-xs font-bold uppercase tracking-widest transition-all ${
									isReadyToCommit && draft.review_status !== "COMMITTED"
										? "border-indigo-400 bg-indigo-500 text-white shadow-lg shadow-indigo-500/20 hover:bg-indigo-400"
										: "cursor-not-allowed border-indigo-500/10 bg-indigo-500/10 text-indigo-400/40"
								}`}
							>
								{draft.review_status === "COMMITTED"
									? "Committed"
									: "Commit to DB"}
							</button>
						</div>

						{showConfirm ? (
							<div className="animate-in zoom-in-95 rounded-2xl border border-indigo-500/50 bg-slate-900 p-6 shadow-2xl duration-200">
								<h5 className="mb-2 text-sm font-bold text-white">
									Registration Authority Gate
								</h5>
								<p className="mb-4 text-[10px] leading-relaxed text-slate-400">
									You are about to commit this product to the canonical
									database. This action remains blocked until evidence is fresh,
									missing evidence is resolved, and required review fields are
									approved.
								</p>
								<div className="space-y-3">
									<div>
										<p className="mb-1 text-[10px] font-bold uppercase text-slate-500">
											Confirmation Phrase
										</p>
										<input
											type="text"
											value={confirmPhrase}
											onChange={(event) => setConfirmPhrase(event.target.value)}
											placeholder="Type REGISTER_OWNED_PRODUCT"
											className="w-full rounded-lg border border-slate-700 bg-black/40 px-3 py-2 text-xs text-white outline-none transition-all placeholder:text-slate-600 focus:border-indigo-500"
										/>
									</div>
									<div className="flex gap-2">
										<button
											type="button"
											onClick={() => setShowConfirm(false)}
											className="flex-1 rounded-lg bg-slate-800 py-2 text-[10px] font-bold uppercase text-slate-400 transition-all hover:text-white"
										>
											Cancel
										</button>
										<button
											type="button"
											onClick={handleCommit}
											disabled={
												confirmPhrase !== "REGISTER_OWNED_PRODUCT" ||
												isCommitting
											}
											className={`flex-1 rounded-lg py-2 text-[10px] font-bold uppercase transition-all ${
												confirmPhrase === "REGISTER_OWNED_PRODUCT"
													? "bg-indigo-500 text-white shadow-lg shadow-indigo-500/20 hover:bg-indigo-400"
													: "cursor-not-allowed bg-slate-700 text-slate-500"
											}`}
										>
											{isCommitting ? "Committing..." : "Authorize Commit"}
										</button>
									</div>
								</div>
								{commitResult?.errors ? (
									<div className="mt-4 rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-[10px] font-medium text-red-400">
										{commitResult.errors.join(", ")}
									</div>
								) : null}
								{commitResult?.blocked_reasons?.length ? (
									<div className="mt-4 rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-[10px] font-medium text-amber-200">
										{commitResult.blocked_reasons.join(" | ")}
									</div>
								) : null}
							</div>
						) : null}
					</div>
				</div>
			</div>
		</div>
	);
}
