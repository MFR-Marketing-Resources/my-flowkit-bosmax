import { describe, expect, it } from "vitest";
import type { V3AssistantPlan, V3LandbankItem, V3ProductionCapacity } from "../api/storyboardLandbankV3Round2";
import {
	blockerToOperator,
	buildPreflightSummary,
	resolvePrimaryTruthBlocker,
	capacityLabels,
	extractBlockerCode,
	inferAssistantMode,
	masterStatusToOperator,
	materializationToOperator,
	missingCopies,
	reconstructStep,
	resolveNextAction,
	reviewBuckets,
	toOperatorError,
	type WorkflowCounts,
} from "./storyboardLandbankResolver";

function capacity(overrides: Partial<V3ProductionCapacity> = {}): V3ProductionCapacity {
	return {
		product_id: "p1",
		semantic_capacity: 0,
		projection_capacity: 0,
		executable_copy_capacity: 0,
		production_capacity: 0,
		stale_copy_count: 0,
		production_capacity_note: "note",
		...overrides,
	};
}

function plan(overrides: Partial<V3AssistantPlan> = {}): V3AssistantPlan {
	return {
		plan_id: "plan-1",
		run_id: "run-1",
		product_id: "p1",
		recipe: { entity_id: "recipe-1", revision: 1 },
		formula: { formula_id: "PAS", formula_version: "pas.v1" },
		mode: "CREATE",
		target_counts: {},
		gaps: [{ semantic_class: "HOOK", current_count: 0, target_count: 1, gap_count: 1, reason: "t" }],
		target_durations_seconds: [8, 16, 24],
		wps_mode: "SAFE",
		provider: { lane: "text_assist", status: "READY", configured: true, execution_enabled: true, provider_calls: 0, credit_spend: 0, fake_provider_allowed: false },
		prompt_version: "v1",
		prompt_digest: "d".repeat(64),
		estimated_provider_calls: 1,
		estimated_output_tokens: 100,
		estimated_credit_spend: 0,
		max_proposals: 3,
		evidence_fact_ids: ["fact:p1:benefit:0"],
		explicit_execute_required: true,
		created_at: "2026-08-18T00:00:00Z",
		created_by: "operator",
		...overrides,
	};
}

function landbankItem(overrides: { status?: string; hardPass?: boolean; masterId?: string } = {}): V3LandbankItem {
	const status = overrides.status ?? "VALIDATED";
	return {
		master: {
			master_id: overrides.masterId ?? "m1",
			revision: 1,
			product_id: "p1",
			formula: { formula_id: "PAS", formula_version: "pas.v1" },
			angle: { entity_id: "a1", revision: 1 },
			storyline_family: { entity_id: "f1", revision: 1 },
			stages: [],
			status,
			source: "ROUND2",
			exact_content_digest: "a".repeat(64),
			word_count: 10,
		},
		projections: [],
		quality: {
			hard_pass: overrides.hardPass ?? true,
			formula_valid: true,
			evidence_valid: true,
			bridge_valid: true,
			claim_safety_valid: true,
			truth_current: true,
			wps_valid: true,
			issue_codes: [],
			novelty_signal: "NOVEL",
			novelty_score: 1,
			quality_score: 1,
		},
		current_truth: true,
		approval_receipt: null,
		v2_materialization: "NOT_IN_ROUND2",
		p6_status: "NOT_IN_ROUND2",
	};
}

const baseCounts: WorkflowCounts = { target: 54, approved: 0, reviewable: 0, productionReady: 0, needsPreparation: 0, needsRevalidation: 0 };

describe("inferAssistantMode", () => {
	it("returns CREATE when there is no approved supply", () => {
		expect(inferAssistantMode({ existingApproved: 0, target: 54 })).toBe("CREATE");
	});
	it("returns FILL_CAPACITY when supply is below target", () => {
		expect(inferAssistantMode({ existingApproved: 18, target: 54 })).toBe("FILL_CAPACITY");
	});
	it("returns EXPAND when supply meets or exceeds target", () => {
		expect(inferAssistantMode({ existingApproved: 54, target: 54 })).toBe("EXPAND");
		expect(inferAssistantMode({ existingApproved: 60, target: 54 })).toBe("EXPAND");
	});
});

describe("missingCopies", () => {
	it("is target minus approved, floored at zero", () => {
		expect(missingCopies({ target: 54, approved: 18 })).toBe(36);
		expect(missingCopies({ target: 54, approved: 54 })).toBe(0);
		expect(missingCopies({ target: 10, approved: 20 })).toBe(0);
	});
});

