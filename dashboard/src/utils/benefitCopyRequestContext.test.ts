import { describe, expect, it } from "vitest";
import { benefitCopyRequestContext } from "./benefitCopyRequestContext";
import type { BenefitCopyExecutionContext } from "../components/copywriting/BenefitCopySourceSection";

const CTX: BenefitCopyExecutionContext = {
	authority_kind: "BENEFIT_COPY_RENDER_V1",
	lane: "HYBRID",
	session_id: "CRS_x",
	candidate_id: "CRC_selected",
	duration_seconds: 8,
};

describe("benefitCopyRequestContext (request-scoped copy identity for compile+generate)", () => {
	// C/D/F: an explicit Benefit On-Demand selection carries the candidate so the
	// backend resolves BENEFIT_COPY_RENDER_V1 (not the persisted product-global V2).
	it("carries the selected candidate when Benefit On-Demand is chosen", () => {
		expect(benefitCopyRequestContext("BENEFIT_RENDER", CTX)).toEqual({
			lane: "HYBRID",
			benefit_copy_render: { candidate_id: "CRC_selected" },
		});
	});

	// J: switching Copy Source back to Copy V2 must NOT smuggle a rendered candidate —
	// the backend then resolves the normal persisted Copy V2 binding.
	it("returns undefined for Copy V2 even if a benefit candidate is still in state", () => {
		expect(benefitCopyRequestContext("COPY_V2", CTX)).toBeUndefined();
	});

	// I: a dropped/absent candidate must fail to a normal path — never masquerade as a
	// selected Benefit Copy. This is the exact bug that produced COPY_V2_DURATION_BINDING_MISMATCH.
	it("returns undefined when Benefit On-Demand is chosen but no candidate is finalized", () => {
		expect(benefitCopyRequestContext("BENEFIT_RENDER", null)).toBeUndefined();
	});

	// H: compile and generate call the SAME pure builder → identical authority, no flip.
	it("is deterministic so preview and generate resolve the same authority", () => {
		expect(benefitCopyRequestContext("BENEFIT_RENDER", CTX)).toEqual(
			benefitCopyRequestContext("BENEFIT_RENDER", CTX),
		);
	});

	it("uses the candidate's own lane (FACELESS stays FACELESS)", () => {
		const faceless = { ...CTX, lane: "FACELESS" as const };
		expect(benefitCopyRequestContext("BENEFIT_RENDER", faceless)?.lane).toBe("FACELESS");
	});
});
