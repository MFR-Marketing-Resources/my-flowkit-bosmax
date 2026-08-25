import { beforeEach, describe, expect, it, vi } from "vitest";
import { CREATIVE_LANE_SETTINGS_UNAVAILABLE } from "../api/creativeLaneSettings";
import {
	collectMontageSessionResults,
	rehydrateMontageRun,
	rememberMontageRunId,
} from "../utils/videoSessionResults";

beforeEach(() => window.sessionStorage.clear());

describe("montage settings SSOT", () => {
	it("does not ship a local full Hook/Background vocabulary fallback", () => {
		// Montage page imports useCreativeLaneSettings — unavailable shell must be empty.
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.hook.options).toEqual([]);
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.background.options).toEqual([]);
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.source).toBe("unavailable");
	});
});

describe("montage session results", () => {
	it("hydrates only the authoritative final video", () => {
		expect(
			collectMontageSessionResults(
				({
					scenes: [
						{ video_media_id: "clip-1" },
						{ video_media_id: "clip-2" },
						{ video_media_id: "clip-1" },
					],
				} as never),
				{ concat: { final_media_id: "montage-final" } },
			),
		).toEqual([
			{ media_id: "montage-final", kind: "video" },
		]);
	});
});

describe("montage durable run hydration", () => {
	it("rehydrates the existing run after reload without submitting", async () => {
		rememberMontageRunId("montage-existing");
		const readRun = vi.fn().mockResolvedValue({ montage_run_id: "montage-existing" });

		await expect(rehydrateMontageRun(readRun)).resolves.toEqual({
			montage_run_id: "montage-existing",
		});
		expect(readRun).toHaveBeenCalledOnce();
		expect(readRun).toHaveBeenCalledWith("montage-existing");
	});
});
