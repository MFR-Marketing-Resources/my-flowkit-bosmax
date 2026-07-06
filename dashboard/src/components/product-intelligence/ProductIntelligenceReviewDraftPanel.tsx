import { useEffect, useMemo, useState } from "react";

import {
	approveProductIntelligenceReviewDraft,
	createProductIntelligenceReviewDraft,
	fetchProductIntelligenceReviewDraft,
	fetchProductIntelligenceReviewDrafts,
	rejectProductIntelligenceReviewDraft,
	updateProductIntelligenceReviewDraft,
	validateProductIntelligenceReviewDraft,
} from "../../api/products";
import type {
	ProductIntelligenceReviewDraft,
	ProductIntelligenceReviewDraftMutationRequest,
	ProductIntelligenceReviewDraftValidationResponse,
	ProductIntelligenceReviewFieldProvenanceInput,
} from "../../types";

const REQUIRED_FIELDS = [
	"product_description",
	"benefits_json",
	"usp_json",
	"usage_text",
	"ingredients_text",
	"warnings_text",
	"target_customer_text",
	"allowed_claims_json",
	"buyer_persona_snapshot_json",
	"copy_strategy_summary_json",
	"source_urls_json",
	"image_evidence_json",
	"claim_gate",
	"claim_risk_level",
] as const;

type DraftFormState = {
	product_description: string;
	benefits_json: string;
	usp_json: string;
	usage_text: string;
	ingredients_text: string;
	warnings_text: string;
	target_customer_text: string;
	paste_anything_summary: string;
	source_urls_json: string;
	image_evidence_json: string;
	package_notes: string;
	size_or_volume: string;
	product_form_factor: string;
	packaging_description: string;
	product_truth_lock: string;
	allowed_claims_json: string;
	blocked_claims_json: string;
	buyer_persona_snapshot_json: string;
	copy_strategy_summary_json: string;
	confidence_score: string;
	reviewer_note: string;
	created_by: string;
	reviewed_by: string;
};

type DraftProvenanceFormRow = ProductIntelligenceReviewFieldProvenanceInput & {
	key: string;
	confidence_score_text: string;
};

function fieldValue(value: string | null | undefined) {
	return value && value.trim().length > 0 ? value : "NOT_AVAILABLE";
}

function hasValue(value: unknown) {
	if (value === null || value === undefined) return false;
	if (typeof value === "string") return value.trim().length > 0;
	if (Array.isArray(value)) return value.length > 0;
	if (typeof value === "object") return Object.keys(value).length > 0;
	return true;
}

function toPrettyJson(value: unknown) {
	if (!hasValue(value)) return "{}";
	try {
		return JSON.stringify(value, null, 2);
	} catch {
		return "{}";
	}
}

function listToLines(value: string[] | null | undefined) {
	return (value || []).join("\n");
}

function linesToList(value: string) {
	return value
		.split(/\r?\n/)
		.map((entry) => entry.trim())
		.filter(Boolean);
}

function parseJsonObject(value: string, label: string) {
	const trimmed = value.trim();
	if (!trimmed) return {};
	let parsed: unknown;
	try {
		parsed = JSON.parse(trimmed);
	} catch {
		throw new Error(`${label} must be valid JSON.`);
	}
	if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
		throw new Error(`${label} must be a JSON object.`);
	}
	return parsed as Record<string, unknown>;
}

function parseOptionalNumber(value: string, label: string) {
	const trimmed = value.trim();
	if (!trimmed) return null;
	const parsed = Number(trimmed);
	if (!Number.isFinite(parsed)) {
		throw new Error(`${label} must be a valid number.`);
	}
	return parsed;
}

function createEmptyProvenanceRow(): DraftProvenanceFormRow {
	return {
		key: `prov-${Math.random().toString(36).slice(2, 10)}`,
		field_name: "",
		declared_value: null,
		normalized_value: null,
		source_type: "REVIEW_DRAFT",
		source_url: null,
		source_lane: "PRODUCT_INTELLIGENCE_REVIEW_DRAFT",
		evidence_kind: "TEXT",
		extraction_method: "MANUAL_REVIEW",
		confidence_score: null,
		confidence_score_text: "",
		verification_status: "PENDING_REVIEW",
		claim_risk_flag: null,
		reviewer_decision: null,
		reviewer_note: null,
	};
}

