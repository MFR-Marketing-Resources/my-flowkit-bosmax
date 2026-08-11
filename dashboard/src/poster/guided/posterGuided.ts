// Guided Poster Builder — friendly, poster-native presentation layer over the
// existing POSTER_BUILDER_V2 backend. No new backend, no new domain: this only
// reorganises the operator experience into a clean guided journey and hides
// engineering terminology (recipes, Hook/Subhook/USP, readiness matrices, raw
// IDs) behind Advanced Diagnostics.

export type GuidedStepId =
	| "product"
	| "goal"
	| "angle"
	| "copy"
	| "approve"
	| "visual"
	| "scene"
	| "compose"
	| "save";

export interface GuidedStepMeta {
	id: GuidedStepId;
	title: string; // short label for the stepper
	heading: string; // full heading shown on the step
}

// Ordered guided journey. Titles are user-facing Malay; no engineering jargon.
export const GUIDED_STEPS: GuidedStepMeta[] = [
	{ id: "product", title: "Product", heading: "Choose a product" },
	{ id: "goal", title: "Objective", heading: "What is this poster for?" },
	{ id: "angle", title: "Angle", heading: "Choose a selling angle" },
	{ id: "copy", title: "Copy", heading: "Choose the poster copy direction" },
	{ id: "approve", title: "Approve", heading: "Review and approve the poster copy" },
	{ id: "visual", title: "Visual", heading: "Choose a visual style" },
	{ id: "scene", title: "Background", heading: "Background / product asset" },
	{ id: "compose", title: "Generate", heading: "Generate the poster" },
	{ id: "save", title: "Save", heading: "Save and reuse" },
];

export function stepIndex(id: GuidedStepId): number {
	return GUIDED_STEPS.findIndex((s) => s.id === id);
}

// Friendly goal cards. `archetype` is the internal code the backend expects; the
// user only ever sees the friendly title / description / accent. `nonPrice`
// flags the OFFER goal so the UI can reassure "no price mentioned".
export interface GuidedGoal {
	archetype: string;
	title: string;
	description: string;
	accent: string; // tailwind ring/border accent class stem
	nonPrice?: boolean;
}

export const GUIDED_GOALS: GuidedGoal[] = [
	{
		archetype: "PRODUCT_HERO",
		title: "Product Hero",
		description: "Make the product the hero of the poster.",
		accent: "emerald",
	},
	{
		// Backend/recipe archetype code — "PRODUCT_SCALE" was a mismatch that
		// silently broke recommendations + recipe filtering for this goal.
		archetype: "PORTABILITY",
		title: "Easy to Carry",
		description: "Emphasize the compact size and easy portability.",
		accent: "sky",
	},
	{
		archetype: "ROUTINE_USE",
		title: "Usage Routine",
		description: "Show the product as part of your chosen routine.",
		accent: "violet",
	},
	{
		archetype: "HERITAGE_TRUST",
		title: "Heritage and Trust",
		description: "Build trust through heritage and authenticity.",
		accent: "amber",
	},
	{
		archetype: "OFFER",
		title: "Promosi Tanpa Harga",
		description: "An appealing promo without mentioning price or discounts.",
		accent: "rose",
		nonPrice: true,
	},
	{
		archetype: "PROBLEM_AWARE_SAFE",
		title: "Problem-Aware Safe",
		description: "Target the customer's problem with safe messaging.",
		accent: "teal",
	},
	{
		// Archetype code must equal the wrna_ads_poster_916 recipe's archetype
		// exactly (see PORTABILITY mismatch note above).
		archetype: "ADS_PREMIUM",
		title: "Ads Premium (WRNA)",
		description:
			"Poster iklan premium high-converting: tajuk persuasif, hierarki jelas, CTA kuat.",
		accent: "fuchsia",
	},
];

export function goalForArchetype(archetype: string): GuidedGoal {
	return (
		GUIDED_GOALS.find((g) => g.archetype === archetype) ?? {
			archetype,
			title: archetype.replace(/_/g, " "),
			description: "",
			accent: "slate",
		}
	);
}

// Friendly readiness banner — one concise state instead of technical cards.
export type ReadinessBannerTone = "ready" | "info" | "review" | "blocked";

export interface ReadinessBanner {
	tone: ReadinessBannerTone;
	title: string;
	message: string;
	canProceed: boolean;
}

