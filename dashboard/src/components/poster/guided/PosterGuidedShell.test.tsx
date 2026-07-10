import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PosterGuidedShell from "./PosterGuidedShell";

const { TEST_PRODUCT, RECIPE } = vi.hoisted(() => ({
	TEST_PRODUCT: {
		id: "prod-1",
		source: "MANUAL",
		raw_product_title: "Minyak Warisan Tok 25ml",
		product_display_name: "Minyak Warisan Tok",
		product_short_name: "Minyak Warisan",
		category: "Traditional",
	},
	RECIPE: {
		recipe_id: "product_hero_night_routine",
		archetype: "PRODUCT_HERO",
		label: "Hero Malam",
		description: "Gaya hero premium",
		allowed_text_density: ["medium"],
	},
}));

// Product picker is stubbed to a single deterministic select action.
vi.mock("../../workspace/SearchableProductSelect", () => ({
	default: ({ onSelect }: { onSelect: (p: unknown) => void }) => (
		<button type="button" data-testid="pick-product" onClick={() => onSelect(TEST_PRODUCT)}>
			pick
		</button>
	),
}));

vi.mock("../../../api/products", () => ({
	fetchProductCatalog: vi.fn().mockResolvedValue({ items: [TEST_PRODUCT] }),
	searchProducts: vi.fn().mockResolvedValue([TEST_PRODUCT]),
}));

vi.mock("../../../api/posterReadiness", () => ({
	fetchPosterReadiness: vi
		.fn()
		.mockResolvedValue({ poster_status: "POSTER_READY", blockers: [], warnings: [] }),
}));

vi.mock("../../../api/posterRecipes", () => ({
	usePosterRecipes: () => ({ recipes: [RECIPE], error: "" }),
}));

vi.mock("../../../api/posterCopySets", () => {
	const dir = (i: number) => ({
		primary_message: `Tajuk ${i}`,
		support_message: `Sokongan ${i}`,
		proof_points: i === 0 ? [] : ["Bukti"],
		cta: `CTA ${i}`,
		disclaimer: "",
		tone: "neutral",
		language: "ms",
		field_provenance: {},
	});
	return {
	recommendPosterObjectives: vi.fn().mockResolvedValue({
		recommendations: [
			{
				archetype: "PRODUCT_HERO",
				recipe_id: "product_hero_night_routine",
				objective: "Perkenalan produk",
				reason: "Sesuai untuk menyerlahkan produk",
				source: "AI",
			},
		],
		warnings: [],
	}),
	recommendPosterAngles: vi.fn().mockResolvedValue({
		angles: [
			{ angle: "Premium hero", rationale: "Serlahkan kualiti", source: "AI" },
			{ angle: "Warisan keluarga", rationale: "Bina kepercayaan", source: "AI" },
		],
		warnings: [],
	}),
	generatePosterDirections: vi.fn().mockResolvedValue({
		directions: [dir(0), dir(1), dir(2)],
		ai_model: "test",
		prompt_version: "v1",
		warnings: [],
	}),
	regeneratePosterField: vi
		.fn()
		.mockResolvedValue({ field: "cta", value: "CTA baharu", provenance: "AI" }),
	createPosterCopySet: vi
		.fn()
		.mockResolvedValue({ poster_copy_set_id: "pcs-1", status: "POSTER_COPY_DRAFT", version: 1 }),
	approvePosterCopySet: vi
		.fn()
		.mockResolvedValue({ poster_copy_set_id: "pcs-1", status: "POSTER_COPY_APPROVED", version: 1 }),
	newPosterCopySetVersion: vi.fn().mockResolvedValue({
		poster_copy_set_id: "pcs-2",
		status: "POSTER_COPY_DRAFT",
		version: 2,
		primary_message: "Tajuk 0",
		support_message: "Sokongan 0",
		proof_points: [],
		cta: "CTA 0",
		disclaimer: "",
		tone: "neutral",
		language: "ms",
	}),
	composePoster: vi.fn().mockResolvedValue({
		deliverable: {
			poster_deliverable_id: "pd-1",
			composition_strategy: "REFERENCE_CONDITIONED",
			poster_copy_set_id: "pcs-1",
		},
		render_report: {},
		qa_report: { ok: true, findings: [], block_count: 0, warn_count: 0 },
	}),
	savePosterToLibrary: vi
		.fn()
		.mockResolvedValue({ creative_asset_id: "ca-1", already_saved: false }),
		posterDeliverableOutputUrl: (id: string) => `/api/poster/deliverables/${id}/output`,
		fetchPosterDeliverableByAsset: vi.fn(),
	};
});

