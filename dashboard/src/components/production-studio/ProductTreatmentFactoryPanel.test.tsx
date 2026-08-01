import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const listFactoryPlans = vi.fn();
const getFactoryPlan = vi.fn();
const createFactoryPlan = vi.fn();
const prepareFactoryPlan = vi.fn();
const pauseFactoryPlan = vi.fn();
const resumeFactoryPlan = vi.fn();

vi.mock("../../api/productTreatmentFactory", () => ({
	listFactoryPlans: (...args: unknown[]) => listFactoryPlans(...args),
	getFactoryPlan: (...args: unknown[]) => getFactoryPlan(...args),
	createFactoryPlan: (...args: unknown[]) => createFactoryPlan(...args),
	prepareFactoryPlan: (...args: unknown[]) => prepareFactoryPlan(...args),
	pauseFactoryPlan: (...args: unknown[]) => pauseFactoryPlan(...args),
	resumeFactoryPlan: (...args: unknown[]) => resumeFactoryPlan(...args),
}));

import ProductTreatmentFactoryPanel from "./ProductTreatmentFactoryPanel";

const HASH_A = "a".repeat(64);
const HASH_B = "b".repeat(64);
const HASH_C = "c".repeat(64);

function snapshot(productId: string, blocked = false) {
	return {
		context: {
			product_id: productId,
			selected_action_index: 0,
			format: "UGC",
			logical_mode: "HYBRID",
			generation_mode: "SINGLE",
			model_key: "veo_3_1_fast",
			duration_seconds: 8,
		},
		readiness: {
			product_id: productId,
			primary_status: blocked ? "EVIDENCE_REQUIRED" : "READY",
			product_authority_sha256: HASH_A,
			readiness_sha256: blocked ? HASH_B : HASH_C,
			next_actions: blocked ? ["REVIEW_PRODUCT_EVIDENCE"] : [],
			applicability_profile: {
				product_family: blocked ? "BEAUTY" : "FOOD",
				product_type: blocked ? "SERUM" : "SPICE_SEASONING",
			},
			evidence_requirements: [
				{
					requirement_code: "INGREDIENTS_EVIDENCE",
					state: blocked ? "NOT_STATED_IN_EVIDENCE" : "VERIFIED_VALUE",
					rule_code: "INGREDIENTS_RULE",
					source_fields: ["ingredients_text"],
					provenance_hashes: [HASH_A],
				},
			],
			blockers: blocked
				? [
						{
							code: "EVIDENCE_NOT_STATED_IN_EVIDENCE",
							message: "Ingredients evidence is not stated.",
							next_action: "REVIEW_PRODUCT_EVIDENCE",
						},
					]
				: [],
		},
		resolved_authority: {
			taxonomy: {
				product_type_group: blocked ? "beauty_serum" : "spice_seasoning",
				cluster: blocked ? "Beauty" : "Food & Beverage",
				taxonomy_fingerprint: HASH_B,
			},
			product_truth: {
				snapshot_id: `${productId}-truth`,
				provenance: [
					{
						provenance_id: `${productId}-provenance`,
						field_name: "ingredients_text",
						source_type: "PRODUCT_TRUTH",
						source_lane: "CANONICAL",
						verification_status: blocked ? "NOT_STATED" : "VERIFIED",
						provenance_sha256: HASH_A,
					},
				],
			},
			copy: {
				grounding_ready: !blocked,
				grounding_source: "PRODUCT_TRUTH",
				approved_copy_set_ids: blocked ? [] : [`${productId}-copy`],
			},
			selection: {
				selected_avatar_code: blocked ? null : "BOS_F_01",
				selected_scene_template_id: "SCENE_KITCHEN",
				selected_camera_preset_code: "CAM_PRODUCT_CLOSEUP",
			},
			assets: {
				required_roles: ["PRODUCT_REFERENCE"],
				eligible_asset_ids_by_role: {
					PRODUCT_REFERENCE: [`${productId}-asset`],
				},
				missing_roles: blocked ? ["PRODUCT_REFERENCE"] : [],
			},
			treatment: {
				approved_treatment_ids: blocked ? [] : [`${productId}-treatment`],
				selected_treatment_ids: blocked ? [] : [`${productId}-treatment`],
				availability_sha256: HASH_C,
				p6_ready: !blocked,
			},
		},
		treatment_template: {
			action_text: "Present the governed product action",
			format: "UGC",
			actor_policy: "PRESENTER_REQUIRED",
			action_sequence: [
				{
					sequence: 1,
					actor_role: "PRESENTER",
					action_text: "Hold the product",
					initial_state: "SEALED",
					resulting_state: "PRESENTED",
				},
			],
			shot_grammar: [
				{
					sequence: 1,
					framing: "MEDIUM_CLOSE_UP",
					camera_motion: "LOCKED",
					subject: "Presenter and product",
					purpose: "Hook",
				},
			],
			compatibility_profile: {
				required_asset_roles: ["PRODUCT_REFERENCE"],
			},
		},
		copy_preview: { produced: blocked ? 0 : 1 },
		existing_treatments: blocked
			? []
			: [
					{
						avatar_code: "BOS_F_01",
						wardrobe_text: "modest neutral wardrobe",
						scene_template_id: "SCENE_KITCHEN",
						camera_preset_code: "CAM_PRODUCT_CLOSEUP",
					},
				],
		scan_error_code: null,
		provider_calls: 0,
		media_generation_calls: 0,
		credit_spend: 0,
	};
}

