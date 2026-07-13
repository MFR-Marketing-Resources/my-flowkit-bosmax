import { describe, expect, it } from "vitest";
import {
	type AvatarComposerVocab,
	composeAvatarPersonaId,
	composeAvatarPersonaPreview,
} from "./OperatorPage";

// Mirrors agent/authority/PERSONA_VARIANTS.yaml shapes (contract fixture).
const VOCAB: AvatarComposerVocab = {
	id_prefix: "AVX",
	genders: [
		{ id: "F", label_ms: "Wanita", descriptor_en: "woman" },
		{ id: "F_HIJAB", label_ms: "Wanita (bertudung)", descriptor_en: "woman" },
		{ id: "M", label_ms: "Lelaki", descriptor_en: "man" },
	],
	ethnicities: [{ id: "MELAYU", label: "Melayu", descriptor_en: "Malay" }],
	age_ranges: [{ id: "30S", label: "30-an", descriptor_en: "adult in their 30s" }],
	bundles: [
		{
			id: "KENDURI",
			label: "Kenduri",
			environment_en: "a festive Malaysian event hall",
			wardrobe_f_en: "an elegant modern baju kurung",
			wardrobe_f_hijab_en: "an elegant modern baju kurung with a matching hijab",
			wardrobe_m_en: "a modern baju melayu with sampin",
			expression_en: "warm, polite expression",
			allowed_genders: ["F", "F_HIJAB", "M"],
		},
		{
			id: "LADIES_ONLY",
			label: "Vanity",
			environment_en: "an elegant vanity corner",
			wardrobe_f_en: "soft casual wear",
			wardrobe_f_hijab_en: "soft casual wear with a hijab",
			wardrobe_m_en: "",
			expression_en: "calm expression",
			allowed_genders: ["F", "F_HIJAB"],
		},
	],
	seeds: [],
	visual_template_en:
		"Malaysian {ethnicity} {gender}, {age}, wearing {wardrobe}, in {environment}, {expression}.",
};

describe("composeAvatarPersonaId (must mirror compose_persona_id server-side)", () => {
	it("builds the AVX id uppercase", () => {
		expect(composeAvatarPersonaId("f_hijab", "melayu", "30s", "kenduri")).toBe(
			"AVX_F_HIJAB_MELAYU_30S_KENDURI",
		);
	});

	it("returns null while incomplete", () => {
		expect(composeAvatarPersonaId("F", "", "30S", "KENDURI")).toBeNull();
	});
});

describe("composeAvatarPersonaPreview (coherence + wardrobe-per-gender)", () => {
	it("female hijab wardrobe carries the hijab, environment stays paired", () => {
		const preview = composeAvatarPersonaPreview(
			VOCAB, "F_HIJAB", "MELAYU", "30S", "KENDURI",
		);
		expect(preview).toContain("baju kurung with a matching hijab");
		expect(preview).toContain("festive Malaysian event hall");
	});

	it("male wardrobe swaps to baju melayu in the same bundle", () => {
		const preview = composeAvatarPersonaPreview(VOCAB, "M", "MELAYU", "30S", "KENDURI");
		expect(preview).toContain("baju melayu with sampin");
		expect(preview).not.toContain("baju kurung");
	});

	it("gender not allowed by the bundle returns null (no incoherent combos)", () => {
		expect(
			composeAvatarPersonaPreview(VOCAB, "M", "MELAYU", "30S", "LADIES_ONLY"),
		).toBeNull();
	});

	it("unknown vocab ids return null", () => {
		expect(composeAvatarPersonaPreview(VOCAB, "F", "XX", "30S", "KENDURI")).toBeNull();
	});
});
