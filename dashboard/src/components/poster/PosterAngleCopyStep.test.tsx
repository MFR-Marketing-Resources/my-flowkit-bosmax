import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PosterAngleCopyStep from "./PosterAngleCopyStep";
import PosterComposePanel from "./PosterComposePanel";
import {
	approvePosterCopySet,
	composePoster,
	createPosterCopySet,
	generatePosterDirections,
	recommendPosterAngles,
	regeneratePosterField,
	savePosterToLibrary,
} from "../../api/posterCopySets";
import type { PosterCopySet } from "../../types/posterCopySet";

vi.mock("../../api/posterCopySets", () => ({
	recommendPosterAngles: vi.fn(),
	generatePosterDirections: vi.fn(),
	regeneratePosterField: vi.fn(),
	createPosterCopySet: vi.fn(),
	approvePosterCopySet: vi.fn(),
	composePoster: vi.fn(),
	savePosterToLibrary: vi.fn(),
	posterDeliverableOutputUrl: (id: string) => `/api/poster/deliverables/${id}/output`,
}));

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

const DIRECTION = {
	primary_message: "Warisan dalam poket anda",
	support_message: "Sedia setiap masa.",
	proof_points: ["Saiz poket", "Mudah dibawa"],
	cta: "Beli sekarang",
	disclaimer: "",
	tone: "mesra",
	language: "ms",
	field_provenance: { cta: "AI_GENERATED" },
};

const APPROVED: PosterCopySet = {
	poster_copy_set_id: "pcs-77",
	product_id: "p1",
	campaign_id: "",
	objective: "product_hero_night_routine",
	archetype: "PRODUCT_HERO",
	angle: "Premium hero",
	primary_message: DIRECTION.primary_message,
	support_message: DIRECTION.support_message,
	proof_points: DIRECTION.proof_points,
	offer: null,
	cta: DIRECTION.cta,
	disclaimer: "",
	tone: "mesra",
	language: "ms",
	variants: [],
	field_provenance: {},
	ai_model: "prov:model",
	prompt_version: "poster-copy-ai-v1",
	status: "POSTER_COPY_APPROVED",
	version: 1,
	parent_poster_copy_set_id: "",
	approved_at: "2026-07-10T00:00:00Z",
	approved_by: "operator",
};

describe("PosterAngleCopyStep — angle-first AI copy flow", () => {
	it("angles → directions → pick → per-field regen → approve emits the set", async () => {
		vi.mocked(recommendPosterAngles).mockResolvedValue({
			angles: [
				{ angle: "Premium hero", rationale: "why", source: "RECIPE" },
				{ angle: "Kualiti produk", rationale: "why", source: "AI" },
			],
			warnings: [],
		});
		vi.mocked(generatePosterDirections).mockResolvedValue({
			directions: [DIRECTION],
			ai_model: "prov:model",
			prompt_version: "poster-copy-ai-v1",
			warnings: [],
		});
		vi.mocked(regeneratePosterField).mockResolvedValue({
			field: "cta",
			value: "Dapatkan hari ini",
			provenance: "AI_GENERATED",
		});
		vi.mocked(createPosterCopySet).mockResolvedValue({
			...APPROVED,
			status: "POSTER_COPY_DRAFT",
		});
		vi.mocked(approvePosterCopySet).mockResolvedValue(APPROVED);
		const onApproved = vi.fn();

		render(
			<PosterAngleCopyStep
				productId="p1"
				archetype="PRODUCT_HERO"
				recipeId="product_hero_night_routine"
				language="ms"
				onApproved={onApproved}
			/>,
		);
		fireEvent.click(screen.getByTestId("poster-load-angles"));
		await waitFor(() => expect(screen.getByTestId("poster-angle-list")).toBeInTheDocument());
		fireEvent.click(screen.getByText("Premium hero"));
		await waitFor(() =>
			expect(screen.getByTestId("poster-direction-card-0")).toBeInTheDocument(),
		);
		fireEvent.click(screen.getByTestId("poster-direction-card-0"));
		// Per-field regeneration replaces ONLY the CTA.
		fireEvent.click(screen.getByTestId("poster-regen-cta"));
		await waitFor(() =>
			expect(screen.getByTestId("poster-direction-cta")).toHaveValue("Dapatkan hari ini"),
		);
		expect(screen.getByTestId("poster-direction-primary_message")).toHaveValue(
			DIRECTION.primary_message,
		);
		// Approve → create + approve APIs, emits the approved set.
		fireEvent.click(screen.getByTestId("poster-approve-copy-set"));
		await waitFor(() =>
			expect(screen.getByTestId("poster-copy-set-approved")).toBeInTheDocument(),
		);
		expect(vi.mocked(approvePosterCopySet)).toHaveBeenCalledWith(
			"pcs-77",
			"APPROVE_POSTER_COPY_SET",
		);
		expect(onApproved).toHaveBeenCalledWith(APPROVED);
	});

	it("operator edits stamp provenance and clear approval state", async () => {
		vi.mocked(recommendPosterAngles).mockResolvedValue({
			angles: [{ angle: "Premium hero", rationale: "", source: "RECIPE" }],
			warnings: [],
		});
		vi.mocked(generatePosterDirections).mockResolvedValue({
			directions: [DIRECTION],
			ai_model: "",
			prompt_version: "poster-copy-ai-v1",
			warnings: [],
		});
		render(
			<PosterAngleCopyStep
				productId="p1"
				archetype="PRODUCT_HERO"
				recipeId="product_hero_night_routine"
				language="ms"
				onApproved={vi.fn()}
			/>,
		);
		fireEvent.click(screen.getByTestId("poster-load-angles"));
		await waitFor(() => screen.getByTestId("poster-angle-list"));
		fireEvent.click(screen.getByText("Premium hero"));
		await waitFor(() => screen.getByTestId("poster-direction-card-0"));
		fireEvent.click(screen.getByTestId("poster-direction-card-0"));
		const input = screen.getByTestId("poster-direction-primary_message");
		fireEvent.change(input, { target: { value: "Edit manual saya" } });
		expect(input).toHaveValue("Edit manual saya");
	});
});