describe("resolveNextAction", () => {
	it("asks for a product first", () => {
		expect(resolveNextAction({ hasProduct: false, recipeReady: false, counts: baseCounts }).kind).toBe("SELECT_PRODUCT");
	});
	it("asks to set up the campaign when no recipe is resolved", () => {
		const action = resolveNextAction({ hasProduct: true, recipeReady: false, counts: baseCounts });
		expect(action.kind).toBe("SETUP");
		expect(action.step).toBe("SETUP");
	});
	it("recommends generating the full target when campaign is ready and nothing exists", () => {
		const action = resolveNextAction({ hasProduct: true, recipeReady: true, counts: { ...baseCounts, target: 54 } });
		expect(action.kind).toBe("GENERATE");
		expect(action.label).toContain("54");
	});
	it("prioritises review over generating more", () => {
		const action = resolveNextAction({ hasProduct: true, recipeReady: true, counts: { ...baseCounts, approved: 18, reviewable: 5 } });
		expect(action.kind).toBe("REVIEW");
		expect(action.label).toContain("5");
	});
	it("recommends generating the missing copies", () => {
		const action = resolveNextAction({ hasProduct: true, recipeReady: true, counts: { ...baseCounts, target: 54, approved: 18 } });
		expect(action.kind).toBe("GENERATE");
		expect(action.count).toBe(36);
	});
	it("recommends preparing when approved copy is not production ready", () => {
		const action = resolveNextAction({ hasProduct: true, recipeReady: true, counts: { ...baseCounts, target: 18, approved: 18, needsPreparation: 4 } });
		expect(action.kind).toBe("PREPARE");
		expect(action.count).toBe(4);
	});
	it("recommends opening production studio when everything is ready", () => {
		const action = resolveNextAction({ hasProduct: true, recipeReady: true, counts: { ...baseCounts, target: 18, approved: 18, productionReady: 18 } });
		expect(action.kind).toBe("OPEN_STUDIO");
	});
	it("recommends resolving a blocker instead of generating when generation is blocked", () => {
		const action = resolveNextAction({
			hasProduct: true,
			recipeReady: true,
			counts: { ...baseCounts, target: 54 },
			blocker: { code: "PRODUCT_TRUTH_NOT_FOUND", message: "no truth", actionLabel: "Set up Product Truth", actionRoute: "/products" },
		});
		expect(action.kind).toBe("RESOLVE_BLOCKER");
		expect(action.actionRoute).toBe("/products");
	});
});

describe("resolvePrimaryTruthBlocker", () => {
	it("blocks with PRODUCT_TRUTH_NOT_FOUND when the snapshot is not approved (regardless of fact count)", () => {
		expect(resolvePrimaryTruthBlocker({ truthApproved: false, truthFactCount: 5 })?.code).toBe("PRODUCT_TRUTH_NOT_FOUND");
	});
	it("blocks with NO_APPROVED_EVIDENCE when approved but there are no current facts", () => {
		expect(resolvePrimaryTruthBlocker({ truthApproved: true, truthFactCount: 0 })?.code).toBe("NO_APPROVED_EVIDENCE");
	});
	it("is clear when approved with current evidence", () => {
		expect(resolvePrimaryTruthBlocker({ truthApproved: true, truthFactCount: 3 })).toBeNull();
	});
});

describe("reconstructStep", () => {
	it("honors a valid explicit URL step", () => {
		expect(reconstructStep({ urlStep: "GENERATE", hasProduct: true, recipeReady: false, reviewableCount: 0, approvedCount: 0 })).toBe("GENERATE");
	});
	it("falls back to SETUP without a product", () => {
		expect(reconstructStep({ urlStep: null, hasProduct: false, recipeReady: true, reviewableCount: 9, approvedCount: 9 })).toBe("SETUP");
	});
	it("reconstructs REVIEW from existing reviewable copy even without a client recipe id", () => {
		expect(reconstructStep({ urlStep: null, hasProduct: true, recipeReady: false, reviewableCount: 3, approvedCount: 0 })).toBe("REVIEW");
	});
	it("reconstructs PRODUCTION from approved copy", () => {
		expect(reconstructStep({ urlStep: null, hasProduct: true, recipeReady: false, reviewableCount: 0, approvedCount: 5 })).toBe("PRODUCTION");
	});
	it("lands on GENERATE when the campaign is ready but empty", () => {
		expect(reconstructStep({ urlStep: null, hasProduct: true, recipeReady: true, reviewableCount: 0, approvedCount: 0 })).toBe("GENERATE");
	});
});

describe("blockerToOperator", () => {
	it("translates a known code into operator language and keeps the raw code", () => {
		const blocker = blockerToOperator("COPY_V3_EVIDENCE_AUTHORITY_MISMATCH");
		expect(blocker.code).toBe("COPY_V3_EVIDENCE_AUTHORITY_MISMATCH");
		expect(blocker.message).toMatch(/Product Truth changed/);
		expect(blocker.actionLabel).toBe("Review Product Truth");
	});
	it("falls back safely for an unknown code but preserves it", () => {
		const blocker = blockerToOperator("SOME_NEW_CODE");
		expect(blocker.code).toBe("SOME_NEW_CODE");
		expect(blocker.message).toMatch(/Technical Details/);
	});
	it("extracts a code from an API error message", () => {
		expect(extractBlockerCode("COPY_V2_EVIDENCE_STALE: something happened")).toBe("COPY_V2_EVIDENCE_STALE");
		expect(extractBlockerCode("plain text")).toBe("");
	});
});