function mapDraftToForm(draft: ProductIntelligenceReviewDraft): DraftFormState {
	return {
		product_description: draft.product_description || "",
		benefits_json: listToLines(draft.benefits_json),
		usp_json: listToLines(draft.usp_json),
		usage_text: draft.usage_text || "",
		ingredients_text: draft.ingredients_text || "",
		warnings_text: draft.warnings_text || "",
		target_customer_text: draft.target_customer_text || "",
		paste_anything_summary: draft.paste_anything_summary || "",
		source_urls_json: toPrettyJson(draft.source_urls_json),
		image_evidence_json: toPrettyJson(draft.image_evidence_json),
		package_notes: draft.package_notes || "",
		size_or_volume: draft.size_or_volume || "",
		product_form_factor: draft.product_form_factor || "",
		packaging_description: draft.packaging_description || "",
		product_truth_lock: draft.product_truth_lock || "",
		allowed_claims_json: listToLines(draft.allowed_claims_json),
		blocked_claims_json: listToLines(draft.blocked_claims_json),
		buyer_persona_snapshot_json: toPrettyJson(
			draft.buyer_persona_snapshot_json,
		),
		copy_strategy_summary_json: toPrettyJson(
			draft.copy_strategy_summary_json,
		),
		confidence_score:
			draft.confidence_score === null ? "" : String(draft.confidence_score),
		reviewer_note: draft.reviewer_note || "",
		created_by: draft.created_by || "",
		reviewed_by: draft.reviewed_by || "",
	};
}

function mapDraftToProvenanceRows(
	draft: ProductIntelligenceReviewDraft,
): DraftProvenanceFormRow[] {
	if (draft.provenance_items.length === 0) return [createEmptyProvenanceRow()];
	return draft.provenance_items.map((item) => ({
		key: item.review_provenance_id,
		field_name: item.field_name,
		declared_value: item.declared_value,
		normalized_value: item.normalized_value,
		source_type: item.source_type,
		source_url: item.source_url,
		source_lane: item.source_lane,
		evidence_kind: item.evidence_kind,
		extraction_method: item.extraction_method,
		confidence_score: item.confidence_score,
		confidence_score_text:
			item.confidence_score === null ? "" : String(item.confidence_score),
		verification_status: item.verification_status,
		claim_risk_flag: item.claim_risk_flag,
		reviewer_decision: item.reviewer_decision,
		reviewer_note: item.reviewer_note,
	}));
}

function getStatusTone(status: string) {
	switch (status) {
		case "APPROVED":
		case "READY_FOR_REVIEW":
		case "READY_FOR_APPROVAL":
		case "CLAIM_SAFE":
			return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
		case "CLAIM_REVIEW_REQUIRED":
		case "NEEDS_REVISION":
			return "border-amber-500/30 bg-amber-500/10 text-amber-100";
		case "REJECTED":
		case "CLAIM_BLOCKED":
			return "border-red-500/30 bg-red-500/10 text-red-200";
		default:
			return "border-slate-700 bg-slate-900/70 text-slate-200";
	}
}

function Badge({ label }: { label: string }) {
	return (
		<span
			className={`inline-flex rounded border px-2 py-1 text-[10px] font-semibold ${getStatusTone(label)}`}
		>
			{label}
		</span>
	);
}

function SectionHeading({
	title,
	subtitle,
}: {
	title: string;
	subtitle?: string;
}) {
	return (
		<div className="space-y-1">
			<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
				{title}
			</div>
			{subtitle ? (
				<div className="text-[11px] text-slate-500">{subtitle}</div>
			) : null}
		</div>
	);
}

function TextInput({
	label,
	value,
	onChange,
	placeholder,
}: {
	label: string;
	value: string;
	onChange: (value: string) => void;
	placeholder?: string;
}) {
	return (
		<label className="block space-y-2">
			<span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
				{label}
			</span>
			<input
				value={value}
				onChange={(event) => onChange(event.target.value)}
				placeholder={placeholder}
				className="w-full rounded border border-slate-700 bg-slate-950/70 px-3 py-2 text-[12px] text-slate-100 outline-none focus:border-sky-400"
			/>
		</label>
	);
}

