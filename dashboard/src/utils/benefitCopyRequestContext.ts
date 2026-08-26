import type { BenefitCopyExecutionContext } from "../components/copywriting/BenefitCopySourceSection";

/** The request-scoped copy context a video operator sends into compile + generate.
 * Carries BENEFIT_COPY_RENDER_V1 identity ONLY when the operator explicitly chose
 * Benefit On-Demand AND a finalized candidate exists. Returns `undefined` otherwise,
 * so the backend `resolve_execution_copy` uses its normal persisted Copy V2 path —
 * an operator never silently masquerades a dropped candidate as a benefit selection,
 * and a Copy V2 selection never carries a rendered candidate. */
export function benefitCopyRequestContext(
	selectedCopySource: "BENEFIT_RENDER" | "COPY_V2",
	selectedBenefitCopy: BenefitCopyExecutionContext | null,
): { lane: string; benefit_copy_render: { candidate_id: string } } | undefined {
	if (
		selectedCopySource === "BENEFIT_RENDER" &&
		selectedBenefitCopy &&
		selectedBenefitCopy.candidate_id
	) {
		return {
			lane: selectedBenefitCopy.lane,
			benefit_copy_render: { candidate_id: selectedBenefitCopy.candidate_id },
		};
	}
	return undefined;
}