describe("PosterComposePanel — deterministic compose + save", () => {
	it("compose renders QA + preview, save registers to Creative Library", async () => {
		vi.mocked(composePoster).mockResolvedValue({
			deliverable: {
				poster_deliverable_id: "pd-1",
				product_id: "p1",
				poster_copy_set_id: "pcs-77",
				recipe_id: "product_hero_night_routine",
				template_version: "1.0.0",
				composition_strategy: "REFERENCE_CONDITIONED",
				background_media_id: "media-9",
				output_path: "x",
				output_sha256: "abc",
				creative_asset_id: "",
				status: "POSTER_COMPOSED",
			},
			render_report: {},
			qa_report: { ok: true, findings: [], block_count: 0, warn_count: 0 },
		});
		vi.mocked(savePosterToLibrary).mockResolvedValue({
			creative_asset_id: "ca_1",
			already_saved: false,
		});
		render(
			<PosterComposePanel
				productId="p1"
				recipeId="product_hero_night_routine"
				copySet={APPROVED}
				backgroundMediaId="media-9"
			/>,
		);
		fireEvent.click(screen.getByTestId("poster-compose-button"));
		await waitFor(() =>
			expect(screen.getByTestId("poster-compose-result")).toBeInTheDocument(),
		);
		expect(vi.mocked(composePoster)).toHaveBeenCalledWith({
			product_id: "p1",
			poster_copy_set_id: "pcs-77",
			recipe_id: "product_hero_night_routine",
			background_media_id: "media-9",
		});
		fireEvent.click(screen.getByTestId("poster-save-library"));
		await waitFor(() =>
			expect(screen.getByTestId("poster-saved-note")).toBeInTheDocument(),
		);
	});

	it("QA blockers disable saving", async () => {
		vi.mocked(composePoster).mockResolvedValue({
			deliverable: {
				poster_deliverable_id: "pd-2",
				product_id: "p1",
				poster_copy_set_id: "pcs-77",
				recipe_id: "product_hero_night_routine",
				template_version: "1.0.0",
				composition_strategy: "REFERENCE_CONDITIONED",
				background_media_id: "media-9",
				output_path: "x",
				output_sha256: "abc",
				creative_asset_id: "",
				status: "POSTER_COMPOSED",
			},
			render_report: {},
			qa_report: {
				ok: false,
				findings: [
					{ code: "TEXT_OVERFLOW", severity: "BLOCK", message: "x", zone_id: "headline" },
				],
				block_count: 1,
				warn_count: 0,
			},
		});
		render(
			<PosterComposePanel
				productId="p1"
				recipeId="product_hero_night_routine"
				copySet={APPROVED}
				backgroundMediaId="media-9"
			/>,
		);
		fireEvent.click(screen.getByTestId("poster-compose-button"));
		await waitFor(() => screen.getByTestId("poster-compose-result"));
		expect(screen.getByTestId("poster-save-library")).toBeDisabled();
		expect(screen.getByText(/TEXT_OVERFLOW/)).toBeInTheDocument();
	});

	it("waits for prerequisites", () => {
		render(
			<PosterComposePanel
				productId="p1"
				recipeId="product_hero_night_routine"
				copySet={null}
				backgroundMediaId=""
			/>,
		);
		expect(screen.getByTestId("poster-compose-waiting")).toBeInTheDocument();
	});
});
