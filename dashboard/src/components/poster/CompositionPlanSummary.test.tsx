import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { CompositionPlan } from "../../types/posterCompositionPlan";
import CompositionPlanSummary from "./CompositionPlanSummary";

// Backend-resolved sample plans (shape mirrors the canonical resolver output;
// the VALUES themselves are proven by tests/unit/test_poster_composition_service.py
// — this component only displays them verbatim).
function backendPlan(mode: string, overrides: Partial<CompositionPlan> = {}): CompositionPlan {
	return {
		schema_version: "wrna-poster-composition-v1",
		profile_id: `${mode.toLowerCase()}_profile_v1`,
		creative_mode: mode,
		recipe_id: "product_hero_night_routine",
		authority_versions: {
			creative_direction: "creative-direction-modes-v1",
			representation_policy: "malaysian-representation-policy-v1",
		},
		provenance: {
			constraint_schema: "wrna-composition-constraints-v1",
			active_locks: ["PRODUCT_TRUTH", "RECIPE_SAFE_REGION"],
			suppressions: [
				{
					property: "product.anchor",
					mode_value: "middle-right",
					resolved_value: "middle-center",
					reason: "RECIPE_SAFE_REGION_LOCK",
					authority: "RECIPE",
				},
			],
		},
		canvas: { frame_ratio: "9:16", safe_margin: "5%" },
		reading_order: ["product", "hook", "cta", "usp"],
		product: {
			anchor: "middle-center",
			dominance: "70-80%",
			label_visibility: "required",
			real_world_scale: "required",
			identity_lock: true,
		},
		copy: {
			copy_side: "stacked",
			hook_zone: "top-center",
			usp_zone: "lower-center band",
			cta_zone: "bottom-center",
		},
		typography: {
			hook: "bold campaign headline",
			usp: "two tight proof lines",
			cta: "high-contrast campaign button",
			intensity: "high-impact display",
		},
		scene: {
			lighting: "campaign key light",
			human_presence: "optional",
			identity_policy: "unrestricted natural person",
			face_safe_rule: "upper-right protected when present",
			background_complexity: "controlled cinematic gradient",
		},
		warnings: ["PRODUCT_COPY_ZONE_CONFLICT_RESOLVED"],
		blockers: [],
		signature: `sig-${mode}`,
		...overrides,
	};
}

const MODES = [
	"PGC_CAMPAIGN",
	"UGC_AUTHENTIC",
	"MODEL_AMBASSADOR",
	"CLEAN_STUDIO_CATALOGUE",
	"LIFESTYLE_EDITORIAL",
];

describe("CompositionPlanSummary", () => {
	afterEach(() => cleanup());

	it("renders every backend-resolved governed mode compactly (no raw JSON)", () => {
		for (const mode of MODES) {
			const { unmount } = render(
				<CompositionPlanSummary plan={backendPlan(mode)} />,
			);
			const panel = screen.getByTestId("poster-composition-plan");
			expect(panel.getAttribute("data-mode")).toBe(mode);
			expect(panel.textContent).toContain(mode);
			expect(panel.textContent).toContain("middle-center");
			expect(panel.textContent).toContain("70-80%");
			expect(panel.textContent).toContain("product → hook → cta → usp");
			expect(panel.textContent).toContain("5%");
			expect(panel.textContent).toContain("top-center");
			expect(panel.textContent).toContain("bottom-center");
			expect(panel.textContent).toContain("campaign key light");
			// No raw JSON dump.
			expect(panel.textContent).not.toContain("{");
			expect(panel.textContent).not.toContain("schema_version");
			unmount();
		}
	});

	it("renders authority locks, suppressions, warnings and blockers", () => {
		render(
			<CompositionPlanSummary
				plan={backendPlan("PGC_CAMPAIGN", {
					blockers: ["UNSUPPORTED_CLAIM_BADGE"],
				})}
			/>,
		);
		expect(
			screen.getByTestId("poster-composition-locks").textContent,
		).toContain("PRODUCT_TRUTH");
		const supp = screen.getByTestId("poster-composition-suppressions");
		expect(supp.textContent).toContain("product.anchor");
		expect(supp.textContent).toContain("middle-right → middle-center");
		expect(supp.textContent).toContain("RECIPE_SAFE_REGION_LOCK");
		expect(
			screen.getByTestId("poster-composition-warnings").textContent,
		).toContain("PRODUCT_COPY_ZONE_CONFLICT_RESOLVED");
		expect(
			screen.getByTestId("poster-composition-blockers").textContent,
		).toContain("UNSUPPORTED_CLAIM_BADGE");
	});

	it("renders nothing for the legacy empty plan", () => {
		render(<CompositionPlanSummary plan={{}} />);
		expect(screen.queryByTestId("poster-composition-plan")).toBeNull();
		cleanup();
		render(<CompositionPlanSummary plan={null} />);
		expect(screen.queryByTestId("poster-composition-plan")).toBeNull();
	});

	it("proves compile-plan identity via the signature match indicator", () => {
		render(
			<CompositionPlanSummary
				plan={backendPlan("PGC_CAMPAIGN")}
				compiledSignature="sig-PGC_CAMPAIGN"
			/>,
		);
		expect(
			screen.getByTestId("poster-composition-plan-match"),
		).toBeInTheDocument();
		cleanup();
		render(
			<CompositionPlanSummary
				plan={backendPlan("PGC_CAMPAIGN")}
				compiledSignature="sig-OTHER"
			/>,
		);
		expect(
			screen.getByTestId("poster-composition-plan-mismatch"),
		).toBeInTheDocument();
		cleanup();
		// No compile yet → no verdict either way.
		render(<CompositionPlanSummary plan={backendPlan("PGC_CAMPAIGN")} />);
		expect(screen.queryByTestId("poster-composition-plan-match")).toBeNull();
		expect(screen.queryByTestId("poster-composition-plan-mismatch")).toBeNull();
	});

	it("shows loading and error states without inventing plan values", () => {
		render(<CompositionPlanSummary plan={null} loading />);
		expect(
			screen.getByTestId("poster-composition-plan-loading"),
		).toBeInTheDocument();
		cleanup();
		render(<CompositionPlanSummary plan={null} error="Gagal" />);
		expect(
			screen.getByTestId("poster-composition-plan-error").textContent,
		).toContain("Gagal");
	});
});
