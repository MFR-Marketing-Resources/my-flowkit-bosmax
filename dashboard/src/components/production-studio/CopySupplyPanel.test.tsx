import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchV3ProductionCapacity = vi.fn();
const buildV3ProductionManifest = vi.fn();
const freezeV3ProductionManifest = vi.fn();
const fetchV3ProductionManifest = vi.fn();
const materializeV3Projection = vi.fn();
const materializeV3ProjectionsBulk = vi.fn();
const planV3Assistant = vi.fn();
const executeV3Assistant = vi.fn();

vi.mock("../../api/storyboardLandbankV3Round2", () => ({
	fetchV3ProductionCapacity: (...args: unknown[]) =>
		fetchV3ProductionCapacity(...args),
	buildV3ProductionManifest: (...args: unknown[]) =>
		buildV3ProductionManifest(...args),
	freezeV3ProductionManifest: (...args: unknown[]) =>
		freezeV3ProductionManifest(...args),
	fetchV3ProductionManifest: (...args: unknown[]) =>
		fetchV3ProductionManifest(...args),
	// Present only so the render-time "no generation" assertion is meaningful.
	materializeV3Projection: (...args: unknown[]) =>
		materializeV3Projection(...args),
	materializeV3ProjectionsBulk: (...args: unknown[]) =>
		materializeV3ProjectionsBulk(...args),
	planV3Assistant: (...args: unknown[]) => planV3Assistant(...args),
	executeV3Assistant: (...args: unknown[]) => executeV3Assistant(...args),
}));

import CopySupplyPanel from "./CopySupplyPanel";

const CAPACITY = {
	product_id: "product-a",
	semantic_capacity: 12,
	projection_capacity: 9,
	executable_copy_capacity: 3,
	production_capacity: 3,
	stale_copy_count: 2,
	production_capacity_note: "Not a Cartesian guarantee.",
};

const MANIFEST = {
	manifest: {
		manifest_id: "manifest-1",
		revision: 1,
		status: "DRAFT",
		item_count: 3,
		valid_item_count: 2,
		blocked_item_count: 1,
		manifest_digest: "digest-abc",
	},
	items: [],
	selected_count: 3,
	valid_count: 2,
	blocked_count: 1,
	blocked: [
		{ projection_id: "proj-9", reason: "STALE_COPY: projection out of date" },
	],
	shortfall: 7,
	reuse_policy: "NO_REUSE",
};

const PRODUCTS = [{ id: "product-a", name: "P6 Product A", target: 10 }];

beforeEach(() => {
	fetchV3ProductionCapacity.mockResolvedValue(CAPACITY);
	buildV3ProductionManifest.mockResolvedValue(MANIFEST);
	freezeV3ProductionManifest.mockResolvedValue({
		manifest: { ...MANIFEST.manifest, status: "FROZEN" },
	});
});

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe("CopySupplyPanel", () => {
	it("renders the four-tier capacity from a mocked capacity response", async () => {
		render(<CopySupplyPanel products={PRODUCTS} defaultDurationSeconds={8} />);

		await waitFor(() =>
			expect(screen.getByTestId("copy-supply-tier-semantic")).toHaveTextContent(
				"12",
			),
		);
		expect(screen.getByTestId("copy-supply-tier-projection")).toHaveTextContent(
			"9",
		);
		expect(screen.getByTestId("copy-supply-tier-executable")).toHaveTextContent(
			"3",
		);
		expect(screen.getByTestId("copy-supply-tier-production")).toHaveTextContent(
			"3",
		);
		expect(screen.getByTestId("copy-supply-tier-stale")).toHaveTextContent("2");
		expect(screen.getByTestId("copy-supply-capacity-note")).toHaveTextContent(
			"Not a Cartesian guarantee.",
		);
		expect(fetchV3ProductionCapacity).toHaveBeenCalledWith("product-a");
	});

	it("builds a manifest and renders selected/valid/blocked counts + reasons", async () => {
		render(<CopySupplyPanel products={PRODUCTS} defaultDurationSeconds={8} />);

		// The build control is disabled while capacity is loading; wait for it.
		await waitFor(() =>
			expect(screen.getByTestId("copy-supply-build-manifest")).toBeEnabled(),
		);
		fireEvent.click(screen.getByTestId("copy-supply-build-manifest"));

		await waitFor(() =>
			expect(buildV3ProductionManifest).toHaveBeenCalledTimes(1),
		);
		expect(buildV3ProductionManifest).toHaveBeenCalledWith(
			expect.objectContaining({
				productId: "product-a",
				requestedCapacity: 10,
				durationSeconds: 8,
			}),
		);

		expect(
			await screen.findByTestId("copy-supply-selected-count"),
		).toHaveTextContent("3");
		expect(screen.getByTestId("copy-supply-blocked-count")).toHaveTextContent(
			"1",
		);
		expect(
			screen.getByTestId("copy-supply-blocked-reasons"),
		).toHaveTextContent("STALE_COPY");
		expect(screen.getByTestId("copy-supply-manifest-status")).toHaveTextContent(
			"DRAFT",
		);
	});

	it("shows shortfall + Fill Capacity when target exceeds executable, and triggers no generation on render", async () => {
		render(<CopySupplyPanel products={PRODUCTS} defaultDurationSeconds={8} />);

		// target defaults to the page target (10); executable is 3 -> shortfall 7.
		await waitFor(() =>
			expect(screen.getByTestId("copy-supply-shortfall")).toHaveTextContent(
				"7",
			),
		);

		const fill = await screen.findByTestId("copy-supply-fill-capacity");
		const href = fill.getAttribute("href") ?? "";
		expect(href).toContain("product_id=product-a");
		expect(href).toContain("mode=FILL_CAPACITY");
		expect(href).toContain("needed=7");

		// Fill Capacity is a route only — nothing is generated, approved, or
		// materialized by rendering the panel or surfacing the affordance.
		expect(materializeV3Projection).not.toHaveBeenCalled();
		expect(materializeV3ProjectionsBulk).not.toHaveBeenCalled();
		expect(planV3Assistant).not.toHaveBeenCalled();
		expect(executeV3Assistant).not.toHaveBeenCalled();
		expect(buildV3ProductionManifest).not.toHaveBeenCalled();
	});
});
