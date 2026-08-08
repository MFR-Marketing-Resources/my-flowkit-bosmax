import { describe, expect, it } from "vitest";
import { CREATIVE_LANE_SETTINGS_UNAVAILABLE } from "../api/creativeLaneSettings";
import {
	FACELESS_CHARACTER_PRESENCE,
	FACELESS_SOURCE_MODE,
	FACELESS_TRANSPORT_MODE,
	facelessPrepareBlockers,
	facelessProductBlocker,
	facelessStartFrameBlocker,
	optionLabel,
} from "./facelessLane";

describe("facelessLane", () => {
	it("uses F2V/FRAMES transport with faceless presence", () => {
		expect(FACELESS_TRANSPORT_MODE).toBe("F2V");
		expect(FACELESS_SOURCE_MODE).toBe("FRAMES");
		expect(FACELESS_CHARACTER_PRESENCE).toBe("FACELESS");
	});

	it("fails closed without product or start frame", () => {
		expect(facelessProductBlocker(null)).toMatch(/product/i);
		expect(facelessStartFrameBlocker("")).toMatch(/start frame/i);
		expect(
			facelessPrepareBlockers({ productId: null, startFrameAssetId: null }),
		).toHaveLength(2);
		expect(
			facelessPrepareBlockers({
				productId: "p1",
				startFrameAssetId: "asset-1",
			}),
		).toEqual([]);
	});

	it("frontend settings shell is fail-closed empty (no second SSOT vocab)", () => {
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.source).toBe("unavailable");
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.hook.options).toEqual([]);
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.background.options).toEqual([]);
		// Must NOT mirror full owner vocabulary
		const labels = CREATIVE_LANE_SETTINGS_UNAVAILABLE.hook.options.map((o) => o.label);
		expect(labels).not.toContain("Penat Kejar Promo");
		expect(labels).not.toContain("Nangis Mak-Mak");
		expect(optionLabel([], "AUTO")).toBe("AUTO");
	});
});