function TextArea({
	label,
	value,
	onChange,
	rows = 4,
	placeholder,
}: {
	label: string;
	value: string;
	onChange: (value: string) => void;
	rows?: number;
	placeholder?: string;
}) {
	return (
		<label className="block space-y-2">
			<span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
				{label}
			</span>
			<textarea
				value={value}
				onChange={(event) => onChange(event.target.value)}
				rows={rows}
				placeholder={placeholder}
				className="w-full rounded border border-slate-700 bg-slate-950/70 px-3 py-2 text-[12px] text-slate-100 outline-none focus:border-sky-400"
			/>
		</label>
	);
}

function buildMutationPayload(
	form: DraftFormState,
	provenanceRows: DraftProvenanceFormRow[],
): ProductIntelligenceReviewDraftMutationRequest {
	return {
		product_description: form.product_description.trim() || null,
		benefits_json: linesToList(form.benefits_json),
		usp_json: linesToList(form.usp_json),
		usage_text: form.usage_text.trim() || null,
		ingredients_text: form.ingredients_text.trim() || null,
		warnings_text: form.warnings_text.trim() || null,
		target_customer_text: form.target_customer_text.trim() || null,
		paste_anything_summary: form.paste_anything_summary.trim() || null,
		source_urls_json: parseJsonObject(form.source_urls_json, "Source URLs"),
		image_evidence_json: parseJsonObject(
			form.image_evidence_json,
			"Image Evidence",
		),
		package_notes: form.package_notes.trim() || null,
		size_or_volume: form.size_or_volume.trim() || null,
		product_form_factor: form.product_form_factor.trim() || null,
		packaging_description: form.packaging_description.trim() || null,
		product_truth_lock: form.product_truth_lock.trim() || null,
		allowed_claims_json: linesToList(form.allowed_claims_json),
		blocked_claims_json: linesToList(form.blocked_claims_json),
		buyer_persona_snapshot_json: parseJsonObject(
			form.buyer_persona_snapshot_json,
			"Buyer Persona Snapshot",
		),
		copy_strategy_summary_json: parseJsonObject(
			form.copy_strategy_summary_json,
			"Copy Strategy Summary",
		),
		confidence_score: parseOptionalNumber(
			form.confidence_score,
			"Confidence score",
		),
		reviewer_note: form.reviewer_note.trim() || null,
		created_by: form.created_by.trim() || null,
		reviewed_by: form.reviewed_by.trim() || null,
		provenance_items: provenanceRows
			.filter((row) => row.field_name.trim())
			.map((row) => ({
				field_name: row.field_name.trim(),
				declared_value: row.declared_value?.trim() || null,
				normalized_value: row.normalized_value?.trim() || null,
				source_type: row.source_type.trim() || "REVIEW_DRAFT",
				source_url: row.source_url?.trim() || null,
				source_lane: row.source_lane?.trim() || null,
				evidence_kind: row.evidence_kind.trim() || "TEXT",
				extraction_method: row.extraction_method.trim() || "MANUAL_REVIEW",
				confidence_score: parseOptionalNumber(
					row.confidence_score_text,
					`Provenance confidence for ${row.field_name || "row"}`,
				),
				verification_status: row.verification_status.trim() || "PENDING_REVIEW",
				claim_risk_flag: row.claim_risk_flag?.trim() || null,
				reviewer_decision: row.reviewer_decision?.trim() || null,
				reviewer_note: row.reviewer_note?.trim() || null,
			})),
	};
}

