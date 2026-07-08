import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import CopywritingReadinessCard from "./CopywritingReadinessCard";
import type { CopywritingReadiness } from "../../api/copywritingReadiness";

const base: CopywritingReadiness = {
	product_id: "p1",
	product_intelligence_status: "NO_APPROVED_SNAPSHOT",
	has_approved_snapshot: false,
	product_knowledge_ready: false,
	customer_avatar_ready: false,
	recommended_formula: "PAS",
	selected_copy_set_id: null,
	approved_copy_set_count: 0,
	formula_validation_status: "NONE",
	sales_clarity_status: "NONE",
	copy_applicable: true,
	ready_for_generation: false,
	blocking_reasons: ["NO_APPROVED_PRODUCT_INTELLIGENCE_SNAPSHOT"],
	recommended_next_action: "PREPARE_PRODUCT_FOR_COPYWRITING",
};

describe("CopywritingReadinessCard", () => {
	afterEach(() => cleanup());

	it("[UI smoke] not ready → NOT READY + Prepare CTA", () => {
		const onPrepare = vi.fn();
		render(<CopywritingReadinessCard readiness={base} onPrepare={onPrepare} />);
		expect(screen.getByTestId("readiness-badge")).toHaveTextContent("NOT READY");
		const cta = screen.getByTestId("readiness-prepare-cta");
		expect(cta).toBeInTheDocument();
		cta.click();
		expect(onPrepare).toHaveBeenCalled();
	});

	it("[UI smoke] ready → READY, no CTA", () => {
		render(
			<CopywritingReadinessCard
				readiness={{
					...base,
					has_approved_snapshot: true,
					product_knowledge_ready: true,
					customer_avatar_ready: true,
					approved_copy_set_count: 1,
					ready_for_generation: true,
					blocking_reasons: [],
					recommended_next_action: "READY",
					formula_validation_status: "PASS",
					sales_clarity_status: "CLEAR",
				}}
			/>,
		);
		expect(screen.getByTestId("readiness-badge").textContent?.trim()).toBe("READY");
		expect(screen.queryByTestId("readiness-prepare-cta")).not.toBeInTheDocument();
	});

	it("copy_applicable=false → renders nothing", () => {
		const { container } = render(
			<CopywritingReadinessCard readiness={{ ...base, copy_applicable: false }} />,
		);
		expect(container).toBeEmptyDOMElement();
	});
});