import {
	approvePosterCopySet,
	composePoster,
	createPosterCopySet,
	fetchPosterDeliverableByAsset,
	newPosterCopySetVersion,
	recommendPosterObjectives,
	regeneratePosterField,
	savePosterToLibrary,
} from "../../../api/posterCopySets";

function renderShell(query = "") {
	return render(
		<MemoryRouter initialEntries={[`/creative/poster-builder${query}`]}>
			<Routes>
				<Route path="/creative/poster-builder" element={<PosterGuidedShell />} />
			</Routes>
		</MemoryRouter>,
	);
}

async function driveToApproved() {
	fireEvent.click(screen.getByTestId("pick-product"));
	fireEvent.click(await screen.findByTestId("poster-goal-card-PRODUCT_HERO"));
	fireEvent.click(await screen.findByTestId("poster-angle-card-0"));
	fireEvent.click(await screen.findByTestId("poster-copy-direction-0"));
	fireEvent.click(await screen.findByTestId("poster-guided-continue")); // → approve
	fireEvent.click(await screen.findByTestId("poster-approve-copy"));
	await screen.findByTestId("poster-copy-approved");
}

describe("PosterGuidedShell", () => {
	beforeEach(() => vi.clearAllMocks());
	afterEach(() => cleanup());

	it("shows a clean guided first screen with no engineering jargon", async () => {
		renderShell();
		expect(await screen.findByTestId("poster-guided-shell")).toBeInTheDocument();
		expect(screen.getByTestId("poster-guided-stepper")).toBeInTheDocument();
		expect(screen.getByTestId("pick-product")).toBeInTheDocument();
		// No legacy slot terminology anywhere in the default journey.
		expect(screen.queryByText(/\bHook\b/)).toBeNull();
		expect(screen.queryByText(/Subhook/i)).toBeNull();
		expect(screen.queryByText(/\bUSP\b/)).toBeNull();
		expect(screen.queryByText(/Manual Expert/i)).toBeNull();
	});

	it("walks the full guided journey product → save", async () => {
		renderShell();
		fireEvent.click(screen.getByTestId("pick-product"));
		// Readiness banner is friendly + ready.
		const banner = await screen.findByTestId("poster-readiness-banner");
		await waitFor(() => expect(banner.getAttribute("data-tone")).toBe("ready"));

		// "Cadangkan untuk saya" marks a recommended goal.
		fireEvent.click(screen.getByTestId("poster-goal-recommend"));
		await waitFor(() => expect(recommendPosterObjectives).toHaveBeenCalled());
		expect(await screen.findByText(/Disyorkan/)).toBeInTheDocument();

		fireEvent.click(screen.getByTestId("poster-goal-card-PRODUCT_HERO"));
		fireEvent.click(await screen.findByTestId("poster-angle-card-0"));

		// Three copy directions to compare; pick + edit + regen a field.
		fireEvent.click(await screen.findByTestId("poster-copy-direction-0"));
		const cta = (await screen.findByTestId("poster-field-cta")) as HTMLInputElement;
		expect((screen.getByTestId("poster-field-primary_message") as HTMLInputElement).value).toBe(
			"Tajuk 0",
		);
		fireEvent.change(cta, { target: { value: "CTA edit" } });
		fireEvent.click(screen.getByTestId("poster-regen-cta"));
		await waitFor(() => expect(regeneratePosterField).toHaveBeenCalled());

		fireEvent.click(screen.getByTestId("poster-guided-continue")); // → approve
		fireEvent.click(await screen.findByTestId("poster-approve-copy"));
		await waitFor(() => expect(createPosterCopySet).toHaveBeenCalled());
		await waitFor(() => expect(approvePosterCopySet).toHaveBeenCalled());
		expect(await screen.findByTestId("poster-copy-approved")).toBeInTheDocument();

		// Approve → visual → scene → compose → save.
		fireEvent.click(screen.getByTestId("poster-guided-continue")); // approve → visual
		fireEvent.click(await screen.findByTestId("poster-visual-card-product_hero_night_routine"));
		fireEvent.click(await screen.findByTestId("poster-guided-continue")); // scene → compose
		fireEvent.click(await screen.findByTestId("poster-compose"));
		await waitFor(() => expect(composePoster).toHaveBeenCalled());
		expect(await screen.findByTestId("poster-preview")).toBeInTheDocument();
		expect(screen.getByTestId("poster-qa-passed")).toBeInTheDocument();

		fireEvent.click(screen.getByTestId("poster-guided-continue")); // compose → save
		fireEvent.click(await screen.findByTestId("poster-save"));
		await waitFor(() => expect(savePosterToLibrary).toHaveBeenCalled());
		expect(await screen.findByTestId("poster-saved")).toBeInTheDocument();
	});

	it("editing approved copy creates a new version", async () => {
		renderShell();
		await driveToApproved();
		fireEvent.click(screen.getByTestId("poster-copy-edit-new-version"));
		await waitFor(() => expect(newPosterCopySetVersion).toHaveBeenCalledWith("pcs-1", {}));
		// Back on the copy step, editable again.
		expect(await screen.findByTestId("poster-copy-editor")).toBeInTheDocument();
	});

	it("changing product invalidates downstream steps", async () => {
		renderShell();
		fireEvent.click(screen.getByTestId("pick-product"));
		fireEvent.click(await screen.findByTestId("poster-goal-card-PRODUCT_HERO"));
		await screen.findByTestId("poster-angle-card-0"); // angle reached
		// Re-select the product → downstream (angle) is no longer reachable.
		fireEvent.click(screen.getByTestId("poster-guided-step-product"));
		fireEvent.click(await screen.findByTestId("pick-product"));
		expect((screen.getByTestId("poster-guided-step-angle") as HTMLButtonElement).disabled).toBe(
			true,
		);
	});

	it("reopens a saved poster from the Creative Library", async () => {
		vi.mocked(fetchPosterDeliverableByAsset).mockResolvedValue({
			deliverable: {
				poster_deliverable_id: "pd-9",
				product_id: "prod-1",
				poster_copy_set_id: "pcs-9",
				recipe_id: "product_hero_night_routine",
				template_version: "v1",
				composition_strategy: "REFERENCE_CONDITIONED",
				background_media_id: "m1",
				output_path: "/p.png",
				output_sha256: "abc",
				creative_asset_id: "ca-9",
				status: "POSTER_SAVED",
			},
			render_manifest: {},
			poster_copy_set: {
				poster_copy_set_id: "pcs-9",
				status: "POSTER_COPY_APPROVED",
				primary_message: "Tajuk tersimpan",
			},
			poster_copy_set_status: "POSTER_COPY_APPROVED",
			poster_copy_set_historical: false,
			qa_report: { ok: true, findings: [], block_count: 0, warn_count: 0 },
			output_available: true,
			output_source: "CREATIVE_LIBRARY",
			output_sha256_verified: true,
		} as never);
		renderShell("?reopen_asset=ca-9");
		expect(await screen.findByTestId("poster-guided-reopen")).toBeInTheDocument();
		expect(screen.getByTestId("poster-guided-reopen-source").textContent).toContain(
			"Creative Library",
		);
	});
});