export default function ProductIntelligenceReviewDraftPanel({
	productId,
	onApproved,
}: {
	productId: string;
	onApproved: (snapshotId: string) => Promise<void> | void;
}) {
	const [drafts, setDrafts] = useState<ProductIntelligenceReviewDraft[]>([]);
	const [draftsLoading, setDraftsLoading] = useState(false);
	const [draftsError, setDraftsError] = useState<string | null>(null);
	const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null);
	const [activeDraft, setActiveDraft] =
		useState<ProductIntelligenceReviewDraft | null>(null);
	const [form, setForm] = useState<DraftFormState | null>(null);
	const [provenanceRows, setProvenanceRows] = useState<DraftProvenanceFormRow[]>(
		[],
	);
	const [validation, setValidation] =
		useState<ProductIntelligenceReviewDraftValidationResponse | null>(null);
	const [busyAction, setBusyAction] = useState<
		"CREATE" | "SAVE" | "VALIDATE" | "APPROVE" | "REJECT" | null
	>(null);
	const [message, setMessage] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);

	const missingRequiredFields = useMemo(() => {
		if (!activeDraft) return [...REQUIRED_FIELDS];
		return REQUIRED_FIELDS.filter((fieldName) => !hasValue(activeDraft[fieldName]));
	}, [activeDraft]);

	useEffect(() => {
		let cancelled = false;
		async function loadDrafts() {
			setDraftsLoading(true);
			setDraftsError(null);
			try {
				const response = await fetchProductIntelligenceReviewDrafts(productId);
				if (cancelled) return;
				setDrafts(response.items);
				const nextDraftId = response.items[0]?.draft_id || null;
				setSelectedDraftId((current) => current || nextDraftId);
			} catch (err) {
				if (cancelled) return;
				setDraftsError(
					err instanceof Error
						? err.message
						: "Failed to load product intelligence review drafts",
				);
			} finally {
				if (!cancelled) setDraftsLoading(false);
			}
		}
		void loadDrafts();
		return () => {
			cancelled = true;
		};
	}, [productId]);

	useEffect(() => {
		if (!selectedDraftId) {
			setActiveDraft(null);
			setForm(null);
			setProvenanceRows([]);
			setValidation(null);
			return;
		}
		let cancelled = false;
		const draftId = selectedDraftId;
		async function loadDraft() {
			try {
				const draft = await fetchProductIntelligenceReviewDraft(draftId);
				if (cancelled) return;
				setActiveDraft(draft);
				setForm(mapDraftToForm(draft));
				setProvenanceRows(mapDraftToProvenanceRows(draft));
				setValidation(null);
			} catch (err) {
				if (cancelled) return;
				setError(
					err instanceof Error
						? err.message
						: "Failed to load product intelligence review draft detail",
				);
			}
		}
		void loadDraft();
		return () => {
			cancelled = true;
		};
	}, [selectedDraftId]);

	const updateFormField = (field: keyof DraftFormState, value: string) => {
		setForm((current) => (current ? { ...current, [field]: value } : current));
	};

	const updateProvenanceRow = (
		key: string,
		field: keyof DraftProvenanceFormRow,
		value: string,
	) => {
		setProvenanceRows((current) =>
			current.map((row) => {
				if (row.key !== key) return row;
				if (field === "confidence_score_text") {
					return { ...row, confidence_score_text: value };
				}
				return { ...row, [field]: value || null };
			}),
		);
	};

	const syncDraftInList = (draft: ProductIntelligenceReviewDraft) => {
		setDrafts((current) => {
			const filtered = current.filter((item) => item.draft_id !== draft.draft_id);
			return [draft, ...filtered];
		});
		setSelectedDraftId(draft.draft_id);
		setActiveDraft(draft);
		setForm(mapDraftToForm(draft));
		setProvenanceRows(mapDraftToProvenanceRows(draft));
	};

	const handleCreateDraft = async () => {
		setBusyAction("CREATE");
		setError(null);
		setMessage(null);
		try {
			const draft = await createProductIntelligenceReviewDraft(productId, {
				created_by: "operator",
			});
			syncDraftInList(draft);
			setValidation(null);
			setMessage("Review draft created.");
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to create product intelligence review draft",
			);
		} finally {
			setBusyAction(null);
		}
	};

	const saveDraft = async () => {
		if (!activeDraft || !form) return null;
		const payload = buildMutationPayload(form, provenanceRows);
		const updated = await updateProductIntelligenceReviewDraft(
			activeDraft.draft_id,
			payload,
		);
		syncDraftInList(updated);
		return updated;
	};

	const handleSaveDraft = async () => {
		setBusyAction("SAVE");
		setError(null);
		setMessage(null);
		try {
			await saveDraft();
			setValidation(null);
			setMessage("Review draft saved.");
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to save product intelligence review draft",
			);
		} finally {
			setBusyAction(null);
		}
	};

	const handleValidateDraft = async () => {
		if (!activeDraft) return;
		setBusyAction("VALIDATE");
		setError(null);
		setMessage(null);
		try {
			const saved = await saveDraft();
			const report = await validateProductIntelligenceReviewDraft(
				saved?.draft_id || activeDraft.draft_id,
			);
			syncDraftInList(report.draft);
			setValidation(report);
			setMessage("Review draft validated.");
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to validate product intelligence review draft",
			);
		} finally {
			setBusyAction(null);
		}
	};

	const handleApproveDraft = async () => {
		if (!activeDraft || !form) return;
		setBusyAction("APPROVE");
		setError(null);
		setMessage(null);
		try {
			const saved = await saveDraft();
			const report = await validateProductIntelligenceReviewDraft(
				saved?.draft_id || activeDraft.draft_id,
			);
			syncDraftInList(report.draft);
			setValidation(report);
			const snapshot = await approveProductIntelligenceReviewDraft(
				report.draft.draft_id,
				{
					approved_by: form.reviewed_by.trim() || "operator",
					approval_note: form.reviewer_note.trim() || null,
				},
			);
			const refreshedDraft = await fetchProductIntelligenceReviewDraft(
				report.draft.draft_id,
			);
			syncDraftInList(refreshedDraft);
			await onApproved(snapshot.snapshot_id);
			setMessage(
				`Review draft approved. Immutable snapshot ${snapshot.version} created.`,
			);
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to approve product intelligence review draft",
			);
		} finally {
			setBusyAction(null);
		}
	};

	const handleRejectDraft = async () => {
		if (!activeDraft || !form) return;
		setBusyAction("REJECT");
		setError(null);
		setMessage(null);
		try {
			const saved = await saveDraft();
			const rejected = await rejectProductIntelligenceReviewDraft(
				saved?.draft_id || activeDraft.draft_id,
				{
					rejected_by: form.reviewed_by.trim() || "operator",
					reviewer_note: form.reviewer_note.trim() || null,
				},
			);
			syncDraftInList(rejected);
			setValidation(null);
			setMessage("Review draft rejected. No approved snapshot created.");
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to reject product intelligence review draft",
			);
		} finally {
			setBusyAction(null);
		}
	};

	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-950/40 p-4">
			<div className="mb-4 flex flex-wrap items-start justify-between gap-3">
				<div className="space-y-1">
					<h2 className="text-sm font-bold text-slate-100">
						Product Intelligence Review Draft Pipeline
					</h2>
					<p className="max-w-3xl text-[11px] text-slate-400">
						Create a human-reviewable draft, validate required fields, inspect
						claim safety, approve or reject, and create the immutable snapshot
						used by the read-only INTELLIGENCE view.
					</p>
				</div>
				<button
					type="button"
					onClick={handleCreateDraft}
					disabled={busyAction !== null}
					className="rounded border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-[11px] font-semibold text-sky-100 disabled:cursor-not-allowed disabled:opacity-60"
				>
					{busyAction === "CREATE" ? "Creating..." : "Create Review Draft"}
				</button>
			</div>

			<div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
				<div className="rounded border border-slate-800 bg-slate-900/50 p-3">
					<SectionHeading
						title="Draft Queue"
						subtitle="Review drafts remain editable until rejected or approved."
					/>
					<div className="mt-3 space-y-2">
						{draftsLoading ? (
							<div className="text-[11px] text-slate-500">
								Loading review drafts...
							</div>
						) : draftsError ? (
							<div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
								{draftsError}
							</div>
						) : drafts.length === 0 ? (
							<div className="rounded border border-slate-800 bg-slate-950/70 px-3 py-3 text-[11px] text-slate-500">
								No review draft exists for this product yet.
							</div>
						) : (
							drafts.map((draft) => (
								<button
									key={draft.draft_id}
									type="button"
									onClick={() => setSelectedDraftId(draft.draft_id)}
									className={`block w-full rounded border px-3 py-3 text-left transition ${
										selectedDraftId === draft.draft_id
											? "border-sky-400 bg-sky-500/10"
											: "border-slate-800 bg-slate-950/60 hover:border-slate-700"
									}`}
								>
									<div className="flex flex-wrap items-center justify-between gap-2">
										<div className="text-[11px] font-semibold text-slate-100">
											{draft.draft_id}
										</div>
										<Badge label={draft.review_status} />
									</div>
									<div className="mt-2 flex flex-wrap gap-2">
										<Badge label={draft.claim_gate} />
										<Badge label={draft.claim_risk_level} />
									</div>
									<div className="mt-2 text-[11px] text-slate-400">
										Readiness: {fieldValue(draft.readiness_status)}
									</div>
								</button>
							))
						)}
					</div>
				</div>

				<div className="space-y-4">
					{message ? (
						<div className="rounded border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-100">
							{message}
						</div>
					) : null}
					{error ? (
						<div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
							{error}
						</div>
					) : null}

					{!activeDraft || !form ? (
						<div className="rounded border border-slate-800 bg-slate-900/40 px-4 py-6 text-[11px] text-slate-500">
							Select a draft or create a new review draft to begin manual
							validation.
						</div>
					) : (
						<>
							<div className="rounded border border-slate-800 bg-slate-900/50 p-3">
								<div className="flex flex-wrap items-center justify-between gap-3">
									<div className="space-y-2">
										<div className="text-[11px] font-semibold text-slate-100">
											Draft Status Overview
										</div>
										<div className="flex flex-wrap gap-2">
											<Badge label={activeDraft.review_status} />
											<Badge label={activeDraft.claim_gate} />
											<Badge label={activeDraft.claim_risk_level} />
											<Badge
												label={
													activeDraft.readiness_status || "NOT_AVAILABLE"
												}
											/>
										</div>
									</div>
									<div className="flex flex-wrap gap-2">
										<button
											type="button"
											onClick={handleSaveDraft}
											disabled={busyAction !== null}
											className="rounded border border-slate-700 bg-slate-950/70 px-3 py-2 text-[11px] font-semibold text-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
										>
											{busyAction === "SAVE" ? "Saving..." : "Save Draft"}
										</button>
										<button
											type="button"
											onClick={handleValidateDraft}
											disabled={busyAction !== null}
											className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] font-semibold text-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
										>
											{busyAction === "VALIDATE" ? "Validating..." : "Validate Draft"}
										</button>
										<button
											type="button"
											onClick={handleApproveDraft}
											disabled={busyAction !== null}
											className="rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-[11px] font-semibold text-emerald-100 disabled:cursor-not-allowed disabled:opacity-60"
										>
											{busyAction === "APPROVE" ? "Approving..." : "Approve Draft"}
										</button>
										<button
											type="button"
											onClick={handleRejectDraft}
											disabled={busyAction !== null}
											className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-[11px] font-semibold text-red-100 disabled:cursor-not-allowed disabled:opacity-60"
										>
											{busyAction === "REJECT" ? "Rejecting..." : "Reject Draft"}
										</button>
									</div>
								</div>
							</div>

							<div className="grid gap-4 xl:grid-cols-2">
								<div className="rounded border border-slate-800 bg-slate-900/50 p-3">
									<SectionHeading title="Missing Required Fields" />
									<div className="mt-3 flex flex-wrap gap-2">
										{missingRequiredFields.length > 0 ? (
											missingRequiredFields.map((field) => (
												<Badge key={field} label={field} />
											))
										) : (
											<div className="text-[11px] text-emerald-200">
												All required fields are populated.
											</div>
										)}
									</div>
								</div>

								<div className="rounded border border-slate-800 bg-slate-900/50 p-3">
									<SectionHeading title="Claim Safety Gate" />
									<div className="mt-3 space-y-3 text-[11px] text-slate-300">
										<div className="flex flex-wrap gap-2">
											<Badge label={activeDraft.claim_gate} />
											<Badge label={activeDraft.claim_risk_level} />
										</div>
										<div>
											<div className="mb-1 font-semibold text-slate-400">
												Claim Tokens
											</div>
											<div className="flex flex-wrap gap-2">
												{activeDraft.claim_tokens_json.length > 0 ? (
													activeDraft.claim_tokens_json.map((token) => (
														<Badge key={token} label={token} />
													))
												) : (
													<span className="text-slate-500">No claim tokens.</span>
												)}
											</div>
										</div>
										<div>
											<div className="mb-1 font-semibold text-slate-400">
												Approval Blockers
											</div>
											<div className="space-y-1">
												{validation?.approval_blockers?.length ? (
													validation.approval_blockers.map((blocker) => (
														<div
															key={blocker}
															className="rounded border border-red-500/30 bg-red-500/10 px-2 py-1 text-red-100"
														>
															{blocker}
														</div>
													))
												) : (
													<div className="text-slate-500">
														No validation blockers stored.
													</div>
												)}
											</div>
										</div>
									</div>
								</div>
							</div>

							<div className="rounded border border-slate-800 bg-slate-900/50 p-3">
								<SectionHeading
									title="Draft Editor"
									subtitle="Minimal V1 editor for the canonical snapshot-aligned product truth fields."
								/>
								<div className="mt-4 grid gap-4 xl:grid-cols-2">
									<TextArea
										label="Product Description"
										value={form.product_description}
										onChange={(value) =>
											updateFormField("product_description", value)
										}
									/>
									<TextArea
										label="Benefits (one per line)"
										value={form.benefits_json}
										onChange={(value) => updateFormField("benefits_json", value)}
									/>
									<TextArea
										label="USP (one per line)"
										value={form.usp_json}
										onChange={(value) => updateFormField("usp_json", value)}
									/>
									<TextArea
										label="Usage Text"
										value={form.usage_text}
										onChange={(value) => updateFormField("usage_text", value)}
									/>
									<TextArea
										label="Ingredients Text"
										value={form.ingredients_text}
										onChange={(value) =>
											updateFormField("ingredients_text", value)
										}
									/>
									<TextArea
										label="Warnings Text"
										value={form.warnings_text}
										onChange={(value) => updateFormField("warnings_text", value)}
									/>
									<TextArea
										label="Target Customer Text"
										value={form.target_customer_text}
										onChange={(value) =>
											updateFormField("target_customer_text", value)
										}
									/>
									<TextArea
										label="Paste Anything Summary"
										value={form.paste_anything_summary}
										onChange={(value) =>
											updateFormField("paste_anything_summary", value)
										}
									/>
									<TextInput
										label="Size or Volume"
										value={form.size_or_volume}
										onChange={(value) => updateFormField("size_or_volume", value)}
									/>
									<TextInput
										label="Product Form Factor"
										value={form.product_form_factor}
										onChange={(value) =>
											updateFormField("product_form_factor", value)
										}
									/>
									<TextInput
										label="Packaging Description"
										value={form.packaging_description}
										onChange={(value) =>
											updateFormField("packaging_description", value)
										}
									/>
									<TextInput
										label="Product Truth Lock"
										value={form.product_truth_lock}
										onChange={(value) =>
											updateFormField("product_truth_lock", value)
										}
									/>
									<TextArea
										label="Package Notes"
										value={form.package_notes}
										onChange={(value) => updateFormField("package_notes", value)}
									/>
									<TextArea
										label="Allowed Claims (one per line)"
										value={form.allowed_claims_json}
										onChange={(value) =>
											updateFormField("allowed_claims_json", value)
										}
									/>
									<TextArea
										label="Blocked Claims (one per line)"
										value={form.blocked_claims_json}
										onChange={(value) =>
											updateFormField("blocked_claims_json", value)
										}
									/>
									<TextInput
										label="Confidence Score"
										value={form.confidence_score}
										onChange={(value) =>
											updateFormField("confidence_score", value)
										}
										placeholder="0.0 - 1.0"
									/>
									<TextInput
										label="Created By"
										value={form.created_by}
										onChange={(value) => updateFormField("created_by", value)}
									/>
									<TextInput
										label="Reviewed By"
										value={form.reviewed_by}
										onChange={(value) => updateFormField("reviewed_by", value)}
									/>
									<div className="xl:col-span-2">
										<TextArea
											label="Reviewer Note"
											value={form.reviewer_note}
											onChange={(value) => updateFormField("reviewer_note", value)}
										/>
									</div>
									<div className="xl:col-span-2">
										<TextArea
											label="Source URLs JSON"
											value={form.source_urls_json}
											onChange={(value) =>
												updateFormField("source_urls_json", value)
											}
											rows={6}
										/>
									</div>
									<div className="xl:col-span-2">
										<TextArea
											label="Image Evidence JSON"
											value={form.image_evidence_json}
											onChange={(value) =>
												updateFormField("image_evidence_json", value)
											}
											rows={6}
										/>
									</div>
									<div className="xl:col-span-2">
										<TextArea
											label="Buyer Persona Snapshot JSON"
											value={form.buyer_persona_snapshot_json}
											onChange={(value) =>
												updateFormField("buyer_persona_snapshot_json", value)
											}
											rows={8}
										/>
									</div>
									<div className="xl:col-span-2">
										<TextArea
											label="Copy Strategy Summary JSON"
											value={form.copy_strategy_summary_json}
											onChange={(value) =>
												updateFormField("copy_strategy_summary_json", value)
											}
											rows={8}
										/>
									</div>
								</div>
							</div>

							<div className="rounded border border-slate-800 bg-slate-900/50 p-3">
								<div className="mb-4 flex flex-wrap items-center justify-between gap-3">
									<SectionHeading
										title="Field Provenance Editor"
										subtitle="Evidence rows copied into product_intelligence_field_provenance on approval."
									/>
									<button
										type="button"
										onClick={() =>
											setProvenanceRows((current) => [
												...current,
												createEmptyProvenanceRow(),
											])
										}
										className="rounded border border-slate-700 bg-slate-950/70 px-3 py-2 text-[11px] font-semibold text-slate-100"
									>
										Add Evidence Row
									</button>
								</div>

								<div className="space-y-3">
									{provenanceRows.map((row) => (
										<div
											key={row.key}
											className="rounded border border-slate-800 bg-slate-950/60 p-3"
										>
											<div className="mb-3 flex flex-wrap items-center justify-between gap-2">
												<div className="text-[11px] font-semibold text-slate-100">
													Provenance Row
												</div>
												<button
													type="button"
													onClick={() =>
														setProvenanceRows((current) =>
															current.length === 1
																? [createEmptyProvenanceRow()]
																: current.filter((item) => item.key !== row.key),
														)
													}
													className="rounded border border-red-500/30 bg-red-500/10 px-2 py-1 text-[10px] font-semibold text-red-100"
												>
													Remove
												</button>
											</div>
											<div className="grid gap-3 xl:grid-cols-2">
												<TextInput
													label="Field Name"
													value={row.field_name}
													onChange={(value) =>
														updateProvenanceRow(row.key, "field_name", value)
													}
												/>
												<TextInput
													label="Source Type"
													value={row.source_type}
													onChange={(value) =>
														updateProvenanceRow(row.key, "source_type", value)
													}
												/>
												<TextInput
													label="Evidence Kind"
													value={row.evidence_kind}
													onChange={(value) =>
														updateProvenanceRow(row.key, "evidence_kind", value)
													}
												/>
												<TextInput
													label="Extraction Method"
													value={row.extraction_method}
													onChange={(value) =>
														updateProvenanceRow(
															row.key,
															"extraction_method",
															value,
														)
													}
												/>
												<TextInput
													label="Verification Status"
													value={row.verification_status}
													onChange={(value) =>
														updateProvenanceRow(
															row.key,
															"verification_status",
															value,
														)
													}
												/>
												<TextInput
													label="Confidence Score"
													value={row.confidence_score_text}
													onChange={(value) =>
														updateProvenanceRow(
															row.key,
															"confidence_score_text",
															value,
														)
													}
												/>
												<TextInput
													label="Source URL"
													value={row.source_url || ""}
													onChange={(value) =>
														updateProvenanceRow(row.key, "source_url", value)
													}
												/>
												<TextInput
													label="Source Lane"
													value={row.source_lane || ""}
													onChange={(value) =>
														updateProvenanceRow(row.key, "source_lane", value)
													}
												/>
												<TextInput
													label="Claim Risk Flag"
													value={row.claim_risk_flag || ""}
													onChange={(value) =>
														updateProvenanceRow(row.key, "claim_risk_flag", value)
													}
												/>
												<TextInput
													label="Reviewer Decision"
													value={row.reviewer_decision || ""}
													onChange={(value) =>
														updateProvenanceRow(
															row.key,
															"reviewer_decision",
															value,
														)
													}
												/>
												<div className="xl:col-span-2">
													<TextArea
														label="Declared Value"
														value={row.declared_value || ""}
														onChange={(value) =>
															updateProvenanceRow(
																row.key,
																"declared_value",
																value,
															)
														}
													/>
												</div>
												<div className="xl:col-span-2">
													<TextArea
														label="Normalized Value"
														value={row.normalized_value || ""}
														onChange={(value) =>
															updateProvenanceRow(
																row.key,
																"normalized_value",
																value,
															)
														}
													/>
												</div>
												<div className="xl:col-span-2">
													<TextArea
														label="Reviewer Note"
														value={row.reviewer_note || ""}
														onChange={(value) =>
															updateProvenanceRow(
																row.key,
																"reviewer_note",
																value,
															)
														}
													/>
												</div>
											</div>
										</div>
									))}
								</div>
							</div>
						</>
					)}
				</div>
			</div>
		</section>
	);
}