describe("toOperatorError", () => {
	it("translates a known operational code to operator language", () => {
		expect(toOperatorError("DUPLICATE_COMPONENT: An exact component content revision already exists.")).toMatch(/already created/);
	});
	it("strips a bare CODE: prefix for unknown codes so the UI never leads with a raw code", () => {
		expect(toOperatorError("SOME_UNKNOWN_CODE: the human readable part")).toBe("the human readable part");
	});
	it("passes through plain messages", () => {
		expect(toOperatorError("Network request failed.")).toBe("Network request failed.");
	});
});

describe("buildPreflightSummary", () => {
	it("is READY when truth is approved, evidence exists, and a plan is present", () => {
		const summary = buildPreflightSummary({ plan: plan(), capacity: capacity({ semantic_capacity: 18 }), target: 54, truthApproved: true, truthFactCount: 3 });
		expect(summary.ready).toBe(true);
		expect(summary.productTruth).toBe("READY");
		expect(summary.evidence).toBe("READY");
		expect(summary.missing).toBe(36);
		expect(summary.formula).toBe("PAS");
		expect(summary.estimatedAiCalls).toBe(1);
	});
	it("fails closed with a no-approved-truth blocker only when the snapshot is not approved", () => {
		const summary = buildPreflightSummary({ plan: plan(), capacity: capacity(), target: 54, truthApproved: false, truthFactCount: 0 });
		expect(summary.ready).toBe(false);
		expect(summary.productTruth).toBe("ACTION REQUIRED");
		expect(summary.blockers[0].code).toBe("PRODUCT_TRUTH_NOT_FOUND");
	});
	it("keeps Product Truth READY but flags evidence when the approved snapshot has no usable facts", () => {
		// The Sambal Nyet class: approved truth, but no current evidence facts. It
		// must NOT read as 'no approved Product Truth'.
		const summary = buildPreflightSummary({ plan: plan(), capacity: capacity(), target: 54, truthApproved: true, truthFactCount: 0 });
		expect(summary.productTruth).toBe("READY");
		expect(summary.evidence).toBe("ACTION REQUIRED");
		expect(summary.blockers[0].code).toBe("NO_APPROVED_EVIDENCE");
	});
	it("surfaces a plan error as an operator blocker with the raw code preserved", () => {
		const summary = buildPreflightSummary({ plan: null, capacity: capacity(), target: 54, truthApproved: true, truthFactCount: 3, planError: "COPY_V3_EVIDENCE_AUTHORITY_MISMATCH: mismatch" });
		expect(summary.ready).toBe(false);
		expect(summary.blockers[0].code).toBe("COPY_V3_EVIDENCE_AUTHORITY_MISMATCH");
	});
});

describe("reviewBuckets", () => {
	it("splits reviewable copy into passed vs needs-attention and separates approved", () => {
		const buckets = reviewBuckets([
			landbankItem({ status: "VALIDATED", hardPass: true, masterId: "m1" }),
			landbankItem({ status: "VALIDATED", hardPass: false, masterId: "m2" }),
			landbankItem({ status: "APPROVED", hardPass: true, masterId: "m3" }),
			landbankItem({ status: "ARCHIVED", hardPass: true, masterId: "m4" }),
		]);
		expect(buckets.passed.map((item) => item.master.master_id)).toEqual(["m1"]);
		expect(buckets.needsAttention.map((item) => item.master.master_id)).toEqual(["m2"]);
		expect(buckets.approved.map((item) => item.master.master_id)).toEqual(["m3"]);
		expect(buckets.reviewable).toBe(2);
	});
});

describe("operator-language mappers", () => {
	it("maps materialization statuses to production language", () => {
		expect(materializationToOperator("MATERIALIZED").label).toBe("Production Ready");
		expect(materializationToOperator("STALE").label).toBe("Needs Revalidation");
		expect(materializationToOperator("BLOCKED").label).toBe("Action Required");
		expect(materializationToOperator("NOT_MATERIALIZED").label).toBe("Needs Preparation");
	});
	it("maps master statuses to plain language", () => {
		expect(masterStatusToOperator("APPROVED").label).toBe("Approved");
		expect(masterStatusToOperator("VALIDATED").label).toBe("Passed checks");
		expect(masterStatusToOperator("DRAFT").label).toBe("Draft");
	});
	it("maps the 4-tier capacity into operator labels", () => {
		const labels = capacityLabels(capacity({ semantic_capacity: 18, projection_capacity: 54, executable_copy_capacity: 12, production_capacity: 12, stale_copy_count: 2 }));
		expect(labels.copyIdeas).toBe(18);
		expect(labels.durationVersions).toBe(54);
		expect(labels.productionReady).toBe(12);
		expect(labels.availableForProduction).toBe(12);
		expect(labels.needsRevalidation).toBe(2);
	});
});
