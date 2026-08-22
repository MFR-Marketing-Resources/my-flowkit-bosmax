import { describe, expect, it } from "vitest";

import {
	ACTIVE_VIDEO_SURFACE_LABELS,
	normalizeVideoSurfaceLane,
	surfaceDisplayLabel,
} from "./videoSurfaceProvenance";

describe("video surface provenance", () => {
	it("exposes only the four active production surfaces", () => {
		expect(Object.values(ACTIVE_VIDEO_SURFACE_LABELS)).toEqual([
			"Hybrid",
			"Faceless Video",
			"Montage",
			"Production Studio / P6",
		]);
		expect(normalizeVideoSurfaceLane("F2V")).toBeNull();
		expect(normalizeVideoSurfaceLane("Native Extend")).toBeNull();
	});

	it("keeps active surface separate from transport mode", () => {
		expect(surfaceDisplayLabel("HYBRID", "F2V", "F2V")).toBe("Hybrid");
		expect(surfaceDisplayLabel("MONTAGE", "F2V", "F2V")).toBe("Montage");
		expect(surfaceDisplayLabel("P6", "MONTAGE")).toBe("Production Studio / P6");
	});

	it("does not dishonestly remap untyped historical rows", () => {
		expect(surfaceDisplayLabel(null, "F2V")).toBe("Legacy/Internal");
		expect(surfaceDisplayLabel(null)).toBe("Unknown Surface");
	});
});
