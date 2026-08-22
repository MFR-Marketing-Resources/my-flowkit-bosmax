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

// Task B §1 / Test A — the normal operator navigation must present Copywriting
// Landbank as the single primary copywriting door, and Copy Authority (the V2
// console) must live only under ADVANCED — never as a second normal copy door.
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

	it("presents Copywriting Landbank as the primary copywriting door", () => {
		const copywriting = groupByLabel("COPYWRITING");
		expect(copywriting).toBeDefined();
		expect(copywriting?.items[0]?.label).toBe("Copywriting Landbank");
		expect(copywriting?.items[0]?.to).toBe("/creative/storyboard-landbank-v3");
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

	it("exposes Copy Authority only under the ADVANCED group", () => {
		const authorityDoors = allItems().filter((item) => item.to === "/creative/copy-authority");
		expect(authorityDoors.map((door) => door.group)).toEqual(["ADVANCED"]);
		expect(authorityDoors.map((door) => door.label)).toEqual(["Copy Authority"]);
	});

	it("presents exactly one normal copy-generation door (Landbank), avoiding two doors", () => {
		const landbankDoors = allItems().filter((item) => item.to === "/creative/storyboard-landbank-v3");
		expect(landbankDoors.map((door) => door.group)).toEqual(["COPYWRITING"]);
		// The legacy copy-registry route must never appear as a live nav door.
		expect(allItems().some((item) => item.to === "/creative/copy-registry")).toBe(false);
	});

	// Copy Intelligence declutter — owner decision HIDE_FROM_NAV_KEEP_ROUTE.
	it("removes Copy Intelligence from the normal COPYWRITING navigation", () => {
		const copywriting = groupByLabel("COPYWRITING");
		const labels = (copywriting?.items ?? []).map((item) => item.label);
		expect(labels).not.toContain("Copy Intelligence");
		// Copywriting Landbank stays the single primary door.
		expect(copywriting?.items).toHaveLength(1);
		// The Copy Intelligence surface must not appear as a nav door in ANY group.
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

// Task B §6 / Test H — the old /creative/copy-registry deep link must keep
// working by redirecting to the canonical Copy Authority route, preserving the
// product_id (and any other) query so existing links are never broken.
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
					<Route path="/creative/copy-authority" element={<LandingProbe />} />
				</Routes>
			</MemoryRouter>,
		);
	}

	it("redirects /creative/copy-registry to Copy Authority", async () => {
		renderRedirect("/creative/copy-registry");
		expect(await screen.findByTestId("copy-authority-landing")).toHaveTextContent("search:");
	});

	it("preserves the product_id query on redirect", async () => {
		renderRedirect("/creative/copy-registry?product_id=p1&blueprint_id=bpv2_test");
		expect(await screen.findByTestId("copy-authority-landing")).toHaveTextContent(
			"search:?product_id=p1&blueprint_id=bpv2_test",
		);
	});
});