function task(productId: string, blocked = false) {
	return {
		task_id: `${productId}-task`,
		plan_id: "factory-plan-1",
		product_id: productId,
		task_type: blocked ? "EVIDENCE_REVIEW" : "TREATMENT_CANDIDATE",
		status: blocked ? "REVIEW_REQUIRED" : "SATISFIED",
		task_identity_sha256: HASH_A,
		required_authority_sha256: HASH_B,
		blocker_code: blocked ? "EVIDENCE_NOT_STATED_IN_EVIDENCE" : null,
		next_action: blocked ? "REVIEW_PRODUCT_EVIDENCE" : null,
		template_id: `${productId}-template`,
		template_sha256: HASH_C,
		treatment_id: blocked ? null : `${productId}-treatment`,
		treatment_sha256: blocked ? null : HASH_A,
		snapshot: snapshot(productId, blocked),
		result: blocked
			? {}
			: {
					lineage: {
						template_id: `${productId}-template`,
						template_sha256: HASH_C,
						treatment_id: `${productId}-treatment`,
						treatment_sha256: HASH_A,
					},
				},
		error_code: null,
		attempt_count: 0,
		created_at: "2026-07-31T00:00:00Z",
		updated_at: "2026-07-31T00:00:00Z",
	};
}

function plan(status = "SCANNED") {
	return {
		plan_id: "factory-plan-1",
		plan_identity_sha256: HASH_A,
		cohort_sha256: HASH_B,
		context_sha256: HASH_C,
		status,
		product_count: 2,
		request: {},
		authority_versions: {},
		readiness_summary: { SATISFIED: 1, REVIEW_REQUIRED: 1 },
		capacity_summary: {
			target_video_count: 1,
			required_dialogues: 1,
			variation_group_reuse_cap: 5,
			approved_copy_set_count: 1,
			required_copy_set_count: 1,
			copy_shortfall: 0,
			approved_master_treatment_count: 1,
			required_treatment_count: 1,
			treatment_shortfall: 0,
			unique_material_count: 1,
			unique_compiled_payload_count: 1,
		},
		failure_count: 0,
		provider_calls_enabled: false,
		media_generation_enabled: false,
		created_by: "factory-production-operator",
		created_at: "2026-07-31T00:00:00Z",
		updated_at: "2026-07-31T00:00:00Z",
		tasks: [task("product-ready"), task("product-blocked", true)],
	};
}

