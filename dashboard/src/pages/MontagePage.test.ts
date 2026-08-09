import { describe, expect, it } from "vitest";
import { CREATIVE_LANE_SETTINGS_UNAVAILABLE } from "../api/creativeLaneSettings";

describe("montage settings SSOT", () => {
	it("does not ship a local full Hook/Background vocabulary fallback", () => {
		// Montage page imports useCreativeLaneSettings — unavailable shell must be empty.
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.hook.options).toEqual([]);
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.background.options).toEqual([]);
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.source).toBe("unavailable");
	});
});
