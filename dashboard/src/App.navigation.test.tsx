import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { NAV_GROUPS, CopyRegistryRedirect } from "./App";
import {
	DEACTIVATED_SURFACE_REDIRECTS,
	isDeactivatedSurfacePath,
} from "./deactivatedSurfaces";

afterEach(cleanup);

function groupByLabel(label: string) {
	return NAV_GROUPS.find((group) => group.label === label);
}

function allItems() {
	return NAV_GROUPS.flatMap((group) => group.items.map((item) => ({ group: group.label, ...item })));
}

// Round 3: the Copywriting Landbank authoring door is hidden from the live nav
// (HIDE_FROM_NAV_KEEP_ROUTE) while its route stays live for Copy Supply deep-links.
// Copy Authority is a deep-link-only V2 detail route; cross-product governance is
// owned by the queue.
describe("Task B — navigation surface (Test A)", () => {
	it("exposes only active production video surfaces in the live nav", () => {
		const video = groupByLabel("VIDEO PRODUCTION");
		expect(video?.items.map((item) => item.label)).toEqual([
			"Hybrid",
			"Faceless Video",
			"Montage",
			"Production Studio",
		]);
		expect(video?.items.map((item) => item.to)).toEqual([
			"/operator/hybrid",
			"/operator/faceless",
			"/operator/montage",
			"/production-studio",
		]);
	});

	it("does not expose dormant transport modes as production nav labels", () => {
		const labels = allItems().map((item) => item.label);
		expect(labels).not.toContain("Text to Video");
		expect(labels).not.toContain("Frames");
		expect(labels).not.toContain("Ingredients");
		expect(allItems().some((item) => item.to === "/operator/t2v")).toBe(false);
		expect(allItems().some((item) => item.to === "/operator/f2v")).toBe(false);
		expect(allItems().some((item) => item.to === "/operator/i2v")).toBe(false);
	});

	it("hides the Copywriting Landbank authoring door from the live nav (HIDE_FROM_NAV_KEEP_ROUTE)", () => {
		// Round 3: FAST54 / Storyboard V3 authoring leaves the sidebar but the route
		// stays live — it must NOT enter the deactivated-surface redirect map, so
		// Production Studio's Copy Supply deep-links keep resolving to the real page.
		expect(groupByLabel("COPYWRITING")).toBeUndefined();
		expect(allItems().some((item) => item.to === "/creative/storyboard-landbank-v3")).toBe(false);
		expect(allItems().some((item) => item.label === "Copywriting Landbank")).toBe(false);
		expect(isDeactivatedSurfacePath("/creative/storyboard-landbank-v3")).toBe(false);
		expect(Object.keys(DEACTIVATED_SURFACE_REDIRECTS)).not.toContain(
			"/creative/storyboard-landbank-v3",
		);
	});

	it("does not place a V2 copy authority door beside Landbank in the normal group", () => {
		const copywriting = groupByLabel("COPYWRITING");
		const labels = (copywriting?.items ?? []).map((item) => item.label);
		expect(labels).not.toContain("Copy Register");
		expect(labels).not.toContain("Copy Authority");
		const targets = (copywriting?.items ?? []).map((item) => item.to);
		expect(targets).not.toContain("/creative/copy-authority");
		expect(targets).not.toContain("/creative/copy-registry");
	});

	it("keeps Copy Authority out of navigation and exposes the Governance Queue", () => {
		const authorityDoors = allItems().filter((item) => item.to === "/creative/copy-authority");
		expect(authorityDoors).toEqual([]);
		const queueDoors = allItems().filter((item) => item.to === "/creative/copy-review-queue");
		expect(queueDoors.map((door) => door.group)).toEqual(["ADVANCED"]);
		expect(queueDoors.map((door) => door.label)).toEqual(["Copy Governance Queue"]);
	});

	it("keeps copy-generation authoring doors out of the live nav (Landbank + legacy registry)", () => {
		// Round 3: the Landbank authoring door is hidden (HIDE_FROM_NAV_KEEP_ROUTE),
		// so no storyboard-landbank-v3 nav door remains.
		expect(allItems().some((item) => item.to === "/creative/storyboard-landbank-v3")).toBe(false);
		// The legacy copy-registry route must never appear as a live nav door.
		expect(allItems().some((item) => item.to === "/creative/copy-registry")).toBe(false);
	});

	// Copy Intelligence declutter — owner decision HIDE_FROM_NAV_KEEP_ROUTE.
	it("removes Copy Intelligence from the live navigation", () => {
		// The Copy Intelligence surface must not appear as a nav door in ANY group.
		expect(allItems().some((item) => item.label === "Copy Intelligence")).toBe(false);
		expect(allItems().some((item) => item.to === "/creative/copy-intelligence")).toBe(false);
	});

	it("keeps /creative/copy-intelligence reachable — declutter is nav-only, not a redirect", () => {
		// HIDE_FROM_NAV_KEEP_ROUTE: the surface leaves the sidebar but the route
		// stays live, so it must NOT enter the deactivated-surface redirect map.
		expect(isDeactivatedSurfacePath("/creative/copy-intelligence")).toBe(false);
		expect(Object.keys(DEACTIVATED_SURFACE_REDIRECTS)).not.toContain(
			"/creative/copy-intelligence",
		);
	});
});

// Legacy routes preserve exact authority links only when both product_id and
// blueprint_id are present; otherwise they return to the normal Landbank.
describe("Task B — legacy route compatibility (Test H)", () => {
	function LandingProbe() {
		const location = useLocation();
		return <div data-testid="copy-authority-landing">{`search:${location.search}`}</div>;
	}

	function renderRedirect(entry: string) {
		return render(
			<MemoryRouter initialEntries={[entry]}>
				<Routes>
					<Route path="/creative/copy-registry" element={<CopyRegistryRedirect />} />
					<Route path="/creative/storyboard-landbank-v3" element={<LandingProbe />} />
				</Routes>
			</MemoryRouter>,
		);
	}

	it("redirects /creative/copy-registry to Copywriting Landbank", async () => {
		renderRedirect("/creative/copy-registry");
		expect(await screen.findByTestId("copy-authority-landing")).toHaveTextContent("search:");
	});

	it("preserves product-only context on the Landbank redirect", async () => {
		renderRedirect("/creative/copy-registry?product_id=p1");
		expect(await screen.findByTestId("copy-authority-landing")).toHaveTextContent(
			"search:?product_id=p1",
		);
	});
});
