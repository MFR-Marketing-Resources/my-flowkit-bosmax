import { describe, expect, it } from "vitest";
import { resolveCopyAuthorityRoute } from "./copyAuthorityRouting";

describe("Copy Authority deep-link routing", () => {
	it("returns the normal Landbank for a generic route", () => {
		expect(resolveCopyAuthorityRoute("")).toBe("/creative/storyboard-landbank-v3");
	});

	it("preserves product-only context on the Landbank route", () => {
		expect(resolveCopyAuthorityRoute("?product_id=p1")).toBe(
			"/creative/storyboard-landbank-v3?product_id=p1",
		);
	});

	it("keeps exact product and blueprint context for Authority Detail", () => {
		expect(resolveCopyAuthorityRoute("?product_id=p1&blueprint_id=bp1")).toBe(
			"/creative/copy-authority?product_id=p1&blueprint_id=bp1",
		);
	});
});
