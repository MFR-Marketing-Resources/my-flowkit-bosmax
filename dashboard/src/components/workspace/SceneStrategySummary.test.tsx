/**
 * Workflow Upgrade V1 — Scene Strategy authority summary contract.
 *
 * Renders the product's EXISTING strategy_taxonomy semantics: VERIFIED,
 * REVIEW_REQUIRED, FALLBACK_ONLY coverage, and stale conditions — plus the
 * explicit distinction from the Scene Registry Background override.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ProductStrategyTaxonomy } from "../../types";
import SceneStrategySummary, {
	resolveSceneStrategySummaryState,
} from "./SceneStrategySummary";

afterEach(() => cleanup());

function taxonomy(
	over: Partial<ProductStrategyTaxonomy> = {},
): ProductStrategyTaxonomy {
	return {
		product_id: "p1",
		taxonomy_version: "v1",
		product_fingerprint: "fp",
		cluster: "BEAUTY",
		product_type_group: "SERUM",
		matched_scene_strategy_id: "scene_strategy.beauty.serum.v1",
		scene_coverage_status: "COVERED",
		fallback_used: false,
		specific_strategy: true,
		classification_confidence: "HIGH",
		review_status: "VERIFIED",
		consumer_status: "READY",
		authority_source: "AUTO_DERIVED",
		materialization_status: "MATERIALIZED",
		review_reasons: [],
		is_stale: false,
		...over,
	};
}

describe("SceneStrategySummary — taxonomy states", () => {
	it("shows the Scene Strategy ID and VERIFIED state for a verified taxonomy", () => {
		render(<SceneStrategySummary hasProduct taxonomy={taxonomy()} />);
		const root = screen.getByTestId("scene-strategy-summary");
		expect(root).toHaveAttribute("data-state", "VERIFIED");
		expect(root).toHaveAttribute(
			"data-scene-strategy-id",
			"scene_strategy.beauty.serum.v1",
		);
		expect(root).toHaveTextContent("scene_strategy.beauty.serum.v1");
		expect(screen.getByTestId("scene-strategy-review-status")).toHaveTextContent(
			"VERIFIED",
		);
	});

	it("surfaces REVIEW_REQUIRED", () => {
		render(
			<SceneStrategySummary
				hasProduct
				taxonomy={taxonomy({
					review_status: "REVIEW_REQUIRED",
					consumer_status: "BLOCKED_REVIEW_REQUIRED",
				})}
			/>,
		);
		const root = screen.getByTestId("scene-strategy-summary");
		expect(root).toHaveAttribute("data-state", "REVIEW_REQUIRED");
		expect(
			screen.getByTestId("scene-strategy-consumer-status"),
		).toHaveTextContent("BLOCKED_REVIEW_REQUIRED");
	});

	it("surfaces FALLBACK_ONLY coverage and the fallback-used chip", () => {
		render(
			<SceneStrategySummary
				hasProduct
				taxonomy={taxonomy({
					scene_coverage_status: "FALLBACK_ONLY",
					fallback_used: true,
				})}
			/>,
		);
		const root = screen.getByTestId("scene-strategy-summary");
		expect(root).toHaveAttribute("data-state", "FALLBACK_ONLY");
		expect(root).toHaveAttribute("data-fallback-used", "true");
		expect(screen.getByTestId("scene-strategy-fallback-used")).toBeVisible();
	});

	it("surfaces stale taxonomy as the headline condition", () => {
		render(
			<SceneStrategySummary
				hasProduct
				taxonomy={taxonomy({ is_stale: true })}
			/>,
		);
		const root = screen.getByTestId("scene-strategy-summary");
		expect(root).toHaveAttribute("data-state", "STALE");
		expect(root).toHaveAttribute("data-stale", "true");
		expect(screen.getByTestId("scene-strategy-stale")).toBeVisible();
	});

	it("renders guidance without a product and an absent state without taxonomy", () => {
		const { unmount } = render(
			<SceneStrategySummary hasProduct={false} taxonomy={null} />,
		);
		expect(screen.getByTestId("scene-strategy-summary")).toHaveAttribute(
			"data-state",
			"NO_PRODUCT",
		);
		unmount();
		render(
			<SceneStrategySummary hasProduct taxonomy={null} productName="Alpha" />,
		);
		expect(screen.getByTestId("scene-strategy-summary")).toHaveAttribute(
			"data-state",
			"ABSENT",
		);
		expect(screen.getByTestId("scene-strategy-summary")).toHaveTextContent(
			"Alpha",
		);
	});

	it("explicitly distinguishes Scene Strategy from Scene Registry Background", () => {
		render(<SceneStrategySummary hasProduct taxonomy={taxonomy()} />);
		expect(
			screen.getByTestId("scene-strategy-registry-distinction"),
		).toHaveTextContent("distinct from the Scene Registry Background");
	});
});

describe("resolveSceneStrategySummaryState — worst-condition ordering", () => {
	it("orders STALE > FALLBACK_ONLY > REVIEW_REQUIRED > VERIFIED", () => {
		expect(resolveSceneStrategySummaryState(false, null)).toBe("NO_PRODUCT");
		expect(resolveSceneStrategySummaryState(true, null)).toBe("ABSENT");
		expect(
			resolveSceneStrategySummaryState(
				true,
				taxonomy({ is_stale: true, scene_coverage_status: "FALLBACK_ONLY" }),
			),
		).toBe("STALE");
		expect(
			resolveSceneStrategySummaryState(
				true,
				taxonomy({
					scene_coverage_status: "FALLBACK_ONLY",
					review_status: "REVIEW_REQUIRED",
				}),
			),
		).toBe("FALLBACK_ONLY");
		expect(
			resolveSceneStrategySummaryState(
				true,
				taxonomy({ review_status: "REVIEW_REQUIRED" }),
			),
		).toBe("REVIEW_REQUIRED");
		expect(resolveSceneStrategySummaryState(true, taxonomy())).toBe("VERIFIED");
	});
});
