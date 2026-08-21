import { beforeEach, describe, expect, it } from "vitest";
import {
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
