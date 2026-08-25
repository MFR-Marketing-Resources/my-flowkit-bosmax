import { beforeEach, describe, expect, it } from "vitest";
import {
	collectCreativeProductionSessionResults,
	collectMontageSessionResults,
	forgetGenerationJob,
	readGenerationJobs,
	rememberGenerationJob,
} from "./videoSessionResults";

describe("durable video job session registry", () => {
	beforeEach(() => window.sessionStorage.clear());

	it("survives a utility remount and removes only the completed job", () => {
		rememberGenerationJob({ job_id: "g-session-a", request_id: "req-a", mode: "F2V" });
		rememberGenerationJob({ job_id: "g-session-b", request_id: "req-b", mode: "F2V" });

		expect(readGenerationJobs().map((job) => job.job_id)).toEqual([
			"g-session-b",
			"g-session-a",
		]);
		forgetGenerationJob("g-session-b");
		expect(readGenerationJobs().map((job) => job.job_id)).toEqual(["g-session-a"]);
	});
});

describe("final-only session collectors", () => {
	it("exposes only the final Montage binding", () => {
		expect(
			collectMontageSessionResults(
				{
					config: { assembly: { final_media_id: "montage-final" } },
				},
				null,
			),
		).toEqual([{ media_id: "montage-final", kind: "video" }]);
	});

	it("exposes only P6 item final bindings, never attempt artifacts", () => {
		const detail = {
			items: [
				{ media_type: "VIDEO", output_media_id: "p6-final" },
				{ media_type: "IMAGE", output_media_id: "p6-image" },
			],
			attempts: [{ artifact_media_id: "p6-intermediate" }],
		} as never;
		expect(collectCreativeProductionSessionResults(detail)).toEqual([
			{ media_id: "p6-final", kind: "video" },
		]);
	});
});
