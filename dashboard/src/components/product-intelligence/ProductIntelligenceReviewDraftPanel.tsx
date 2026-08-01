import { useEffect, useMemo, useState } from "react";

import {
	aiFillMissingProductIntelligenceReviewDraft,
	approveClaimSafeRewrite,
	approveProductIntelligenceReviewDraft,
	createProductIntelligenceReviewDraft,
	fetchClaimSafeRewritePreview,
	fetchProductIntelligenceReviewDraft,
	fetchProductIntelligenceReviewDrafts,
	prepareProductForCopywriting,
	recomputeProductIntelligence,
	rejectProductIntelligenceReviewDraft,
	updateProductIntelligenceReviewDraft,
	validateProductIntelligenceReviewDraft,
	type ClaimSafeRewritePreview,
	type ProductIntelligenceAIFillResult,
	type ProductIntelligenceRecomputeResult,
	type TikTokRelayBlocker,
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
	persona_audience: string;
	persona_desires: string;
	persona_fears: string;
	persona_pains: string;
	persona_objections: string;
	persona_triggers: string;
	persona_tone: string;
	persona_pronoun: string;
	strategy_angles: string;
	strategy_summary: string;
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

// ── Structured Customer-Avatar / Copy-Strategy helpers ───────────────────────
// The buyer_persona_snapshot_json / copy_strategy_summary_json columns stay the
// authoritative shape read by the backend copy-grounding resolver. These helpers
// let the operator author them as friendly fields (audience / desires / fears /
// pains / objections / triggers / tone / pronoun; angles) instead of raw JSON,
// parsing the stored object in and re-assembling the SAME object out.
function jsonToLines(value: unknown): string {
	if (Array.isArray(value)) {
		return value
			.map((entry) => String(entry ?? "").trim())
			.filter(Boolean)
			.join("\n");
	}
	if (typeof value === "string") return value.trim();
	return "";
}

function jsonToText(value: unknown): string {
	if (typeof value === "string") return value;
	return value === null || value === undefined ? "" : String(value);
}

function asObject(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

function personaToForm(value: unknown) {
	const p = asObject(value);
	return {
		persona_audience: jsonToText(p.audience ?? p.persona ?? p.avatar_summary),
		persona_desires: jsonToLines(p.desires),
		persona_fears: jsonToLines(p.fears),
		persona_pains: jsonToLines(p.pains ?? p.pain_points),
		persona_objections: jsonToLines(p.objections),
		persona_triggers: jsonToLines(p.triggers),
		persona_tone: jsonToText(p.tone),
		persona_pronoun: jsonToText(p.pronoun),
	};
}

function formToPersona(form: DraftFormState): Record<string, unknown> {
	const obj: Record<string, unknown> = {};
	const putText = (key: string, value: string) => {
		if (value.trim()) obj[key] = value.trim();
	};
	const putList = (key: string, value: string) => {
		const list = linesToList(value);
		if (list.length) obj[key] = list;
	};
	putText("audience", form.persona_audience);
	putList("desires", form.persona_desires);
	putList("fears", form.persona_fears);
	putList("pains", form.persona_pains);
	putList("objections", form.persona_objections);
	putList("triggers", form.persona_triggers);
	putText("tone", form.persona_tone);
	putText("pronoun", form.persona_pronoun);
	return obj;
}

function strategyToForm(value: unknown) {
	const s = asObject(value);
	const angles = Array.isArray(s.angles)
		? s.angles
		: typeof s.angle === "string" && s.angle.trim()
			? [s.angle]
			: [];
	return {
		strategy_angles: jsonToLines(angles),
		strategy_summary: jsonToText(s.summary ?? s.strategy),
	};
}

function formToStrategy(form: DraftFormState): Record<string, unknown> {
	const obj: Record<string, unknown> = {};
	const angles = linesToList(form.strategy_angles);
	if (angles.length) obj.angles = angles;
	if (form.strategy_summary.trim()) obj.summary = form.strategy_summary.trim();
	return obj;
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
		...personaToForm(draft.buyer_persona_snapshot_json),
		...strategyToForm(draft.copy_strategy_summary_json),
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
		buyer_persona_snapshot_json: formToPersona(form),
		copy_strategy_summary_json: formToStrategy(form),
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

// The API client throws `API <status>: <body>`. Turn a fail-closed approve/validate
// error into a human, actionable message instead of dumping raw JSON at the operator.
// The backend detail is a colon-delimited string, e.g.
// "DRAFT_NOT_APPROVABLE:MISSING_REQUIRED_FIELDS:source_urls_json:CLAIM_BLOCKED:rawat,penyakit".
export function formatReviewDraftError(err: unknown, fallback: string): string {
	if (!(err instanceof Error)) return fallback;
	const raw = err.message || fallback;
	const brace = raw.indexOf("{");
	let detail: unknown = raw;
	if (brace >= 0) {
		try {
			const parsed = JSON.parse(raw.slice(brace)) as { detail?: unknown };
			if (parsed.detail !== undefined) detail = parsed.detail;
		} catch {
			/* keep raw */
		}
	}
	const text = typeof detail === "string" ? detail : JSON.stringify(detail);
	if (/DRAFT_NOT_APPROVABLE/i.test(text)) {
		// Contract: DRAFT_NOT_APPROVABLE:<blocker>|<blocker>... where each blocker is
		// KEY:comma,tokens and KEY ∈ MISSING_REQUIRED_FIELDS/CLAIM_BLOCKED/CLAIM_REVIEW_REQUIRED.
		const body = text.replace(/^[\s\S]*?DRAFT_NOT_APPROVABLE:/i, "");
		const parts: string[] = [];
		for (const blocker of body.split("|")) {
			const idx = blocker.indexOf(":");
			const key = idx >= 0 ? blocker.slice(0, idx) : blocker;
			const val = idx >= 0 ? blocker.slice(idx + 1) : "";
			if (/MISSING_REQUIRED_FIELDS/i.test(key)) {
				parts.push(`lengkapkan medan wajib yang tiada (${val})`);
			} else if (/CLAIM_BLOCKED/i.test(key)) {
				parts.push(`buang / lembutkan perkataan claim ubatan yang disekat (${val})`);
			} else if (/CLAIM_REVIEW_REQUIRED/i.test(key)) {
				parts.push(`semak semula perkataan claim yang berisiko (${val})`);
			}
		}
		const how = parts.length ? parts.join("; ") : "selesaikan semua blocker di bawah";
		return `Draf belum boleh diluluskan — ${how}. Kemas kini medan → Save Draft → Validate Draft → Approve semula. Rujuk panel "Missing Required Fields" & "Claim Safety Gate" di bawah.`;
	}
	return raw;
}

/**
 * Recognise a Recompute that stopped on the authenticated-browser relay.
 *
 * The API returns a STRUCTURED detail for these (`{code, reason, product_url,
 * operator_actionable}`) precisely so the UI does not have to sniff substrings out of an
 * error string to tell "open your TikTok tab" apart from "the backend broke".
 */
export function parseRelayBlocker(err: unknown): TikTokRelayBlocker | null {
	if (!(err instanceof Error)) return null;
	const raw = err.message || "";
	const brace = raw.indexOf("{");
	if (brace < 0) return null;
	try {
		const parsed = JSON.parse(raw.slice(brace)) as { detail?: unknown };
		const detail = parsed.detail;
		if (!detail || typeof detail !== "object") return null;
		const record = detail as Record<string, unknown>;
		const code = String(record.code ?? "");
		if (!code.startsWith("TIKTOK_RELAY_")) return null;
		return {
			code,
			reason: String(record.reason ?? ""),
			product_url: String(record.product_url ?? ""),
			operator_actionable: record.operator_actionable === true,
		};
	} catch {
		return null;
	}
}

/**
 * The operator-facing meaning of each relay code.
 *
 * Every branch ends in the same four physical steps because that IS the fix for all of
 * them; what differs is WHY the lane stopped, and hiding that would leave someone pressing
 * Retry against a disconnected extension forever. The backend code is always rendered
 * alongside this text, never instead of it.
 */
export function describeRelayBlocker(blocker: TikTokRelayBlocker): {
	headline: string;
	steps: string[];
	retryable: boolean;
} {
	const steps = [
		"Open the stored TikTok product link.",
		"Complete TikTok Security Check manually if shown.",
		"Keep the product tab open.",
		"Press Retry.",
	];
	switch (blocker.code) {
		case "TIKTOK_RELAY_SECURITY_CHECK_PRESENT":
			return {
				headline:
					"TikTok is still showing its Security Check. Clear it yourself in the tab — this system will never solve it for you.",
				steps,
				retryable: true,
			};
		case "TIKTOK_RELAY_NO_MATCHING_TAB":
			return {
				headline:
					"No open Chrome tab is showing this product. The listing can only be read from a tab you are already signed in to.",
				steps,
				retryable: true,
			};
		case "TIKTOK_RELAY_EXTENSION_DISCONNECTED":
			return {
				headline:
					"The BOSMAX Chrome extension is not connected to the local agent, so no tab can be read.",
				steps: [
					"Confirm Chrome is running with the BOSMAX extension enabled.",
					...steps,
				],
				retryable: true,
			};
		case "TIKTOK_RELAY_CONTENT_SCRIPT_UNREACHABLE":
			return {
				headline:
					"The product tab is open but not reachable yet — it was most likely loaded before the extension was last reloaded.",
				steps: ["Reload the TikTok product tab.", ...steps],
				retryable: true,
			};
		case "TIKTOK_RELAY_TAB_NAVIGATED_AWAY":
			return {
				headline:
					"The tab moved to a different product while the evidence was being read. Nothing was stored.",
				steps,
				retryable: true,
			};
		case "TIKTOK_RELAY_TIMEOUT":
			return {
				headline:
					"The product tab did not answer in time. Nothing was stored.",
				steps,
				retryable: true,
			};
		case "TIKTOK_RELAY_EMPTY_EVIDENCE":
			return {
				headline:
					"The tab was read but the page stated no product title or description. Nothing was stored — an empty read never overwrites saved evidence.",
				steps: ["Scroll the product page until the listing is fully rendered.", ...steps],
				retryable: true,
			};
		case "TIKTOK_RELAY_URL_MISMATCH":
			return {
				headline:
					"The tab identified itself as a DIFFERENT product, so its evidence was refused. This is the guard that stops one listing's data landing on another product.",
				steps,
				retryable: true,
			};
		case "TIKTOK_RELAY_HOST_NOT_SUPPORTED":
			return {
				headline:
					"This product's stored link is not on shop.tiktok.com or shop-my.tiktok.com, so the authenticated reader cannot open it. Retrying will not help.",
				steps: ["Correct the product's stored TikTok link, then Recompute again."],
				retryable: false,
			};
		default:
			return {
				headline:
					"The authenticated read did not complete. Nothing was stored.",
				steps,
				retryable: blocker.operator_actionable,
			};
	}
}

// Build a friendly "action needed" notice from the STRUCTURED validate report, so we
// never even attempt an approve that will fail closed (no raw 409 reaches the operator).
// Returns null when the draft is actually approvable.
export function describeApprovalBlockers(
	report: ProductIntelligenceReviewDraftValidationResponse,
): string | null {
	const missing = report.missing_required_fields ?? [];
	const claimBlocked =
		report.claim_gate === "CLAIM_BLOCKED" ? (report.claim_tokens_json ?? []) : [];
	const otherBlockers = report.approval_blockers ?? [];
	if (!missing.length && !claimBlocked.length && !otherBlockers.length) return null;
	const parts: string[] = [];
	if (missing.length)
		parts.push(
			`lengkapkan ${missing.length} medan wajib yang tiada (${missing.join(", ")})`,
		);
	if (claimBlocked.length)
		parts.push(
			`buang atau lembutkan perkataan claim ubatan yang disekat (${claimBlocked.join(", ")})`,
		);
	const how = parts.length
		? parts.join("; ")
		: "selesaikan blocker yang tersenarai di bawah";
	return `Draf belum boleh diluluskan — ${how}. Kemas kini medan di editor, tekan Save Draft, kemudian Validate & Approve semula. Panel "Missing Required Fields" dan "Claim Safety Gate" di bawah menyenaraikan butirannya.`;
}

export default function ProductIntelligenceReviewDraftPanel({
	productId,
	onApproved,
	guidedClaimSafe = false,
	onClaimSafeApproved,
}: {
	productId: string;
	onApproved: (snapshotId: string) => Promise<void> | void;
	guidedClaimSafe?: boolean;
	onClaimSafeApproved?: (status: string) => Promise<void> | void;
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
		| "CREATE" | "PREPARE" | "AI_FILL" | "SAVE" | "VALIDATE" | "APPROVE" | "REJECT"
		| "RECOMPUTE_SOURCE" | null
	>(null);
	const [aiFillResult, setAiFillResult] = useState<ProductIntelligenceAIFillResult | null>(null);
	const [recomputeResult, setRecomputeResult] =
		useState<ProductIntelligenceRecomputeResult | null>(null);
	// A Recompute halted at the authenticated-browser relay. Kept separate from `error`
	// because it is not a fault — it is a step the operator has to take in Chrome, and it
	// is the only state that offers a Retry.
	const [relayBlocker, setRelayBlocker] = useState<TikTokRelayBlocker | null>(null);
	const [message, setMessage] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	// Amber "action needed" notice for a draft that fails the fail-closed approval
	// gate (missing required fields / blocked claims) — distinct from a red system error.
	const [blockerNotice, setBlockerNotice] = useState<string | null>(null);
	const [claimSafePreview, setClaimSafePreview] =
		useState<ClaimSafeRewritePreview | null>(null);
	const [claimSafeLoading, setClaimSafeLoading] = useState(false);
	const [claimSafeApproving, setClaimSafeApproving] = useState(false);
	const [claimSafeError, setClaimSafeError] = useState<string | null>(null);
	const [claimSafeApprovalPhrase, setClaimSafeApprovalPhrase] = useState("");
	const [claimSafeApprovalNote, setClaimSafeApprovalNote] = useState("");

	const missingRequiredFields = useMemo(() => {
		if (!activeDraft) return [...REQUIRED_FIELDS];
		return REQUIRED_FIELDS.filter((fieldName) => !hasValue(activeDraft[fieldName]));
	}, [activeDraft]);

	useEffect(() => {
		if (!guidedClaimSafe) {
			setClaimSafePreview(null);
			setClaimSafeError(null);
			setClaimSafeApprovalPhrase("");
			setClaimSafeApprovalNote("");
			return;
		}
		let cancelled = false;
		setClaimSafeLoading(true);
		setClaimSafeError(null);
		void fetchClaimSafeRewritePreview(productId)
			.then((preview) => {
				if (!cancelled) setClaimSafePreview(preview);
			})
			.catch((err) => {
				if (cancelled) return;
				setClaimSafeError(
					err instanceof Error
						? err.message
						: "Failed to load claim-safe package preview",
				);
			})
			.finally(() => {
				if (!cancelled) setClaimSafeLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [guidedClaimSafe, productId]);

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
		// Switching drafts clears stale notices from the previous draft.
		setBlockerNotice(null);
		setError(null);
		setMessage(null);
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
		setBlockerNotice(null);
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

	const handlePrepareWithAI = async () => {
		setBusyAction("PREPARE");
		setError(null);
		setMessage(null);
		setBlockerNotice(null);
		try {
			const result = await prepareProductForCopywriting(productId);
			syncDraftInList(result.draft);
			setSelectedDraftId(result.draft.draft_id);
			setValidation(null);
			setMessage(
				`AI drafted Product Knowledge + Customer Avatar (recommended formula: ${result.recommended_formula}). Review every field, then Validate and Approve — nothing is auto-approved. Tekan Validate Draft untuk lihat baki blocker (medan wajib / claim).`,
			);
		} catch (err) {
			setError(
				formatReviewDraftError(err, "Failed to prepare product for copywriting"),
			);
		} finally {
			setBusyAction(null);
		}
	};

	/**
	 * Analyze & Repair for an EXISTING product: re-read its own stored listing.
	 *
	 * This does NOT go through the link-import route — that one creates a product, so
	 * refreshing a catalogue item through it would mint a duplicate row every press.
	 */
	const handleRecomputeFromSource = async () => {
		setBusyAction("RECOMPUTE_SOURCE");
		setError(null);
		setMessage(null);
		setBlockerNotice(null);
		setRecomputeResult(null);
		setRelayBlocker(null);
		try {
			const result = await recomputeProductIntelligence(productId);
			setRecomputeResult(result);
			// Re-read from the DATABASE so what is shown is what was actually stored,
			// never the optimistic shape of the response we just received.
			const refreshedList = await fetchProductIntelligenceReviewDrafts(productId);
			setDrafts(refreshedList.items);
			if (result.draft_id) {
				const refreshed = await fetchProductIntelligenceReviewDraft(result.draft_id);
				syncDraftInList(refreshed);
				setSelectedDraftId(result.draft_id);
			}
			setValidation(null);
			const extracted = Object.keys(result.extracted_fields ?? {}).length;
			const proposed = result.candidates_persisted?.length ?? 0;
			const via =
				result.acquisition_mode === "AUTHENTICATED_BROWSER_RELAY"
					? "your authenticated TikTok tab"
					: result.source_url;
			setMessage(
				`Acquired ${extracted} field(s) from ${via} (${(result.evidence_methods ?? []).join("+") || "DOM"}). ` +
					`${proposed} AI candidate(s) stored as review-required. Nothing was approved.`,
			);
		} catch (err) {
			// A relay halt is an operator step, not a system failure — it gets its own
			// actionable panel with a Retry rather than a red error the operator can only read.
			const blocker = parseRelayBlocker(err);
			if (blocker) setRelayBlocker(blocker);
			else setError(formatReviewDraftError(err, "Recompute from source failed"));
		} finally {
			setBusyAction(null);
		}
	};

	const handleAiFillMissing = async () => {
		if (!activeDraft) return;
		setBusyAction("AI_FILL");
		setError(null);
		setMessage(null);
		setBlockerNotice(null);
		setAiFillResult(null);
		try {
			const result = await aiFillMissingProductIntelligenceReviewDraft(
				activeDraft.draft_id,
			);
			setAiFillResult(result);
			// Refresh the draft so the proposed values + recalculated status show.
			const refreshed = await fetchProductIntelligenceReviewDraft(activeDraft.draft_id);
			syncDraftInList(refreshed);
			setValidation(null);
			const filledCount = result.proposed.length;
			setMessage(
				filledCount > 0
					? `AI proposed ${filledCount} field(s) as review-only draft suggestions (provider: ${result.provider ?? "?"}). Review every proposal, then Validate and Approve — nothing is auto-approved.`
					: "AI Fill Missing found no empty fields to propose (or insufficient evidence). Nothing was changed.",
			);
		} catch (err) {
			setError(
				formatReviewDraftError(err, "AI Fill Missing failed"),
			);
		} finally {
			setBusyAction(null);
		}
	};

	const handleApproveClaimSafePackage = async () => {
		if (!claimSafePreview) return;
		setClaimSafeApproving(true);
		setClaimSafeError(null);
		try {
			const approved = await approveClaimSafeRewrite(productId, {
				confirmation_phrase: claimSafeApprovalPhrase,
				approval_note: claimSafeApprovalNote.trim() || null,
			});
			setClaimSafePreview(approved);
			setClaimSafeApprovalPhrase("");
			setMessage(
				"Claim-safe package approved for workspace review. No production claim or review draft was auto-approved.",
			);
			await onClaimSafeApproved?.(approved.claim_safe_copy_status);
		} catch (err) {
			setClaimSafeError(
				formatReviewDraftError(err, "Failed to approve claim-safe package"),
			);
		} finally {
			setClaimSafeApproving(false);
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
		setBlockerNotice(null);
		try {
			await saveDraft();
			setValidation(null);
			setMessage("Review draft saved.");
		} catch (err) {
			setError(
				formatReviewDraftError(
					err,
					"Failed to save product intelligence review draft",
				),
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
		setBlockerNotice(null);
		try {
			const saved = await saveDraft();
			const report = await validateProductIntelligenceReviewDraft(
				saved?.draft_id || activeDraft.draft_id,
			);
			syncDraftInList(report.draft);
			setValidation(report);
			const blockerMsg = describeApprovalBlockers(report);
			setBlockerNotice(blockerMsg);
			setMessage(
				blockerMsg
					? null
					: "Draf disemak — semua medan wajib lengkap dan claim gate selamat. Sedia untuk Approve.",
			);
		} catch (err) {
			setError(
				formatReviewDraftError(
					err,
					"Failed to validate product intelligence review draft",
				),
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
		setBlockerNotice(null);
		try {
			const saved = await saveDraft();
			const report = await validateProductIntelligenceReviewDraft(
				saved?.draft_id || activeDraft.draft_id,
			);
			syncDraftInList(report.draft);
			setValidation(report);
			// Fail closed BEFORE the approve call: if the draft is not approvable,
			// surface a clear, actionable notice instead of a raw 409 dump.
			const blockerMsg = describeApprovalBlockers(report);
			if (blockerMsg) {
				setBlockerNotice(blockerMsg);
				return;
			}
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
				formatReviewDraftError(
					err,
					"Failed to approve product intelligence review draft",
				),
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
		setBlockerNotice(null);
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
				formatReviewDraftError(
					err,
					"Failed to reject product intelligence review draft",
				),
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
				<button
					type="button"
					onClick={handlePrepareWithAI}
					disabled={busyAction !== null}
					title="Draft Product Knowledge + Customer Avatar + a recommended formula via the text_assist (DeepSeek) lane. Spends AI tokens on click. Never auto-approved."
					className="rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-[11px] font-semibold text-emerald-100 disabled:cursor-not-allowed disabled:opacity-60"
				>
					{busyAction === "PREPARE"
						? "Preparing with AI…"
						: "Prepare with AI (DeepSeek)"}
				</button>
			</div>

			{guidedClaimSafe ? (
				<div
					data-testid="guided-claim-safe-panel"
					className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4"
				>
					<div className="flex flex-wrap items-start justify-between gap-3">
						<div>
							<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-amber-300">
								Fix Claim-Safe Package
							</div>
							<p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-slate-300">
								This guided path came from a blocked production workspace. Review
								missing Product Intelligence fields, then explicitly approve the
								deterministic claim-safe preview. Prepare with AI and AI Fill Missing
								run only when you click them and may spend configured text-assist
								tokens; neither action approves anything.
							</p>
						</div>
						<span className="rounded-full border border-amber-500/30 bg-slate-950/70 px-3 py-1 text-[10px] font-semibold text-amber-100">
							{claimSafePreview?.stored_status ||
								claimSafePreview?.claim_safe_copy_status ||
								"LOADING"}
						</span>
					</div>

					<div className="mt-3 rounded border border-slate-800 bg-slate-950/70 p-3">
						<div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
							Missing required review fields
						</div>
						<div
							data-testid="guided-claim-safe-missing-fields"
							className="mt-2 text-[11px] text-slate-200"
						>
							{activeDraft
								? missingRequiredFields.length > 0
									? missingRequiredFields.join(", ")
									: "None — the selected review draft is complete."
								: "No selected review draft. Create one or use Prepare with AI explicitly."}
						</div>
					</div>

					{claimSafeLoading ? (
						<div className="mt-3 text-[11px] text-slate-400">
							Loading deterministic claim-safe preview…
						</div>
					) : claimSafeError ? (
						<div
							data-testid="guided-claim-safe-error"
							className="mt-3 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200"
						>
							{claimSafeError}
						</div>
					) : claimSafePreview ? (
						<div className="mt-3 space-y-3">
							<div className="grid gap-3 lg:grid-cols-2">
								<div className="rounded border border-slate-800 bg-slate-950/70 p-3">
									<div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
										Safe rewrite preview
									</div>
									<p className="mt-2 text-[11px] leading-relaxed text-slate-200">
										{claimSafePreview.safe_claim_rewrite}
									</p>
								</div>
								<div className="rounded border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
									<div>
										<span className="text-slate-500">Decision:</span>{" "}
										{claimSafePreview.review_decision}
									</div>
									<div className="mt-1">
										<span className="text-slate-500">Claim gate:</span>{" "}
										{claimSafePreview.claim_gate}
									</div>
									<div className="mt-1">
										<span className="text-slate-500">Provenance:</span>{" "}
										{claimSafePreview.provenance.join(" · ")}
									</div>
								</div>
							</div>

							{claimSafePreview.approval_after_operator_review ? (
								<div className="rounded border border-emerald-500/30 bg-emerald-500/5 p-3">
									<label
										htmlFor="claim-safe-approval-phrase"
										className="block text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-200"
									>
										Type the approval phrase exactly
									</label>
									<code className="mt-2 block text-[11px] text-emerald-100">
										{claimSafePreview.approval_phrase}
									</code>
									<input
										id="claim-safe-approval-phrase"
										data-testid="claim-safe-approval-phrase"
										type="text"
										value={claimSafeApprovalPhrase}
										onChange={(event) =>
											setClaimSafeApprovalPhrase(event.target.value)
										}
										className="mt-2 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-[11px] text-slate-100"
									/>
									<label
										htmlFor="claim-safe-approval-note"
										className="mt-3 block text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
									>
										Approval note (optional)
									</label>
									<input
										id="claim-safe-approval-note"
										type="text"
										value={claimSafeApprovalNote}
										onChange={(event) =>
											setClaimSafeApprovalNote(event.target.value)
										}
										className="mt-2 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-[11px] text-slate-100"
									/>
									<button
										type="button"
										data-testid="approve-claim-safe-package"
										onClick={handleApproveClaimSafePackage}
										disabled={
											claimSafeApproving ||
											claimSafeApprovalPhrase !==
												claimSafePreview.approval_phrase
										}
										className="mt-3 rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-[11px] font-semibold text-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
									>
										{claimSafeApproving
											? "Approving claim-safe package…"
											: "Approve Claim-Safe Package"}
									</button>
								</div>
							) : (
								<div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
									Fail closed: this preview requires a separate claim-safety
									review and cannot be approved from this guided path.
								</div>
							)}
						</div>
					) : null}
				</div>
			) : null}

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
					{blockerNotice ? (
						<div
							data-testid="approval-blocker-notice"
							className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100"
						>
							{blockerNotice}
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
											{busyAction === "VALIDATE" ? "Recompute (deterministic)" : "Recompute (Validate)"}
										</button>
										<button
											type="button"
											data-testid="recompute-from-source-button"
											onClick={handleRecomputeFromSource}
											disabled={busyAction !== null}
											className="rounded border border-indigo-500/40 bg-indigo-500/10 px-3 py-2 text-[11px] font-semibold text-indigo-100 disabled:cursor-not-allowed disabled:opacity-60"
										>
											{busyAction === "RECOMPUTE_SOURCE"
												? "Acquiring source evidence..."
												: "Analyze & Repair from source"}
										</button>
										<button
											type="button"
											data-testid="ai-fill-missing-button"
											onClick={handleAiFillMissing}
											disabled={busyAction !== null}
											className="rounded border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-[11px] font-semibold text-sky-100 disabled:cursor-not-allowed disabled:opacity-60"
										>
											{busyAction === "AI_FILL" ? "AI filling..." : "AI Fill Missing (DeepSeek)"}
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
									<p className="text-[10px] leading-relaxed text-slate-500">
										<span className="font-semibold text-amber-200">Recompute</span> rebuilds
										candidates and readiness from current saved evidence — deterministic,
										no AI, generates no missing product information.{" "}
										<span className="font-semibold text-sky-200">AI Fill Missing</span>{" "}
										uses DeepSeek + approved evidence to propose values for empty Product
										Truth fields only; existing human evidence is never overwritten and
										nothing is auto-approved.
									</p>
									{relayBlocker && (
										<div
											data-testid="recompute-relay-blocker"
											className="mt-3 rounded border border-amber-500/40 bg-amber-500/10 p-3 text-[11px] text-amber-100"
										>
											<p className="font-semibold">
												Authenticated TikTok tab required — nothing was saved.
											</p>
											<p className="mt-1">{describeRelayBlocker(relayBlocker).headline}</p>
											<ol className="mt-2 list-decimal space-y-0.5 pl-4">
												{describeRelayBlocker(relayBlocker).steps.map((step) => (
													<li key={step}>{step}</li>
												))}
											</ol>
											{relayBlocker.product_url && (
												<p className="mt-2 break-all">
													<a
														data-testid="relay-product-link"
														href={relayBlocker.product_url}
														target="_blank"
														rel="noreferrer noopener"
														className="underline decoration-dotted"
													>
														{relayBlocker.product_url}
													</a>
												</p>
											)}
											{/* The raw backend code stays on screen: an operator reporting a
											    problem must be able to quote what actually failed. */}
											<p
												data-testid="relay-blocker-code"
												className="mt-2 font-mono text-[10px] text-amber-200/80"
											>
												{relayBlocker.code}
												{relayBlocker.reason ? ` · ${relayBlocker.reason}` : ""}
											</p>
											{describeRelayBlocker(relayBlocker).retryable && (
												<button
													type="button"
													data-testid="relay-retry-button"
													onClick={handleRecomputeFromSource}
													disabled={busyAction !== null}
													className="mt-2 rounded border border-amber-400/50 bg-amber-400/10 px-3 py-1.5 text-[11px] font-semibold text-amber-50 disabled:cursor-not-allowed disabled:opacity-60"
												>
													{busyAction === "RECOMPUTE_SOURCE" ? "Retrying..." : "Retry"}
												</button>
											)}
										</div>
									)}
									{recomputeResult && (
										<div
											data-testid="recompute-source-result"
											className="mt-3 rounded border border-indigo-500/30 bg-indigo-500/5 p-3 text-[11px] text-indigo-100"
										>
											<p className="font-semibold">
												Source evidence acquired ·{" "}
												{(recomputeResult.evidence_methods ?? []).join("+") || "DOM"}
											</p>
											{/* How the page was reached is reviewable evidence in its own right:
											    an anonymous fetch and a read of the operator's signed-in tab are
											    different provenance and must not look identical. */}
											<p
												data-testid="recompute-acquisition-mode"
												className="mt-1 font-mono text-[10px] text-indigo-200/70"
											>
												{recomputeResult.acquisition_mode ?? "DIRECT_FETCH"}
												{(recomputeResult.relay?.dropped_keys ?? []).length > 0
													? ` · dropped by allowlist: ${recomputeResult.relay?.dropped_keys.join(", ")}`
													: ""}
											</p>
											<p className="mt-1 break-all text-indigo-200/80">
												{recomputeResult.source_url}
											</p>
											<p className="mt-1 text-indigo-200/80">
												Variant: {recomputeResult.variant ?? "—"} (
												{recomputeResult.variant_resolution ?? "—"}) · Size:{" "}
												{recomputeResult.size_resolution ?? "—"}
											</p>
											{Object.keys(recomputeResult.extracted_fields ?? {}).length > 0 && (
												<ul className="mt-2 list-disc pl-4">
													{Object.entries(recomputeResult.extracted_fields).map(
														([field, value]) => (
															<li key={`extracted-${field}`}>
																<span className="font-semibold">{field}</span>{" "}
																<span className="text-indigo-200/70">(from page)</span>:{" "}
																{String(value).slice(0, 160)}
															</li>
														),
													)}
												</ul>
											)}
											{(recomputeResult.candidates_persisted ?? []).length > 0 && (
												<div className="mt-2" data-testid="recompute-ai-candidates">
													<p className="font-semibold">
														AI candidates stored as review-required — approve or reject each
														below. Nothing is auto-approved.
													</p>
													<ul className="list-disc pl-4">
														{recomputeResult.candidates_persisted.map((item) => (
															<li key={`cand-${item.field}`}>
																<span className="font-semibold">{item.field}</span>{" "}
																<span className="text-indigo-200/70">(AI_PROPOSED)</span>
															</li>
														))}
													</ul>
												</div>
											)}
											{Object.keys(recomputeResult.unresolved ?? {}).length > 0 && (
												<div className="mt-2" data-testid="recompute-unresolved">
													<p className="font-semibold text-amber-200">
														Unresolved — the page does not state these. Nothing was invented.
													</p>
													<ul className="list-disc pl-4 text-amber-100/90">
														{Object.entries(recomputeResult.unresolved).map(
															([field, reason]) => (
																<li key={`unresolved-${field}`}>
																	{field}: {reason}
																</li>
															),
														)}
													</ul>
												</div>
											)}
											{(recomputeResult.candidates_skipped ?? []).length > 0 && (
												<p className="mt-2 text-indigo-200/70">
													Preserved existing evidence for:{" "}
													{recomputeResult.candidates_skipped
														.map((item) => item.field)
														.join(", ")}
												</p>
											)}
											{(recomputeResult.refused_model_fields ?? []).length > 0 && (
												<p className="mt-2 text-amber-200">
													Refused model output for{" "}
													{recomputeResult.refused_model_fields.join(", ")} — these are read
													from the page or left absent, never generated.
												</p>
											)}
										</div>
									)}
									{aiFillResult && (
										<div
											data-testid="ai-fill-result"
											className="rounded border border-sky-500/30 bg-sky-500/5 p-3 text-[11px] text-slate-200"
										>
											<div className="mb-2 font-semibold text-sky-100">
												AI Fill Missing — review-only proposals ({aiFillResult.provider ?? "?"}
												{aiFillResult.model ? ` · ${aiFillResult.model}` : ""}) · status{" "}
												{aiFillResult.review_status}
											</div>
											{aiFillResult.proposed.length > 0 ? (
												<ul className="space-y-1">
													{aiFillResult.proposed.map((p) => (
														<li key={p.field}>
															<span className="font-semibold text-slate-100">{p.field}</span>
															<span className="ml-1 rounded bg-slate-800 px-1 text-[9px] uppercase text-slate-300">
																{p.status}
															</span>
															{typeof p.confidence === "number" && (
																<span className="ml-1 text-slate-400">
																	conf {p.confidence}
																</span>
															)}
															{p.rationale && (
																<span className="ml-1 text-slate-400">— {p.rationale}</span>
															)}
														</li>
													))}
												</ul>
											) : (
												<p className="text-slate-400">No fields proposed.</p>
											)}
											{aiFillResult.unresolved.length > 0 && (
												<p className="mt-2 text-slate-400">
													Left unresolved (insufficient evidence):{" "}
													{aiFillResult.unresolved.map((u) => u.field).join(", ")}
												</p>
											)}
											<p className="mt-2 text-[10px] text-slate-500">
												Proposals are stored as draft suggestions with field-level provenance.
												Approve through the existing gate — no Product Truth is auto-approved.
											</p>
										</div>
									)}
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
									<div className="xl:col-span-2 space-y-3 rounded border border-slate-800 bg-slate-950/40 p-3">
										<SectionHeading
											title="Customer Avatar (buyer persona)"
											subtitle="Who buys this and why — this drives the angle. One item per line for the lists."
										/>
										<TextInput
											label="Audience (who is the buyer)"
											value={form.persona_audience}
											onChange={(value) => updateFormField("persona_audience", value)}
											placeholder="e.g. Lelaki 30-50, sibuk, mahu rutin ringkas & yakin"
										/>
										<div className="grid gap-3 md:grid-cols-2">
											<TextArea
												label="Desires (one per line)"
												value={form.persona_desires}
												onChange={(value) => updateFormField("persona_desires", value)}
											/>
											<TextArea
												label="Fears (one per line)"
												value={form.persona_fears}
												onChange={(value) => updateFormField("persona_fears", value)}
											/>
											<TextArea
												label="Pains (one per line)"
												value={form.persona_pains}
												onChange={(value) => updateFormField("persona_pains", value)}
											/>
											<TextArea
												label="Objections (one per line)"
												value={form.persona_objections}
												onChange={(value) => updateFormField("persona_objections", value)}
											/>
										</div>
										<TextArea
											label="Triggers (one per line)"
											value={form.persona_triggers}
											rows={3}
											onChange={(value) => updateFormField("persona_triggers", value)}
										/>
										<div className="grid gap-3 md:grid-cols-2">
											<TextInput
												label="Tone"
												value={form.persona_tone}
												onChange={(value) => updateFormField("persona_tone", value)}
												placeholder="e.g. confident, warm, no-nonsense"
											/>
											<TextInput
												label="Pronoun"
												value={form.persona_pronoun}
												onChange={(value) => updateFormField("persona_pronoun", value)}
												placeholder="e.g. awak / anda"
											/>
										</div>
									</div>
									<div className="xl:col-span-2 space-y-3 rounded border border-slate-800 bg-slate-950/40 p-3">
										<SectionHeading
											title="Copy Strategy"
											subtitle="Safe angle seeds for copy rotation. One angle per line."
										/>
										<TextArea
											label="Angle strategies (one per line)"
											value={form.strategy_angles}
											onChange={(value) => updateFormField("strategy_angles", value)}
										/>
										<TextArea
											label="Strategy summary (optional)"
											value={form.strategy_summary}
											rows={3}
											onChange={(value) => updateFormField("strategy_summary", value)}
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
