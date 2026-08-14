import { describe, expect, it } from "vitest";
import {
	DEACTIVATED_SURFACE_REDIRECTS,
	isDeactivatedSurfacePath,
	resolveActiveSurfacePath,
} from "./deactivatedSurfaces";

describe("deactivated dashboard surfaces", () => {
	it("keeps the six owner-deactivated pages behind active surface redirects", () => {
		expect(DEACTIVATED_SURFACE_REDIRECTS).toEqual({
			"/operator/t2v": "/operator/hybrid",
			"/operator/f2v": "/operator/hybrid",
			"/operator/i2v": "/operator/hybrid",
			"/operator/img": "/creative/poster-builder",
			"/assets/img-cockpit": "/creative/poster-builder",
			"/assets/img-fastlane": "/creative/poster-builder",
		});
	});

	it("leaves active surfaces unchanged", () => {
		expect(isDeactivatedSurfacePath("/operator/hybrid")).toBe(false);
		expect(resolveActiveSurfacePath("/operator/hybrid")).toBe("/operator/hybrid");
		expect(resolveActiveSurfacePath("/operator/t2v")).toBe("/operator/hybrid");
		expect(resolveActiveSurfacePath("/operator/img")).toBe(
			"/creative/poster-builder",
		);
	});
});
