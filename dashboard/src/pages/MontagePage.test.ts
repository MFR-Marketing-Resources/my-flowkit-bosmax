import { describe, expect, it } from "vitest";
import { CREATIVE_LANE_SETTINGS_UNAVAILABLE } from "../api/creativeLaneSettings";
import { collectMontageSessionResults } from "../utils/videoSessionResults";

describe("montage settings SSOT", () => {
	it("does not ship a local full Hook/Background vocabulary fallback", () => {
		// Montage page imports useCreativeLaneSettings — unavailable shell must be empty.
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.hook.options).toEqual([]);
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.background.options).toEqual([]);
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.source).toBe("unavailable");
	});
});

describe("montage session results", () => {
	it("hydrates the final and scene videos once each", () => {
		expect(
			collectMontageSessionResults(
				{
					scenes: [
						{ video_media_id: "clip-1" },
						{ video_media_id: "clip-2" },
						{ video_media_id: "clip-1" },
					],
				},
				{ concat: { final_media_id: "montage-final" } },
			),
		).toEqual([
			{ media_id: "montage-final", kind: "video" },
			{ media_id: "clip-1", kind: "video" },
			{ media_id: "clip-2", kind: "video" },
		]);
	});
});
