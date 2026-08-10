import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const source = readFileSync("src/pages/AvatarRegistryPage.tsx", "utf8");

describe("AvatarRegistryPage product-first safety contract", () => {
	it("keeps avatar creation distinct from product-link failure and retry", () => {
		expect(source).toContain("AVATAR_CREATED_PRODUCT_LINK_FAILED");
		expect(source).toContain("pendingLinkAvatarCode");
		expect(source).toContain("retryPendingProductLink");
		expect(source).toContain("Retry product link");
		expect(source).toContain("patchCreativeSelectionAvatar");
	});

	it("blocks review-required linking and clears stale product context", () => {
		expect(source).toContain("PRODUCT CATEGORY REVIEW REQUIRED");
		expect(source).toContain("creativeSetup?.review_required");
		expect(source).toContain("creativeSetupRequestRef");
		expect(source).toContain("setCreativeSetup(null)");
	});

	it("keeps profile creation non-generative and exposes AgeBand controls", () => {
		expect(source).toContain("Creating a profile never starts image generation");
		expect(source).toContain("Age band");
		expect(source).toContain("autoAgeBand");
		expect(source).toContain("age_band");
	});

	it("renders backend provenance, protection, image state, and permission-gated actions", () => {
		expect(source).toContain("registry_source");
		expect(source).toContain("System Core");
		expect(source).toContain("Locked");
		expect(source).toContain("Mapped Product Cluster(s)");
		expect(source).toContain("NOT GENERATED");
		expect(source).toContain("a.delete_allowed ?");
		expect(source).toContain("SYSTEM_AVATAR_IMMUTABLE");
		expect(source).toContain("?.image_generated ? \"GENERATED\" : \"NOT GENERATED\"");
	});
});
