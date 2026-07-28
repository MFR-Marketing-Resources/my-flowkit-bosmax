import { useEffect, useMemo, useState } from "react";
import { patchAPI, postAPI } from "../../api/client";
import {
	fetchProductStrategyTypeRegistry,
	registerProductStrategyType,
} from "../../api/products";
import type {
	RegistrationCommitResponse,
	RegistrationReviewDraft,
	RegistrationReviewDraftEvidencePatchRequest,
	ProductStrategyTypeRegistryResponse,
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

type EvidenceGuidanceStatus =
	| "Missing"
	| "Placeholder"
	| "Weak evidence"
	| "Needs human review";

interface EvidenceFieldGuidance {
	field: keyof EvidenceEditorState;
	label: string;
	focusId: string;
	status: EvidenceGuidanceStatus;
	detail: string;
}

const EVIDENCE_FIELD_IDS = {
	product_knowledge_text: "registration-product-knowledge-evidence",
	benefits_text: "registration-benefits-evidence",
	ingredients_text: "registration-ingredients-evidence",
	warnings_text: "registration-warnings-evidence",
	size_or_volume: "registration-size-or-volume-evidence",
	package_notes: "registration-package-notes-evidence",
} as const;

const FIELD_LABELS: Record<string, string> = {
	normalized_name: "Normalized name",
	category: "Category",
	subcategory: "Subcategory",
	type: "Type",
	bosmax_product_family: "BOSMAX product family",
	claims: "Sensitive claims",
	physics_profile: "Physics profile",
};

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

function normalizeEvidenceText(value: string): string {
	return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function wordCount(value: string): number {
	return value
		.trim()
		.split(/\s+/)
		.filter(Boolean).length;
}

function isPlaceholderEvidence(value: string): boolean {
	const normalized = normalizeEvidenceText(value);
	if (!normalized) return false;
	if (
		/\b(?:placeholder|tbd|unknown|n\/a|grab now|natural beauty)\b/i.test(
			normalized,
		)
	) {
		return true;
	}
	const hashtagCount = (value.match(/#[\p{L}\p{N}_]+/gu) || []).length;
	const productionCueCount = [
		/\b\d+\s*-\s*\d+\s*s\b/i,
		/\b(?:music|muzik|audio|soundtrack)\b/i,
	].filter((pattern) => pattern.test(value)).length;
	return hashtagCount >= 2 || productionCueCount >= 2;
}

function extractVariantCandidates(sourceText: string): string[] {
	const candidates: string[] = [];
	const seen = new Set<string>();
	const addCandidate = (amount: string, unit: string) => {
		const singularUnit = unit.toLowerCase().replace(/\s+/g, " ").trim();
		const candidate = `${amount.trim()} ${singularUnit}`.trim();
		const key = normalizeEvidenceText(candidate);
		if (!seen.has(key)) {
			seen.add(key);
			candidates.push(candidate);
		}
	};
	const multiVariantPattern =
		/(\d+(?:\.\d+)?(?:\s*\/\s*\d+(?:\.\d+)?)+)\s*(softgels?|soft gels?|capsules?|kapsul|biji|ml|millilit(?:er|re)s?|g|gram|kg|kilogram)\b/gi;
	for (const match of sourceText.matchAll(multiVariantPattern)) {
		for (const amount of match[1].split("/")) {
			addCandidate(amount, match[2]);
		}
	}
	const singleVariantPattern =
		/\b(\d+(?:\.\d+)?)\s*(softgels?|soft gels?|capsules?|kapsul|biji|ml|millilit(?:er|re)s?|g|gram|kg|kilogram)\b/gi;
	for (const match of sourceText.matchAll(singleVariantPattern)) {
		addCandidate(match[1], match[2]);
	}
	return candidates;
}

function candidateMatchesCurrentValue(candidate: string, currentValue: string): boolean {
	const candidateAmount = candidate.match(/\d+(?:\.\d+)?/)?.[0];
	const currentAmount = currentValue.match(/\d+(?:\.\d+)?/)?.[0];
	if (!candidateAmount || !currentAmount || candidateAmount !== currentAmount) {
		return false;
	}
	const normalizedCurrent = normalizeEvidenceText(currentValue);
	return (
		normalizedCurrent === currentAmount ||
		normalizeEvidenceText(candidate) === normalizedCurrent
	);
}

function escapeRegExp(value: string): string {
	return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function extractExplicitEvidence(
	sourceText: string,
	labels: string[],
): string | undefined {
	for (const label of labels) {
		const pattern = new RegExp(
			`(?:^|[\\n|])\\s*${escapeRegExp(label)}\\s*[:=-]\\s*([^|\\n]+)`,
			"i",
		);
		const match = sourceText.match(pattern);
		const value = match?.[1]?.trim();
		if (value) return value;
	}
	return undefined;
}

function buildEvidenceAssessments(
	form: EvidenceEditorState,
	variantCandidates: string[],
): EvidenceFieldGuidance[] {
	const assessments: EvidenceFieldGuidance[] = [];
	const addTextAssessment = (
		field: "product_knowledge_text" | "benefits_text" | "ingredients_text" | "warnings_text",
		label: string,
		minimumWords: number,
	) => {
		const value = form[field].trim();
		if (!value) {
			assessments.push({
				field,
				label,
				focusId: EVIDENCE_FIELD_IDS[field],
				status: "Missing",
				detail: "No evidence is currently stored in this draft field.",
			});
			return;
		}
		if (isPlaceholderEvidence(value)) {
			assessments.push({
				field,
				label,
				focusId: EVIDENCE_FIELD_IDS[field],
				status: "Placeholder",
				detail:
					"This value looks like marketing or production filler, not product evidence.",
			});
			return;
		}
		if (wordCount(value) < minimumWords) {
			assessments.push({
				field,
				label,
				focusId: EVIDENCE_FIELD_IDS[field],
				status: "Weak evidence",
				detail: "Add a specific evidence-backed statement before final review.",
			});
		}
	};

	addTextAssessment("product_knowledge_text", "Product Knowledge", 8);
	addTextAssessment("benefits_text", "Benefits", 5);
	addTextAssessment("ingredients_text", "Ingredients", 2);
	addTextAssessment("warnings_text", "Warnings", 3);

	if (!form.size_or_volume.trim()) {
		assessments.push({
			field: "size_or_volume",
			label: "Size / Volume",
			focusId: EVIDENCE_FIELD_IDS.size_or_volume,
			status: "Missing",
			detail: "Select or enter the exact registered pack variant.",
		});
	} else if (
		variantCandidates.length > 1 &&
		variantCandidates.some((candidate) =>
			candidateMatchesCurrentValue(candidate, form.size_or_volume),
		)
	) {
		assessments.push({
			field: "size_or_volume",
			label: "Size / Volume",
			focusId: EVIDENCE_FIELD_IDS.size_or_volume,
			status: "Needs human review",
			detail:
				"The source title contains multiple pack variants. Confirm the exact variant and unit.",
		});
	}

	if (!form.package_notes.trim()) {
		assessments.push({
			field: "package_notes",
			label: "Package Notes",
			focusId: EVIDENCE_FIELD_IDS.package_notes,
			status: "Missing",
			detail: "Describe the verified bottle, blister, pouch, box, or other pack.",
		});
	}

	return assessments;
}

function buildReviewReasons(
	draft: RegistrationReviewDraft,
	form: EvidenceEditorState,
	approvals: Record<string, boolean>,
): string[] {
	const sourceText = [
		form.product_name,
		form.product_knowledge_text,
		form.paste_anything_about_product,
	].join("\n");
	const assessments = buildEvidenceAssessments(
		form,
		extractVariantCandidates(sourceText),
	);
	const reasons: string[] = [];
	if (draft.missing_required_evidence.length > 0) {
		reasons.push(
			`Missing required evidence: ${draft.missing_required_evidence.join(", ")}.`,
		);
	}
	if (assessments.length > 0) {
		reasons.push(
			`Weak or unresolved draft fields: ${assessments
				.map((assessment) => `${assessment.label} (${assessment.status})`)
				.join(", ")}.`,
		);
	}
	if (!approvals.normalized_name) {
		reasons.push("The normalized product name still requires explicit approval.");
	}
	const unresolvedCandidates = draft.human_review_fields.filter(
		(field) =>
			field in draft.canonical_candidate_fields && !approvals[field],
	);
	if (unresolvedCandidates.length > 0) {
		reasons.push(
			`Review and approve candidate fields: ${unresolvedCandidates
				.map((field) => FIELD_LABELS[field] || field.replace(/_/g, " "))
				.join(", ")}.`,
		);
	}
	if (
		draft.claim_gate === "CLAIM_REVIEW_REQUIRED" ||
		draft.human_review_fields.includes("claims")
	) {
		const tokenDetail =
			draft.claim_tokens.length > 0
				? ` Detected tokens: ${draft.claim_tokens.join(", ")}.`
				: "";
		reasons.push(`Sensitive claims require human verification.${tokenDetail}`);
	}
	if (draft.claim_gate === "CLAIM_BLOCKED") {
		reasons.push("Claim safety is blocked; unsafe claims must be removed or rejected.");
	}
	if (draft.blocked_fields.length > 0) {
		reasons.push(`Blocked fields: ${draft.blocked_fields.join(", ")}.`);
	}
	return reasons;
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
	id,
	label,
	value,
	onChange,
	placeholder,
	type = "text",
	guidance,
}: {
	id?: string;
	label: string;
	value: string;
	onChange: (value: string) => void;
	placeholder?: string;
	type?: "text" | "number" | "url";
	guidance?: EvidenceFieldGuidance;
}) {
	const descriptionId = id && guidance ? `${id}-guidance` : undefined;
	return (
		<div className="space-y-2">
			<div className="flex flex-wrap items-center justify-between gap-2">
				<label
					htmlFor={id}
					className="text-[10px] font-bold uppercase tracking-widest text-slate-500"
				>
					{label}
				</label>
				{guidance ? (
					<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-amber-300">
						{guidance.status}
					</span>
				) : null}
			</div>
			<input
				id={id}
				type={type}
				value={value}
				onChange={(event) => onChange(event.target.value)}
				placeholder={placeholder}
				aria-describedby={descriptionId}
				className={`w-full rounded-xl border bg-slate-950/80 px-3 py-2 text-xs text-slate-100 outline-none transition-all focus:border-indigo-500/50 ${
					guidance
						? "border-amber-500/50 ring-1 ring-amber-500/10"
						: "border-slate-700"
				}`}
			/>
			{guidance ? (
				<p id={descriptionId} className="text-[11px] leading-relaxed text-amber-200">
					{guidance.detail}
				</p>
			) : null}
		</div>
	);
}

function EvidenceTextarea({
	id,
	label,
	value,
	onChange,
	placeholder,
	rows = 4,
	guidance,
}: {
	id?: string;
	label: string;
	value: string;
	onChange: (value: string) => void;
	placeholder?: string;
	rows?: number;
	guidance?: EvidenceFieldGuidance;
}) {
	const descriptionId = id && guidance ? `${id}-guidance` : undefined;
	return (
		<div className="space-y-2">
			<div className="flex flex-wrap items-center justify-between gap-2">
				<label
					htmlFor={id}
					className="text-[10px] font-bold uppercase tracking-widest text-slate-500"
				>
					{label}
				</label>
				{guidance ? (
					<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-amber-300">
						{guidance.status}
					</span>
				) : null}
			</div>
			<textarea
				id={id}
				value={value}
				onChange={(event) => onChange(event.target.value)}
				placeholder={placeholder}
				rows={rows}
				aria-describedby={descriptionId}
				className={`w-full rounded-xl border bg-slate-950/80 px-3 py-2 text-xs text-slate-100 outline-none transition-all focus:border-indigo-500/50 ${
					guidance
						? "border-amber-500/50 ring-1 ring-amber-500/10"
						: "border-slate-700"
				}`}
			/>
			{guidance ? (
				<p id={descriptionId} className="text-[11px] leading-relaxed text-amber-200">
					{guidance.detail}
				</p>
			) : null}
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
	const [taxonomyRegistry, setTaxonomyRegistry] =
		useState<ProductStrategyTypeRegistryResponse>({
			items: [],
			clusters: [],
			scene_strategy_ids: [],
		});
	const [taxonomyCluster, setTaxonomyCluster] = useState(
		draft.strategy_taxonomy?.cluster || "",
	);
	const [taxonomyGroup, setTaxonomyGroup] = useState(
		draft.strategy_taxonomy?.product_type_group || "",
	);
	const [taxonomyReviewerId, setTaxonomyReviewerId] = useState(
		draft.strategy_taxonomy?.reviewer_id || "",
	);
	const [taxonomyReviewerNote, setTaxonomyReviewerNote] = useState(
		draft.strategy_taxonomy?.reviewer_note || "",
	);
	const [taxonomySaving, setTaxonomySaving] = useState(false);
	const [taxonomyMessage, setTaxonomyMessage] = useState("");
	const [newTaxonomyGroup, setNewTaxonomyGroup] = useState("");
	const [newTaxonomyDisplayName, setNewTaxonomyDisplayName] = useState("");
	const [newTaxonomySceneId, setNewTaxonomySceneId] =
		useState("GENERIC_FALLBACK");
	const [newTaxonomyCoverage, setNewTaxonomyCoverage] = useState<
		"COVERED" | "PARTIAL" | "FALLBACK_ONLY"
	>("FALLBACK_ONLY");
	const [newTaxonomyRegistryStatus, setNewTaxonomyRegistryStatus] = useState<
		"ACTIVE" | "REVIEW_REQUIRED"
	>("REVIEW_REQUIRED");

	useEffect(() => {
		setApprovals(draft.approval_checklist);
		setEvidenceForm(buildEvidenceEditorState(draft));
		setPendingImageBase64("");
		setPendingImageFilename("");
		setPendingImagePreview("");
		setTaxonomyCluster(draft.strategy_taxonomy?.cluster || "");
		setTaxonomyGroup(draft.strategy_taxonomy?.product_type_group || "");
		setTaxonomyReviewerId(draft.strategy_taxonomy?.reviewer_id || "");
		setTaxonomyReviewerNote(draft.strategy_taxonomy?.reviewer_note || "");
	}, [draft]);

	useEffect(() => {
		let cancelled = false;
		async function loadTaxonomyRegistry() {
			try {
				const response = await fetchProductStrategyTypeRegistry();
				if (!cancelled) setTaxonomyRegistry(response);
			} catch (err) {
				if (!cancelled) {
					setTaxonomyMessage(
						err instanceof Error
							? err.message
							: "Failed to load product strategy registry",
					);
				}
			}
		}
		void loadTaxonomyRegistry();
		return () => {
			cancelled = true;
		};
	}, []);

	const taxonomyGroupOptions = useMemo(
		() =>
			taxonomyRegistry.items.filter(
				(item) => item.cluster === taxonomyCluster,
			),
		[taxonomyCluster, taxonomyRegistry.items],
	);
	const selectedTaxonomyEntry = useMemo(
		() =>
			taxonomyGroupOptions.find(
				(item) => item.product_type_group === taxonomyGroup,
			) || null,
		[taxonomyGroup, taxonomyGroupOptions],
	);

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
	const hasSizeOrVolumeEvidenceGap = draft.missing_required_evidence.includes(
		"SIZE_OR_VOLUME_EVIDENCE",
	);
	const imageAnalysisStatus = String(
		draft.system_inferred_fields.image_analysis_status || "UNKNOWN",
	);
	const variantCandidates = useMemo(
		() =>
			extractVariantCandidates(
				[
					evidenceForm.product_name,
					evidenceForm.product_knowledge_text,
					evidenceForm.paste_anything_about_product,
				].join("\n"),
			),
		[
			evidenceForm.paste_anything_about_product,
			evidenceForm.product_knowledge_text,
			evidenceForm.product_name,
		],
	);
	const evidenceAssessments = useMemo(
		() => buildEvidenceAssessments(evidenceForm, variantCandidates),
		[evidenceForm, variantCandidates],
	);
	const guidanceByField = useMemo(
		() =>
			new Map(
				evidenceAssessments.map((assessment) => [
					assessment.field,
					assessment,
				]),
			),
		[evidenceAssessments],
	);
	const reviewReasons = useMemo(
		() => buildReviewReasons(draft, evidenceForm, approvals),
		[approvals, draft, evidenceForm],
	);
	const shouldShowNextAction =
		draft.review_status !== "COMMITTED" && reviewReasons.length > 0;
	const hasUnresolvedCandidateReview =
		!approvals.normalized_name ||
		draft.human_review_fields.some(
			(field) =>
				field in draft.canonical_candidate_fields && !approvals[field],
		);
	const hasClaimReview =
		draft.claim_gate !== "CLAIM_SAFE" ||
		draft.human_review_fields.includes("claims");

	const focusEvidenceField = (fieldId: string) => {
		const field = document.getElementById(fieldId);
		field?.focus();
		field?.scrollIntoView?.({ behavior: "smooth", block: "center" });
	};

	const handleExtractExistingEvidence = () => {
		const sourceText = evidenceForm.paste_anything_about_product.trim();
		const next = { ...evidenceForm };
		const applied: string[] = [];
		const applyTextProposal = (
			field:
				| "benefits_text"
				| "usage_text"
				| "ingredients_text"
				| "warnings_text"
				| "package_notes",
			label: string,
			value: string | undefined,
		) => {
			if (!value || next[field].trim()) return;
			next[field] = value;
			applied.push(label);
		};

		if (
			!next.product_knowledge_text.trim() &&
			wordCount(sourceText) >= 8
		) {
			next.product_knowledge_text = sourceText;
			applied.push("Product Knowledge");
		}
		applyTextProposal(
			"benefits_text",
			"Benefits",
			extractExplicitEvidence(sourceText, ["benefits", "benefit", "usp"]),
		);
		applyTextProposal(
			"usage_text",
			"Usage",
			extractExplicitEvidence(sourceText, [
				"usage",
				"cara guna",
				"how to use",
			]),
		);
		applyTextProposal(
			"ingredients_text",
			"Ingredients",
			extractExplicitEvidence(sourceText, [
				"ingredients",
				"ingredient",
				"bahan",
			]),
		);
		applyTextProposal(
			"warnings_text",
			"Warnings",
			extractExplicitEvidence(sourceText, [
				"warnings",
				"warning",
				"amaran",
				"pantang",
			]),
		);
		applyTextProposal(
			"package_notes",
			"Package Notes",
			extractExplicitEvidence(sourceText, [
				"package notes",
				"package",
				"packaging",
				"pembungkusan",
			]),
		);
		if (!next.size_or_volume.trim() && variantCandidates.length === 1) {
			next.size_or_volume = variantCandidates[0];
			applied.push("Size / Volume");
		}

		setEvidenceForm(next);
		const ambiguityNote =
			variantCandidates.length > 1
				? " Multiple pack variants were found; choose one explicitly below."
				: "";
		setSaveMessage(
			applied.length > 0
				? `Review-only proposals applied from stored evidence: ${applied.join(", ")}. No field was approved.${ambiguityNote} Save & Recompute to validate.`
				: `No additional evidence-backed values could be proposed.${ambiguityNote} Missing ingredients or warnings were not invented.`,
		);
	};

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
			const updatedReasons = buildReviewReasons(
				updated,
				buildEvidenceEditorState(updated),
				updated.approval_checklist,
			);
			setSaveMessage(
				recompute
					? updated.missing_required_evidence.length > 0
						? `Recompute validated current evidence; it will not fill missing evidence. Still missing: ${updated.missing_required_evidence.join(", ")}.`
						: updated.review_status === "NEEDS_HUMAN_REVIEW" ||
								updated.review_status === "BLOCKED"
							? `Evidence saved. Still requires human review because: ${updatedReasons.join(" ")}`
							: "Evidence saved and recomputed. The draft is ready for explicit candidate review; nothing was auto-approved."
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

	const handleTaxonomySave = async (
		reviewStatus: "VERIFIED" | "REVIEW_REQUIRED",
	) => {
		if (!draft.strategy_taxonomy || !selectedTaxonomyEntry) {
			setTaxonomyMessage("Select a registered product type first.");
			return;
		}
		if (!taxonomyReviewerId.trim() || !taxonomyReviewerNote.trim()) {
			setTaxonomyMessage("Reviewer ID and reviewer note are required.");
			return;
		}
		setTaxonomySaving(true);
		setTaxonomyMessage("");
		try {
			const updatedDraft: RegistrationReviewDraft = {
				...draft,
				strategy_taxonomy: {
					...draft.strategy_taxonomy,
					cluster: selectedTaxonomyEntry.cluster,
					product_type_group: selectedTaxonomyEntry.product_type_group,
					matched_scene_strategy_id:
						selectedTaxonomyEntry.matched_scene_strategy_id,
					scene_coverage_status: selectedTaxonomyEntry.scene_coverage_status,
					fallback_used:
						selectedTaxonomyEntry.scene_coverage_status === "FALLBACK_ONLY",
					specific_strategy:
						selectedTaxonomyEntry.scene_coverage_status === "COVERED",
					review_status: reviewStatus,
					consumer_status: "BLOCKED_REVIEW_REQUIRED",
					authority_source: "MANUAL_OVERRIDE",
					materialization_status: "PREVIEW",
					review_reasons:
						reviewStatus === "VERIFIED"
							? []
							: ["MANUAL_REVIEW_REQUIRED"],
					reviewer_id: taxonomyReviewerId.trim(),
					reviewer_note: taxonomyReviewerNote.trim(),
					reviewed_at: new Date().toISOString(),
					is_stale: false,
				},
			};
			const saved = await postAPI<RegistrationReviewDraft>(
				"/api/product-registration/review-drafts",
				updatedDraft,
			);
			onUpdate(saved);
			setTaxonomyMessage(
				`Draft taxonomy saved as ${saved.strategy_taxonomy?.review_status}. It will materialize during registration commit.`,
			);
		} catch (err) {
			setTaxonomyMessage(
				err instanceof Error ? err.message : "Failed to save draft taxonomy",
			);
		} finally {
			setTaxonomySaving(false);
		}
	};

	const handleTaxonomyTypeRegistration = async (
		event: React.FormEvent<HTMLFormElement>,
	) => {
		event.preventDefault();
		if (!taxonomyCluster) {
			setTaxonomyMessage("Select a concrete cluster first.");
			return;
		}
		if (!taxonomyReviewerId.trim() || !taxonomyReviewerNote.trim()) {
			setTaxonomyMessage("Reviewer ID and reviewer note are required.");
			return;
		}
		setTaxonomySaving(true);
		setTaxonomyMessage("");
		try {
			const created = await registerProductStrategyType({
				cluster: taxonomyCluster,
				product_type_group: newTaxonomyGroup.trim(),
				display_name: newTaxonomyDisplayName.trim(),
				matched_scene_strategy_id: newTaxonomySceneId,
				scene_coverage_status: newTaxonomyCoverage,
				registry_status: newTaxonomyRegistryStatus,
				auto_classification_enabled: false,
				reviewer_id: taxonomyReviewerId.trim(),
				reviewer_note: taxonomyReviewerNote.trim(),
			});
			setTaxonomyRegistry((current) => ({
				...current,
				items: [...current.items, created].sort((left, right) =>
					`${left.cluster}:${left.product_type_group}`.localeCompare(
						`${right.cluster}:${right.product_type_group}`,
					),
				),
			}));
			setTaxonomyGroup(created.product_type_group);
			setNewTaxonomyGroup("");
			setNewTaxonomyDisplayName("");
			setTaxonomyMessage(
				`Registered ${created.cluster} / ${created.product_type_group} as ${created.registry_status}.`,
			);
		} catch (err) {
			setTaxonomyMessage(
				err instanceof Error
					? err.message
					: "Failed to register product strategy type",
			);
		} finally {
			setTaxonomySaving(false);
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

			{draft.strategy_taxonomy ? (
				<section
					data-testid="registration-strategy-taxonomy"
					className="rounded-2xl border border-cyan-500/20 bg-slate-900/60 p-6"
				>
					<div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
						<div>
							<h4 className="text-sm font-bold uppercase tracking-wider text-white">
								Product Strategy Taxonomy
							</h4>
							<p className="mt-1 text-xs text-slate-400">
								Deterministic registration preview. Copy consumers remain
								blocked until a materialized taxonomy is verified.
							</p>
						</div>
						<span
							className={`rounded-full px-3 py-1 text-[10px] font-bold uppercase tracking-wider ${
								draft.strategy_taxonomy.review_status === "VERIFIED"
									? "bg-emerald-500/10 text-emerald-300"
									: "bg-amber-500/10 text-amber-300"
							}`}
						>
							{draft.strategy_taxonomy.review_status}
						</span>
					</div>
					<div className="mt-4 grid grid-cols-1 gap-3 text-xs md:grid-cols-2 xl:grid-cols-4">
						<div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
								Cluster
							</div>
							<div className="mt-1 text-slate-100">
								{draft.strategy_taxonomy.cluster}
							</div>
						</div>
						<div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
								Product Type Group
							</div>
							<div className="mt-1 text-slate-100">
								{draft.strategy_taxonomy.product_type_group}
							</div>
						</div>
						<div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
								Scene Strategy
							</div>
							<div className="mt-1 text-slate-100">
								{draft.strategy_taxonomy.matched_scene_strategy_id}
							</div>
						</div>
						<div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
							<div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
								Coverage / Consumer Gate
							</div>
							<div className="mt-1 text-slate-100">
								{draft.strategy_taxonomy.scene_coverage_status} /{" "}
								{draft.strategy_taxonomy.consumer_status}
							</div>
						</div>
					</div>
					{draft.strategy_taxonomy.review_reasons.length > 0 ? (
						<div className="mt-4 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
							<div className="text-[10px] font-bold uppercase tracking-wider text-amber-300">
								Review Required Because
							</div>
							<div className="mt-1 text-xs text-slate-300">
								{draft.strategy_taxonomy.review_reasons.join(", ")}
							</div>
						</div>
					) : null}
					<div
						data-testid="registration-strategy-taxonomy-editor"
						className="mt-4 space-y-4 border-t border-slate-800 pt-4"
					>
						<div className="grid gap-3 md:grid-cols-2">
							<label className="text-[11px] text-slate-400">
								Cluster
								<select
									data-testid="registration-taxonomy-cluster-select"
									value={taxonomyCluster}
									onChange={(event) => {
										const cluster = event.target.value;
										const firstGroup = taxonomyRegistry.items.find(
											(item) => item.cluster === cluster,
										);
										setTaxonomyCluster(cluster);
										setTaxonomyGroup(firstGroup?.product_type_group || "");
									}}
									className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
								>
									<option value="">Select cluster</option>
									{taxonomyRegistry.clusters
										.filter(
											(cluster) => cluster !== "generic_unclassified",
										)
										.map((cluster) => (
											<option key={cluster} value={cluster}>
												{cluster}
											</option>
										))}
								</select>
							</label>
							<label className="text-[11px] text-slate-400">
								Product Type Group
								<select
									data-testid="registration-taxonomy-group-select"
									value={taxonomyGroup}
									onChange={(event) => setTaxonomyGroup(event.target.value)}
									className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
								>
									<option value="">Select registered type</option>
									{taxonomyGroupOptions.map((item) => (
										<option
											key={item.product_type_group}
											value={item.product_type_group}
										>
											{item.display_name} · {item.registry_status}
										</option>
									))}
								</select>
							</label>
							<label className="text-[11px] text-slate-400">
								Reviewer ID
								<input
									value={taxonomyReviewerId}
									onChange={(event) =>
										setTaxonomyReviewerId(event.target.value)
									}
									className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
								/>
							</label>
							<label className="text-[11px] text-slate-400">
								Reviewer Note
								<input
									value={taxonomyReviewerNote}
									onChange={(event) =>
										setTaxonomyReviewerNote(event.target.value)
									}
									className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
								/>
							</label>
						</div>
						{selectedTaxonomyEntry ? (
							<div className="rounded border border-slate-800 bg-slate-950/60 p-3 text-[11px] text-slate-300">
								Scene: {selectedTaxonomyEntry.matched_scene_strategy_id} ·
								Coverage: {selectedTaxonomyEntry.scene_coverage_status} ·
								Registry: {selectedTaxonomyEntry.registry_status}
							</div>
						) : null}
						<div className="flex flex-wrap gap-2">
							<button
								type="button"
								disabled={taxonomySaving || !selectedTaxonomyEntry}
								onClick={() => void handleTaxonomySave("REVIEW_REQUIRED")}
								className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] font-bold text-amber-300 disabled:opacity-40"
							>
								Save Review Required
							</button>
							<button
								type="button"
								disabled={
									taxonomySaving ||
									selectedTaxonomyEntry?.registry_status !== "ACTIVE"
								}
								onClick={() => void handleTaxonomySave("VERIFIED")}
								className="rounded border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[11px] font-bold text-emerald-300 disabled:opacity-40"
							>
								Verify Draft Assignment
							</button>
						</div>
						<form
							data-testid="registration-product-strategy-type-registration"
							onSubmit={handleTaxonomyTypeRegistration}
							className="space-y-3 border-t border-slate-800 pt-4"
						>
							<div className="text-[11px] font-bold uppercase tracking-wider text-slate-300">
								Register New Type Under Selected Cluster
							</div>
							<div className="grid gap-3 md:grid-cols-2">
								<input
									aria-label="Registration product type group code"
									placeholder="product_type_group"
									value={newTaxonomyGroup}
									onChange={(event) =>
										setNewTaxonomyGroup(event.target.value)
									}
									className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
								/>
								<input
									aria-label="Registration product type display name"
									placeholder="Display name"
									value={newTaxonomyDisplayName}
									onChange={(event) =>
										setNewTaxonomyDisplayName(event.target.value)
									}
									className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
								/>
								<select
									aria-label="Registration scene strategy"
									value={newTaxonomySceneId}
									onChange={(event) => {
										const sceneId = event.target.value;
										setNewTaxonomySceneId(sceneId);
										if (sceneId === "GENERIC_FALLBACK") {
											setNewTaxonomyCoverage("FALLBACK_ONLY");
											setNewTaxonomyRegistryStatus("REVIEW_REQUIRED");
										}
									}}
									className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
								>
									{taxonomyRegistry.scene_strategy_ids.map((sceneId) => (
										<option key={sceneId} value={sceneId}>
											{sceneId}
										</option>
									))}
								</select>
								<select
									aria-label="Registration scene coverage"
									value={newTaxonomyCoverage}
									onChange={(event) =>
										setNewTaxonomyCoverage(
											event.target.value as
												| "COVERED"
												| "PARTIAL"
												| "FALLBACK_ONLY",
										)
									}
									className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
								>
									<option value="COVERED">COVERED</option>
									<option value="PARTIAL">PARTIAL</option>
									<option value="FALLBACK_ONLY">FALLBACK_ONLY</option>
								</select>
								<select
									aria-label="Registration product type registry status"
									value={newTaxonomyRegistryStatus}
									onChange={(event) =>
										setNewTaxonomyRegistryStatus(
											event.target.value as
												| "ACTIVE"
												| "REVIEW_REQUIRED",
										)
									}
									className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
								>
									<option value="REVIEW_REQUIRED">REVIEW_REQUIRED</option>
									<option value="ACTIVE">ACTIVE</option>
								</select>
								<button
									type="submit"
									disabled={
										taxonomySaving ||
										!taxonomyCluster ||
										!newTaxonomyGroup.trim() ||
										!newTaxonomyDisplayName.trim()
									}
									className="rounded border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-[11px] font-bold text-cyan-300 disabled:opacity-40"
								>
									Register Product Type
								</button>
							</div>
						</form>
						{taxonomyMessage ? (
							<div
								data-testid="registration-taxonomy-message"
								className="text-[11px] text-slate-300"
							>
								{taxonomyMessage}
							</div>
						) : null}
					</div>
				</section>
			) : null}

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

				{shouldShowNextAction ? (
					<div
						data-testid="registration-next-action"
						className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4"
					>
						<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-amber-400">
							Next Action
						</div>
						<div className="mt-2 space-y-4">
							<div>
								<div className="text-sm font-semibold text-amber-100">
									{hasSizeOrVolumeEvidenceGap
										? "Fill size or volume evidence"
										: draft.review_status === "NEEDS_HUMAN_REVIEW"
											? "Review weak evidence and gated candidates"
											: "Complete the explicit review gate"}
								</div>
								<p className="mt-1 text-xs leading-relaxed text-slate-300">
									{hasSizeOrVolumeEvidenceGap
										? "Enter the exact pack quantity or volume shown on the packaging or an authoritative product source. If the listing contains several pack variants, choose the exact variant being registered."
										: "Required evidence is present, but the draft is not approved. Resolve the highlighted quality issues, review sensitive claims, then approve the gated canonical candidates."}
								</p>
							</div>
							<div className="flex flex-wrap gap-2">
								<button
									type="button"
									onClick={handleExtractExistingEvidence}
									className="rounded-lg border border-indigo-400/40 bg-indigo-400/10 px-3 py-2 text-xs font-bold text-indigo-100 transition-colors hover:bg-indigo-400/20"
								>
									Extract from existing evidence
								</button>
								{hasSizeOrVolumeEvidenceGap ? (
									<button
										type="button"
										onClick={() =>
											focusEvidenceField(
												EVIDENCE_FIELD_IDS.size_or_volume,
											)
										}
										className="rounded-lg border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-xs font-bold text-amber-100 transition-colors hover:bg-amber-400/20"
									>
										Edit size or volume evidence
									</button>
								) : null}
								{hasUnresolvedCandidateReview ? (
									<button
										type="button"
										onClick={() =>
											focusEvidenceField(
												"registration-canonical-candidates",
											)
										}
										className="rounded-lg border border-slate-600 bg-slate-900/70 px-3 py-2 text-xs font-bold text-slate-100 transition-colors hover:border-amber-400/50"
									>
										Jump to candidate approvals
									</button>
								) : null}
								{hasClaimReview ? (
									<button
										type="button"
										onClick={() =>
											focusEvidenceField("registration-claim-safety-review")
										}
										className="rounded-lg border border-slate-600 bg-slate-900/70 px-3 py-2 text-xs font-bold text-slate-100 transition-colors hover:border-amber-400/50"
									>
										Jump to claim safety
									</button>
								) : null}
							</div>
							<p className="text-xs leading-relaxed text-slate-400">
								Extraction is deterministic and credit-free. It only copies
								values that are already present in this draft&apos;s title or
								pasted evidence. It never approves a field and never invents
								ingredients, warnings, or claims.
							</p>
							{variantCandidates.length > 1 ? (
								<div
									data-testid="registration-variant-candidates"
									className="rounded-lg border border-amber-500/20 bg-slate-950/40 p-3"
								>
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-amber-300">
										Ambiguous pack variants found
									</div>
									<p className="mt-1 text-xs text-slate-400">
										Choose the exact registered variant. The current draft value
										is marked but still requires explicit review.
									</p>
									<div className="mt-3 flex flex-wrap gap-2">
										{variantCandidates.map((candidate) => {
											const isCurrent = candidateMatchesCurrentValue(
												candidate,
												evidenceForm.size_or_volume,
											);
											return (
												<button
													key={candidate}
													type="button"
													aria-pressed={isCurrent}
													onClick={() => {
														setEvidenceForm((current) => ({
															...current,
															size_or_volume: candidate,
														}));
														setSaveMessage(
															`Review-only size proposal selected: ${candidate}. Save & Recompute to validate; no approval was changed.`,
														);
														focusEvidenceField(
															EVIDENCE_FIELD_IDS.size_or_volume,
														);
													}}
													className={`rounded-lg border px-3 py-2 text-xs font-bold transition-colors ${
														isCurrent
															? "border-emerald-400/50 bg-emerald-400/10 text-emerald-200"
															: "border-slate-700 bg-slate-900 text-slate-200 hover:border-amber-400/50"
													}`}
												>
													Use {candidate}
													{isCurrent ? " · Current draft value" : ""}
												</button>
											);
										})}
									</div>
								</div>
							) : null}
							<div>
								<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-amber-400">
									Why review is still required
								</div>
								<ul className="mt-2 space-y-1 text-xs leading-relaxed text-slate-300">
									{reviewReasons.map((reason) => (
										<li key={reason}>• {reason}</li>
									))}
								</ul>
							</div>
							{evidenceAssessments.length > 0 ? (
								<div className="grid grid-cols-1 gap-2 md:grid-cols-2">
									{evidenceAssessments.map((assessment) => (
										<div
											key={assessment.field}
											className="flex items-center justify-between gap-3 rounded-lg border border-amber-500/20 bg-slate-950/40 p-3"
										>
											<div className="min-w-0">
												<div className="text-xs font-semibold text-slate-100">
													{assessment.label}
												</div>
												<div className="text-[10px] font-bold uppercase tracking-wider text-amber-300">
													{assessment.status}
												</div>
											</div>
											<button
												type="button"
												onClick={() =>
													focusEvidenceField(assessment.focusId)
												}
												className="shrink-0 rounded-lg border border-slate-700 px-2 py-1 text-[10px] font-bold text-slate-200 hover:border-amber-400/50"
											>
												Jump to {assessment.label}
											</button>
										</div>
									))}
								</div>
							) : null}
							<p className="text-xs leading-relaxed text-slate-400">
								Recompute validates current evidence; it will not fill missing
								evidence. It will not approve review fields. Product Intelligence
								AI Fill remains a separate review-only provider action; this
								draft extractor does not consume AI tokens.
							</p>
							{imageAnalysisStatus === "ANALYSIS_SKIPPED" ? (
								<p className="text-xs leading-relaxed text-sky-200">
									An image reference is attached, but semantic vision analysis
									was skipped because provider execution is disabled. Verify
									visual facts from the packaging or source before saving.
								</p>
							) : null}
							{draft.missing_required_evidence.length > 0 ? (
								<div>
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
							id={EVIDENCE_FIELD_IDS.product_knowledge_text}
							label="Product Knowledge Text"
							value={evidenceForm.product_knowledge_text}
							onChange={(value) =>
								setEvidenceForm((current) => ({
									...current,
									product_knowledge_text: value,
								}))
							}
							placeholder="Core product description, source facts, and owned narrative."
							guidance={guidanceByField.get("product_knowledge_text")}
						/>
						<EvidenceTextarea
							id={EVIDENCE_FIELD_IDS.benefits_text}
							label="Benefits Text"
							value={evidenceForm.benefits_text}
							onChange={(value) =>
								setEvidenceForm((current) => ({
									...current,
									benefits_text: value,
								}))
							}
							placeholder="Benefits and USP from the seller or product owner."
							guidance={guidanceByField.get("benefits_text")}
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
							id={EVIDENCE_FIELD_IDS.ingredients_text}
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
							guidance={guidanceByField.get("ingredients_text")}
						/>
						<EvidenceTextarea
							id={EVIDENCE_FIELD_IDS.warnings_text}
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
							guidance={guidanceByField.get("warnings_text")}
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
								id={EVIDENCE_FIELD_IDS.size_or_volume}
								label="Size / Volume"
								value={evidenceForm.size_or_volume}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										size_or_volume: value,
									}))
								}
								placeholder="5 ML"
								guidance={guidanceByField.get("size_or_volume")}
							/>
							<EvidenceInput
								id={EVIDENCE_FIELD_IDS.package_notes}
								label="Package Notes"
								value={evidenceForm.package_notes}
								onChange={(value) =>
									setEvidenceForm((current) => ({
										...current,
										package_notes: value,
									}))
								}
								placeholder="Dropper bottle, trial size, etc."
								guidance={guidanceByField.get("package_notes")}
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
								<div className="grid grid-cols-1 gap-3">
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

					<section
						id="registration-canonical-candidates"
						tabIndex={-1}
						className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6"
					>
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
						id="registration-claim-safety-review"
						tabIndex={-1}
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
