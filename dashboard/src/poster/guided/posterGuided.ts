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
	{ id: "product", title: "Produk", heading: "Pilih produk" },
	{ id: "goal", title: "Tujuan", heading: "Apa tujuan poster ini?" },
	{ id: "angle", title: "Sudut", heading: "Pilih sudut jualan" },
	{ id: "copy", title: "Teks", heading: "Pilih arah teks poster" },
	{ id: "approve", title: "Sahkan", heading: "Semak & sahkan teks poster" },
	{ id: "visual", title: "Visual", heading: "Pilih gaya visual" },
	{ id: "scene", title: "Latar", heading: "Latar / aset produk" },
	{ id: "compose", title: "Hasilkan", heading: "Hasilkan poster" },
	{ id: "save", title: "Simpan", heading: "Simpan & guna semula" },
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
		description: "Serlahkan produk sebagai bintang utama poster.",
		accent: "emerald",
	},
	{
		archetype: "PRODUCT_SCALE",
		title: "Mudah Dibawa",
		description: "Tekankan saiz padat dan mudah dibawa ke mana-mana.",
		accent: "sky",
	},
	{
		archetype: "ROUTINE_USE",
		title: "Rutin Penggunaan",
		description: "Tunjukkan produk sebagai sebahagian rutin pilihan anda.",
		accent: "violet",
	},
	{
		archetype: "HERITAGE_TRUST",
		title: "Warisan & Kepercayaan",
		description: "Bina kepercayaan melalui warisan dan keaslian.",
		accent: "amber",
	},
	{
		archetype: "OFFER",
		title: "Promosi Tanpa Harga",
		description: "Promosi menarik tanpa menyebut harga atau diskaun.",
		accent: "rose",
		nonPrice: true,
	},
	{
		archetype: "PROBLEM_AWARE_SAFE",
		title: "Problem-Aware Safe",
		description: "Sasarkan masalah pelanggan dengan mesej yang selamat.",
		accent: "teal",
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

export function readinessBanner(status: string | null | undefined): ReadinessBanner {
	switch (status) {
		case "POSTER_READY":
			return {
				tone: "ready",
				title: "Sedia",
				message: "Produk ini sudah bersedia untuk menghasilkan poster.",
				canProceed: true,
			};
		case "POSTER_READY_RESTRICTED":
		case "POSTER_PREVIEW_ONLY":
			return {
				tone: "review",
				title: "Semakan disyorkan",
				message:
					"Semakan manusia disyorkan untuk identiti, label atau skala produk sebelum diterbitkan.",
				canProceed: true,
			};
		case "POSTER_BLOCKED":
			return {
				tone: "blocked",
				title: "Disekat",
				message:
					"Poster tidak boleh dijana sehingga isu produk berikut diselesaikan.",
				canProceed: false,
			};
		case null:
		case undefined:
		case "":
			return {
				tone: "info",
				title: "Menyemak",
				message: "Menyemak kesediaan produk…",
				canProceed: false,
			};
		default:
			return {
				tone: "info",
				title: "Lengkapkan maklumat",
				message: "Lengkapkan maklumat produk sebelum meneruskan.",
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

export function bucketQaFindings(qa: {
	ok?: boolean;
	findings?: { severity: string; message: string }[];
} | null | undefined): QaBuckets {
	const findings = qa?.findings ?? [];
	return {
		mustFix: findings.filter((f) => f.severity === "BLOCK").map((f) => f.message),
		review: findings.filter((f) => f.severity === "WARN").map((f) => f.message),
		passed: !!qa?.ok && findings.length === 0,
	};
}

// Human-readable label for the product-truth composition status.
export function truthLabel(status: string | null | undefined): string {
	if (!status) return "";
	if (status.startsWith("REFERENCE_CONDITIONED"))
		return "Latar dijana serupa produk — identiti/label perlu semakan manusia.";
	if (status.includes("DETERMINISTIC_COMPOSITE_VERIFIED"))
		return "Produk sebenar disisipkan (disahkan).";
	if (status.includes("DETERMINISTIC_COMPOSITE"))
		return "Produk sebenar disisipkan — belum disahkan.";
	return status.replace(/_/g, " ");
}
