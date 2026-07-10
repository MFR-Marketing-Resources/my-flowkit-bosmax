import { describe, expect, it } from "vitest";

import {
	type VideoCapabilityMatrix,
	defaultEngine,
	defaultModelLabelForSingle,
	getEngine,
	isCapabilityMatrix,
	modelsForSingle,
	resolveDurationChange,
	resolveSingleSelection,
	singleDurations,
} from "./videoCapability";

const MATRIX: VideoCapabilityMatrix = {
	capability_matrix_version: "video-capability-v1",
	default_engine: "GOOGLE_FLOW",
	engines: [
		{
			id: "GOOGLE_FLOW",
			label: "Google Flow",
			supported: true,
			unsupported_reason: null,
			transport: "flow_creation_agent",
			description: "",
			single_duration_policy: [8, 10],
			default_single_duration: 8,
			models: [
				{ key: "veo_3_1_lite", ui_label: "Veo 3.1 - Lite", allowed_durations_s: [4, 6, 8], default_duration_s: 8 },
				{ key: "omni_flash", ui_label: "Omni Flash", allowed_durations_s: [4, 6, 8, 10], default_duration_s: 10 },
			],
			single_models_by_duration: { "8": ["veo_3_1_lite", "omni_flash"], "10": ["omni_flash"] },
			default_model_by_duration: { "8": "veo_3_1_lite", "10": "omni_flash" },
		},
		{
			id: "GROK",
			label: "Grok",
			supported: false,
			unsupported_reason: "Runtime not yet integrated.",
			transport: null,
			description: "",
			single_duration_policy: [6, 10],
			default_single_duration: 6,
			models: [],
			single_models_by_duration: {},
			default_model_by_duration: {},
		},
	],
};

const flow = getEngine(MATRIX, "GOOGLE_FLOW");
const grok = getEngine(MATRIX, "GROK");

describe("videoCapability resolver", () => {
	it("guards malformed matrix payloads", () => {
		expect(isCapabilityMatrix({ models: [] })).toBe(false);
		expect(isCapabilityMatrix(null)).toBe(false);
		expect(isCapabilityMatrix(MATRIX)).toBe(true);
		expect(getEngine({ models: [] } as never, "GOOGLE_FLOW")).toBeNull();
	});

	it("default engine is the supported Google Flow", () => {
		expect(defaultEngine(MATRIX)?.id).toBe("GOOGLE_FLOW");
	});

	it("Flow SINGLE durations are exactly [8,10]", () => {
		expect(singleDurations(flow)).toEqual([8, 10]);
	});

	it("Grok policy exposed but no models (unsupported)", () => {
		expect(singleDurations(grok)).toEqual([6, 10]);
		expect(modelsForSingle(grok, 6)).toEqual([]);
	});

	it("models filter by operator-policy ∩ registry duration", () => {
		expect(modelsForSingle(flow, 8).map((m) => m.ui_label)).toEqual([
			"Veo 3.1 - Lite",
			"Omni Flash",
		]);
		expect(modelsForSingle(flow, 10).map((m) => m.ui_label)).toEqual(["Omni Flash"]);
		// 6s is a registry capability but NOT in Flow policy → no options.
		expect(modelsForSingle(flow, 6)).toEqual([]);
	});

	it("deterministic default model per duration", () => {
		expect(defaultModelLabelForSingle(flow, 8)).toBe("Veo 3.1 - Lite");
		expect(defaultModelLabelForSingle(flow, 10)).toBe("Omni Flash");
	});

	it("resolveSingleSelection keeps a still-valid model+duration", () => {
		const sel = resolveSingleSelection(flow, "Veo 3.1 - Lite", 8);
		expect(sel).toMatchObject({ model: "Veo 3.1 - Lite", durationSeconds: 8, adjusted: false });
	});

	it("resolveSingleSelection repairs an incompatible model deterministically", () => {
		// Veo has no 10s; keeping duration 10 forces the default 10s model (Omni).
		const sel = resolveSingleSelection(flow, "Veo 3.1 - Lite", 10);
		expect(sel).toMatchObject({ model: "Omni Flash", durationSeconds: 10, adjusted: true });
		expect(sel?.adjustmentReason).toMatch(/adjusted/i);
	});

	it("resolveSingleSelection returns null for an unsupported engine", () => {
		expect(resolveSingleSelection(grok, "Omni Flash", 6)).toBeNull();
	});

	it("resolveDurationChange filters models to the new duration", () => {
		// 8 -> 10 with Veo selected: Veo has no 10s → Omni.
		expect(resolveDurationChange(flow, "Veo 3.1 - Lite", 10)).toMatchObject({
			model: "Omni Flash",
			durationSeconds: 10,
			adjusted: true,
		});
		// Omni stays on a 10s switch.
		expect(resolveDurationChange(flow, "Omni Flash", 10)).toMatchObject({
			model: "Omni Flash",
			durationSeconds: 10,
			adjusted: false,
		});
	});

	it("resolveDurationChange rejects an out-of-policy duration", () => {
		expect(resolveDurationChange(flow, "Omni Flash", 6)).toBeNull();
	});
});
