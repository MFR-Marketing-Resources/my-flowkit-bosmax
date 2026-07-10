import { describe, expect, it } from "vitest";
import {
	buildOperatorDurationAuthority,
	transitionOperatorDurationAuthority,
} from "./OperatorPage";

describe("OperatorPage unified duration authority", () => {
	it.each(["T2V", "HYBRID", "F2V", "I2V"])(
		"uses the shared SINGLE payload contract for %s",
		() => {
			const authority = buildOperatorDurationAuthority({
				generationMode: "SINGLE",
				videoDurationSeconds: 10,
				extendTotalDurationSeconds: null,
			});

			expect(authority.payload).toEqual({
				generation_mode: "SINGLE",
				duration_seconds: 10,
				blocks: [],
			});
			expect("requested_total_duration_seconds" in authority.payload).toBe(false);
			expect("engine_duration_target" in authority.payload).toBe(false);
			expect(authority.plan).toEqual([10]);
		},
	);

	it("derives the authorized Google Flow route, plan, timeline, and payload for a 24s EXTEND", () => {
		const authority = buildOperatorDurationAuthority({
			generationMode: "EXTEND",
			videoDurationSeconds: 8,
			extendTotalDurationSeconds: 24,
		});

		expect(authority.route).toBe("GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS");
		expect(authority.plan).toEqual([8, 8, 8]);
		expect(authority.timeline).toEqual([
			{ block_index: 1, start_s: 0, end_s: 8 },
			{ block_index: 2, start_s: 8, end_s: 16 },
			{ block_index: 3, start_s: 16, end_s: 24 },
		]);
		expect(authority.payload).toEqual({
			generation_mode: "EXTEND",
			engine_duration_target: "GOOGLE_FLOW",
			requested_total_duration_seconds: 24,
		});
		expect("blocks" in authority.payload).toBe(false);
	});

	it("fails closed when EXTEND has no selected total", () => {
		expect(() =>
			buildOperatorDurationAuthority({
				generationMode: "EXTEND",
				videoDurationSeconds: 8,
				extendTotalDurationSeconds: null,
			}),
		).toThrow("EXTEND_TOTAL_DURATION_REQUIRED");
	});

	it("clears stale EXTEND duration state and all compiled-package artifacts on SINGLE", () => {
		expect(
			transitionOperatorDurationAuthority(
				{
					generationMode: "EXTEND",
					extendTotalDurationSeconds: 24,
				},
				"SINGLE",
			),
		).toEqual({
			generationMode: "SINGLE",
			extendTotalDurationSeconds: null,
			clearCompiledArtifacts: true,
		});
	});
});