export function readinessBanner(
	status: string | null | undefined,
): ReadinessBanner {
	switch (status) {
		case "POSTER_READY":
			return {
				tone: "ready",
				title: "Ready",
				message: "This product is ready to generate a poster.",
				canProceed: true,
			};
		case "POSTER_READY_RESTRICTED":
		case "POSTER_PREVIEW_ONLY":
			return {
				tone: "review",
				title: "Review recommended",
				message:
					"Human review is recommended for product identity, label or scale before publishing.",
				canProceed: true,
			};
		case "POSTER_BLOCKED":
			return {
				tone: "blocked",
				title: "Blocked",
				message:
					"The poster cannot be generated until the following product issues are resolved.",
				canProceed: false,
			};
		case null:
		case undefined:
		case "":
			return {
				tone: "info",
				title: "Checking",
				message: "Checking product readiness…",
				canProceed: false,
			};
		default:
			return {
				tone: "info",
				title: "Complete the details",
				message: "Complete the product details before continuing.",
				canProceed: false,
			};
	}
}

// Human-readable QA buckets (Must Fix / Review Recommended / Passed).
export interface QaBuckets {
	mustFix: string[];
	review: string[];
	passed: boolean;
}

export function bucketQaFindings(
	qa:
		| {
				ok?: boolean;
				findings?: { severity: string; message: string }[];
		  }
		| null
		| undefined,
): QaBuckets {
	const findings = qa?.findings ?? [];
	return {
		mustFix: findings
			.filter((f) => f.severity === "BLOCK")
			.map((f) => f.message),
		review: findings.filter((f) => f.severity === "WARN").map((f) => f.message),
		passed: !!qa?.ok && findings.length === 0,
	};
}

// ── Product-truth-aware goal gating ─────────────────────────────────────────
// A goal that CLAIMS something (portability, heritage) must have product
// evidence behind it. Token heuristics mirror the backend's deterministic
// objective ranking signals — the UI must not imply every goal fits every
// product. Goals without evidence stay selectable ONLY behind an explicit
// operator confirmation.

const SIZE_EVIDENCE_TOKENS = [
	"5ml",
	"10ml",
	"15ml",
	"25ml",
	"roll-on",
	"roll on",
	"mini",
	"pocket",
	"travel",
	"poket",
	"kecil",
	"kompak",
];
const HERITAGE_EVIDENCE_TOKENS = [
	"warisan",
	"tradisi",
	"traditional",
	"herba",
	"herbal",
	"turun-temurun",
	"heritage",
	"asli",
];

export interface GoalEvidence {
	supported: boolean;
	// Short user-facing reason when NOT supported ("requires product evidence").
	requirement: string;
}

export function goalEvidence(
	archetype: string,
	product: {
		product_display_name?: string | null;
		raw_product_title?: string | null;
		category?: string | null;
		type_of_product?: string | null;
	} | null,
): GoalEvidence {
	const blob = [
		product?.product_display_name,
		product?.raw_product_title,
		product?.category,
		product?.type_of_product,
	]
		.map((s) => (s ?? "").toLowerCase())
		.join(" ");
	if (archetype === "PORTABILITY") {
		const supported = SIZE_EVIDENCE_TOKENS.some((t) => blob.includes(t));
		return {
			supported,
			requirement: supported
				? ""
				: "Product evidence required: no compact/portable size signal on this product record.",
		};
	}
	if (archetype === "HERITAGE_TRUST") {
		const supported = HERITAGE_EVIDENCE_TOKENS.some((t) => blob.includes(t));
		return {
			supported,
			requirement: supported
				? ""
				: "Product evidence required: no heritage/traditional signal on this product record.",
		};
	}
	// PRODUCT_HERO / ROUTINE_USE / OFFER(non-price) / PROBLEM_AWARE_SAFE are
	// neutral framings that do not assert a product fact.
	return { supported: true, requirement: "" };
}

// Human-readable label for the product-truth composition status.
export function truthLabel(status: string | null | undefined): string {
	if (!status) return "";
	if (status.startsWith("REFERENCE_CONDITIONED"))
		return "Background generated to resemble the product — identity/label needs human review.";
	if (status.includes("DETERMINISTIC_COMPOSITE_VERIFIED"))
		return "Real product inserted (verified).";
	if (status.includes("DETERMINISTIC_COMPOSITE"))
		return "Real product inserted — not yet verified.";
	return status.replace(/_/g, " ");
}