beforeEach(() => {
	listFactoryPlans.mockResolvedValue({ plans: [plan()] });
	getFactoryPlan.mockResolvedValue(plan());
	createFactoryPlan.mockResolvedValue(plan());
	prepareFactoryPlan.mockResolvedValue(plan("COMPLETED_WITH_BLOCKERS"));
	pauseFactoryPlan.mockResolvedValue(plan("PAUSED"));
	resumeFactoryPlan.mockResolvedValue(plan("SCANNED"));
});

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe("ProductTreatmentFactoryPanel", () => {
	it("renders loading and empty states without inventing a plan", async () => {
		listFactoryPlans.mockResolvedValueOnce({ plans: [] });
		render(<ProductTreatmentFactoryPanel />);
		expect(screen.getByTestId("ptf-loading-state")).toBeInTheDocument();
		expect(await screen.findByTestId("ptf-empty-state")).toHaveTextContent(
			"No factory plans exist",
		);
	});

	it("renders exact readiness, evidence, provenance, and visual lineage per product", async () => {
		render(<ProductTreatmentFactoryPanel />);
		const select = await screen.findByLabelText("Select factory plan");
		fireEvent.change(select, { target: { value: "factory-plan-1" } });
		expect(await screen.findByTestId("ptf-success-state")).toBeInTheDocument();
		expect(screen.getByTestId("ptf-blocked-state")).toHaveTextContent(
			"1 product",
		);
		expect(screen.getByTestId("ptf-capacity-summary")).toHaveTextContent("Target videos");
		fireEvent.click(screen.getByText("product-ready"));
		expect(screen.getByText("VERIFIED_VALUE")).toBeInTheDocument();
		expect(screen.getByText("ingredients_text · VERIFIED")).toBeInTheDocument();
		expect(screen.getByText("modest neutral wardrobe")).toBeInTheDocument();
		expect(screen.getAllByText("SCENE_KITCHEN").length).toBeGreaterThan(0);
		expect(
			screen.getAllByText(/MEDIUM_CLOSE_UP.*LOCKED/).length,
		).toBeGreaterThan(0);
		expect(screen.getByText(/product-ready-template/)).toBeInTheDocument();
	});

	it("creates an explicit deterministic cohort with zero-credit flags locked false", async () => {
		listFactoryPlans.mockResolvedValueOnce({ plans: [] });
		render(<ProductTreatmentFactoryPanel />);
		await screen.findByTestId("ptf-empty-state");
		fireEvent.click(screen.getByLabelText("Explicit product IDs"));
		fireEvent.change(screen.getByLabelText("Factory product IDs"), {
			target: { value: "product-b\nproduct-a\nproduct-b" },
		});
		fireEvent.click(screen.getByTestId("ptf-create-plan"));
		await waitFor(() => expect(createFactoryPlan).toHaveBeenCalledTimes(1));
		expect(createFactoryPlan).toHaveBeenCalledWith(
			expect.objectContaining({
				scan_all_active: false,
				target_video_count: 1,
				provider_calls_enabled: false,
				media_generation_enabled: false,
				products: [
					expect.objectContaining({ product_id: "product-a" }),
					expect.objectContaining({ product_id: "product-b" }),
				],
			}),
		);
		expect(await screen.findByTestId("ptf-success-state")).toBeInTheDocument();
	});

	it("prepares, pauses, and resumes through governed zero-credit controls", async () => {
		render(<ProductTreatmentFactoryPanel />);
		fireEvent.change(await screen.findByLabelText("Select factory plan"), {
			target: { value: "factory-plan-1" },
		});
		await screen.findByTestId("ptf-success-state");
		fireEvent.click(screen.getByTestId("ptf-prepare-plan"));
		await waitFor(() => expect(prepareFactoryPlan).toHaveBeenCalledTimes(1));
		expect(prepareFactoryPlan).toHaveBeenCalledWith(
			"factory-plan-1",
			expect.objectContaining({
				provider_calls_enabled: false,
				media_generation_enabled: false,
				materialize_copy_composition: true,
				materialize_treatment_candidates: true,
			}),
		);
		fireEvent.click(screen.getByTestId("ptf-pause-plan"));
		await waitFor(() => expect(pauseFactoryPlan).toHaveBeenCalledTimes(1));
		fireEvent.click(await screen.findByTestId("ptf-resume-plan"));
		await waitFor(() => expect(resumeFactoryPlan).toHaveBeenCalledTimes(1));
	});

	it("surfaces API failures without replacing them with a generic ready state", async () => {
		listFactoryPlans.mockRejectedValueOnce(new Error("FACTORY_API_OFFLINE"));
		render(<ProductTreatmentFactoryPanel />);
		expect(await screen.findByTestId("ptf-error-state")).toHaveTextContent(
			"FACTORY_API_OFFLINE",
		);
		expect(screen.queryByTestId("ptf-success-state")).not.toBeInTheDocument();
	});
});
