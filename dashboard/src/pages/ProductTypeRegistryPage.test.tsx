import "@testing-library/jest-dom/vitest";
import {
	act,
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
	within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import appSource from "../App.tsx?raw";
import {
	fetchCatalogAuthorityReport,
	fetchProductStrategyTypeRegistry,
	fetchProductTypeCopyEligibleReport,
	registerProductStrategyType,
} from "../api/products";
import type {
	CatalogAuthorityReport,
	ProductStrategyTypeRegistryResponse,
	ProductTypeCopyEligibleReport,
} from "../types";
import ProductTypeRegistryPage from "./ProductTypeRegistryPage";

vi.mock("../api/products", () => ({
	fetchCatalogAuthorityReport: vi.fn(),
	fetchProductStrategyTypeRegistry: vi.fn(),
	fetchProductTypeCopyEligibleReport: vi.fn(),
	registerProductStrategyType: vi.fn(),
}));

const REGISTRY: ProductStrategyTypeRegistryResponse = {
	items: [
		{
			cluster: "beauty_makeup",
			product_type_group: "lipstick_lip_tint",
			display_name: "Lipstick Lip Tint",
			matched_scene_strategy_id: "LIP_COLOR",
			scene_coverage_status: "COVERED",
			registry_status: "ACTIVE",
			auto_classification_enabled: true,
			authority_source: "SYSTEM_SEED",
			created_at: "2026-07-28T16:02:56Z",
			updated_at: "2026-07-28T16:02:56Z",
		},
		{
			cluster: "beauty_makeup",
			product_type_group: "eyeliner",
			display_name: "Eyeliner",
			matched_scene_strategy_id: "GENERIC_FALLBACK",
			scene_coverage_status: "FALLBACK_ONLY",
			registry_status: "REVIEW_REQUIRED",
			auto_classification_enabled: true,
			authority_source: "SYSTEM_SEED",
			created_at: "2026-07-28T16:02:56Z",
			updated_at: "2026-07-28T16:02:56Z",
		},
		{
			cluster: "food_cooking",
			product_type_group: "rempah_seasoning",
			display_name: "Rempah Seasoning",
			matched_scene_strategy_id: "SPICE_SEASONING",
			scene_coverage_status: "COVERED",
			registry_status: "ACTIVE",
			auto_classification_enabled: true,
			authority_source: "SYSTEM_SEED",
			created_at: "2026-07-28T16:02:56Z",
			updated_at: "2026-07-28T16:02:56Z",
		},
	],
	clusters: ["beauty_makeup", "food_cooking", "generic_unclassified"],
	scene_strategy_ids: ["GENERIC_FALLBACK", "LIP_COLOR", "SPICE_SEASONING"],
};

const EMPTY_REGISTRY: ProductStrategyTypeRegistryResponse = {
	items: [],
	clusters: [],
	scene_strategy_ids: [],
};

const P4_REPORT: ProductTypeCopyEligibleReport = {
	total_products: 659,
	eligible_count: 11,
	blocked_count: 648,
	eligible_by_product_type: [
		{
			cluster: "beauty_makeup",
			product_type_group: "lipstick_lip_tint",
			scene_strategy_id: "LIP_COLOR",
			count: 9,
		},
		{
			cluster: "food_cooking",
			product_type_group: "rempah_seasoning",
			scene_strategy_id: "SPICE_SEASONING",
			count: 2,
		},
	],
	blocked_by_reason: { TAXONOMY_NOT_VERIFIED: 648 },
	missing_copy_strategy_groups: [
		{
			cluster: "beauty_makeup",
			product_type_group: "eyeliner",
			scene_strategy_id: "GENERIC_FALLBACK",
			count: 4,
		},
	],
	sample_eligible: [
		{
			product_id: "product-lip-1",
			product_name: "Velvet Lip Tint",
			cluster: "beauty_makeup",
			product_type_group: "lipstick_lip_tint",
			scene_strategy_id: "LIP_COLOR",
			blocked_reasons: [],
		},
	],
	sample_blocked: [],
};

const AUTHORITY_REPORT: CatalogAuthorityReport = {
	report_version: "p5.8_final_catalog_authority_v1",
	total_products: 659,
	active_products: 443,
	archived_products: 216,
	product_truth_mapped_count: 628,
	p4_supported_count: 640,
	unknown_product_type_count: 14,
	unknown_product_type_p4_supported_count: 0,
	terminal_state_counts: {
		P6_READY: 438,
		REVIEW_BLOCKED_WITH_EXACT_REASON: 2,
		INSUFFICIENT_PRODUCT_TRUTH: 3,
		ARCHIVED_NOT_IN_SCOPE: 216,
	},
	p6_launch_cohort_count: 438,
	p6_launch_cohort_product_ids: ["product-ready-1"],
	blocked_by_reason: {
		UNVERIFIED_ELECTRICITY_SAVINGS_CLAIM: 1,
	},
	coverage_groups: [],
	products: [
		{
			product_id: "product-blocked-1",
			product_name: "Power Saver Device",
			lifecycle_status: "ACTIVE",
			source_category: "Home Improvement",
			source_subcategory: "Electrical Equipment & Supplies",
			source_product_type: "Power Savers",
			product_truth_mapped: true,
			cluster: "home_electrical",
			product_type_group: "power_saver_device",
			scene_strategy_id: "ELECTRICAL_DEVICE",
			registry_status: "ACTIVE",
			review_status: "REVIEW_REQUIRED",
			consumer_status: "BLOCKED_REVIEW_REQUIRED",
			scene_coverage_status: "COVERED",
			taxonomy_stale: false,
			fallback_used: false,
			specific_strategy: true,
			p4_support_status: "P4_SUPPORTED",
			p6_launch_cohort: false,
			blockers: ["TAXONOMY_NOT_VERIFIED"],
			mapping_provenance: "SOURCE_TAXONOMY",
			mapping_reviewer_id: "owner-mission:P5.8",
			mapping_reviewer_note: "P5.8 reviewed mapping.",
			taxonomy_reviewer_id: null,
			taxonomy_reviewed_at: null,
			terminal_state: "REVIEW_BLOCKED_WITH_EXACT_REASON",
			terminal_reasons: [
				"UNVERIFIED_ELECTRICITY_SAVINGS_CLAIM",
				"ELECTRICAL_SAFETY_REVIEW_REQUIRED",
			],
		},
	],
	matrix_sha256:
		"a467357037d44c54be040fc09d0940795849916785fa4ffada05688cd80b7053",
};

const mockedFetchAuthority = vi.mocked(fetchCatalogAuthorityReport);
const mockedFetchRegistry = vi.mocked(fetchProductStrategyTypeRegistry);
const mockedFetchCopyReport = vi.mocked(fetchProductTypeCopyEligibleReport);
const mockedRegister = vi.mocked(registerProductStrategyType);

function renderPage() {
	return render(
		<MemoryRouter>
			<ProductTypeRegistryPage />
		</MemoryRouter>,
	);
}

function fillRequiredRegistrationFields() {
	fireEvent.change(screen.getByLabelText("Product type group"), {
		target: { value: "custom_palette" },
	});
	fireEvent.change(screen.getByLabelText("Display name"), {
		target: { value: "Custom Palette" },
	});
	fireEvent.change(screen.getByLabelText("Reviewer ID"), {
		target: { value: "operator-1" },
	});
	fireEvent.change(screen.getByLabelText("Reviewer note"), {
		target: { value: "Reviewed binding." },
	});
}

describe("ProductTypeRegistryPage", () => {
	beforeEach(() => {
		mockedFetchAuthority.mockReset();
		mockedFetchRegistry.mockReset();
		mockedFetchCopyReport.mockReset();
		mockedRegister.mockReset();
		mockedFetchAuthority.mockResolvedValue(AUTHORITY_REPORT);
		mockedFetchRegistry.mockResolvedValue(REGISTRY);
		mockedFetchCopyReport.mockResolvedValue(P4_REPORT);
	});

	afterEach(cleanup);

	it("renders grouped rows with bounded P4 support and affected-product guidance", async () => {
		renderPage();
		const lipRow = await screen.findByTestId("registry-row-lipstick_lip_tint");
		expect(screen.getByTestId("registry-cluster-beauty_makeup")).toBeVisible();
		expect(screen.getByTestId("registry-cluster-food_cooking")).toBeVisible();
		expect(within(lipRow).getByText("P4 supported")).toBeVisible();
		expect(within(lipRow).getByText("9 eligible products")).toBeVisible();
		expect(
			within(lipRow).getByRole("link", { name: "Open eligible sample" }),
		).toHaveAttribute(
			"href",
			"/products?product=product-lip-1&tab=INTELLIGENCE",
		);
		const eyelinerRow = screen.getByTestId("registry-row-eyeliner");
		expect(
			within(eyelinerRow).getByText("P4 strategy not registered"),
		).toBeVisible();
		expect(
			within(eyelinerRow).getByText("4 blocked by missing strategy"),
		).toBeVisible();
	});

	it("renders the 659-product terminal-state authority and exact blockers", async () => {
		renderPage();
		const summary = await screen.findByTestId("catalog-authority-summary");
		expect(within(summary).getByText("659")).toBeVisible();
		expect(within(summary).getByText("438")).toBeVisible();
		expect(within(summary).getByText("2")).toBeVisible();
		expect(within(summary).getByText("3")).toBeVisible();
		expect(within(summary).getByText("216")).toBeVisible();
		const blocked = screen.getByTestId("terminal-product-product-blocked-1");
		expect(
			within(blocked).getByText("REVIEW_BLOCKED_WITH_EXACT_REASON"),
		).toBeVisible();
		expect(within(blocked).getByText("SOURCE_TAXONOMY")).toBeVisible();
		expect(blocked).toHaveTextContent("UNVERIFIED_ELECTRICITY_SAVINGS_CLAIM");
		expect(blocked).toHaveTextContent("ELECTRICAL_SAFETY_REVIEW_REQUIRED");
	});

	it("searches and filters by every requested registry dimension", async () => {
		renderPage();
		await screen.findByTestId("registry-row-lipstick_lip_tint");
		fireEvent.change(screen.getByLabelText("Search product types"), {
			target: { value: "rempah" },
		});
		expect(screen.getByTestId("registry-row-rempah_seasoning")).toBeVisible();
		expect(
			screen.queryByTestId("registry-row-lipstick_lip_tint"),
		).not.toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
		fireEvent.change(screen.getByLabelText("Filter by cluster"), {
			target: { value: "beauty_makeup" },
		});
		fireEvent.change(screen.getByLabelText("Filter by registry status"), {
			target: { value: "REVIEW_REQUIRED" },
		});
		expect(screen.getByTestId("registry-row-eyeliner")).toBeVisible();
		expect(
			screen.queryByTestId("registry-row-lipstick_lip_tint"),
		).not.toBeInTheDocument();

		fireEvent.change(screen.getByLabelText("Filter by coverage status"), {
			target: { value: "COVERED" },
		});
		expect(screen.getByTestId("registry-filter-empty-state")).toBeVisible();

		fireEvent.click(
			within(screen.getByTestId("registry-filter-empty-state")).getByRole(
				"button",
				{ name: "Clear filters" },
			),
		);
		fireEvent.change(screen.getByLabelText("Filter by scene strategy"), {
			target: { value: "SPICE_SEASONING" },
		});
		expect(screen.getByTestId("registry-row-rempah_seasoning")).toBeVisible();
		expect(screen.getByTestId("filtered-row-count")).toHaveTextContent(
			"Showing 1 of 3 rows",
		);
	});

	it("shows loading and empty states while P4 failure stays non-blocking", async () => {
		let resolveRegistry:
			| ((value: ProductStrategyTypeRegistryResponse) => void)
			| undefined;
		mockedFetchRegistry.mockReturnValue(
			new Promise((resolve) => {
				resolveRegistry = resolve;
			}),
		);
		mockedFetchCopyReport.mockRejectedValue(new Error("P4 route unavailable"));
		renderPage();
		expect(screen.getByTestId("registry-loading-state")).toBeVisible();

		await act(async () => {
			resolveRegistry?.(EMPTY_REGISTRY);
		});
		expect(await screen.findByTestId("registry-empty-state")).toBeVisible();
		expect(screen.getByTestId("p4-report-warning")).toHaveTextContent(
			"P4 route unavailable",
		);
	});

	it("registers through the official API and refreshes the registry", async () => {
		const created = {
			cluster: "beauty_makeup",
			product_type_group: "custom_palette",
			display_name: "Custom Palette",
			matched_scene_strategy_id: "LIP_COLOR",
			scene_coverage_status: "COVERED" as const,
			registry_status: "ACTIVE" as const,
			auto_classification_enabled: false,
			authority_source: "MANUAL_REGISTRATION" as const,
			reviewer_id: "operator-1",
			reviewer_note: "Reviewed binding.",
			reviewed_at: "2026-07-29T00:00:00Z",
			created_at: "2026-07-29T00:00:00Z",
			updated_at: "2026-07-29T00:00:00Z",
		};
		mockedRegister.mockResolvedValue(created);
		mockedFetchRegistry.mockResolvedValueOnce(REGISTRY).mockResolvedValueOnce({
			...REGISTRY,
			items: [...REGISTRY.items, created],
		});
		renderPage();
		await screen.findByTestId("registry-row-lipstick_lip_tint");
		fillRequiredRegistrationFields();
		fireEvent.click(
			screen.getByRole("button", { name: "Register product type" }),
		);

		await waitFor(() =>
			expect(mockedRegister).toHaveBeenCalledWith({
				cluster: "beauty_makeup",
				product_type_group: "custom_palette",
				display_name: "Custom Palette",
				matched_scene_strategy_id: "LIP_COLOR",
				scene_coverage_status: "COVERED",
				registry_status: "ACTIVE",
				auto_classification_enabled: false,
				reviewer_id: "operator-1",
				reviewer_note: "Reviewed binding.",
			}),
		);
		expect(await screen.findByTestId("registration-success")).toHaveTextContent(
			"Registered beauty_makeup / custom_palette as ACTIVE.",
		);
		expect(mockedFetchRegistry).toHaveBeenCalledTimes(2);
		expect(
			await screen.findByTestId("registry-row-custom_palette"),
		).toBeVisible();
	});

	it("surfaces official API registration errors without refreshing", async () => {
		mockedRegister.mockRejectedValue(
			new Error("PRODUCT_STRATEGY_TYPE_ALREADY_REGISTERED"),
		);
		renderPage();
		await screen.findByTestId("registry-row-lipstick_lip_tint");
		fillRequiredRegistrationFields();
		fireEvent.click(
			screen.getByRole("button", { name: "Register product type" }),
		);
		expect(await screen.findByTestId("registration-error")).toHaveTextContent(
			"PRODUCT_STRATEGY_TYPE_ALREADY_REGISTERED",
		);
		expect(mockedFetchRegistry).toHaveBeenCalledTimes(1);
	});

	it("renders a retryable registry error state", async () => {
		mockedFetchRegistry.mockRejectedValue(new Error("Registry offline"));
		renderPage();
		expect(await screen.findByTestId("registry-error-state")).toHaveTextContent(
			"Registry offline",
		);
		expect(
			screen.getByRole("button", { name: "Retry registry load" }),
		).toBeVisible();
	});
});

describe("Product Type Registry navigation contract", () => {
	it("registers the dedicated Assets navigation item and route", () => {
		expect(appSource).toContain(
			'import ProductTypeRegistryPage from "./pages/ProductTypeRegistryPage"',
		);
		expect(appSource).toContain('to: "/assets/product-type-registry"');
		expect(appSource).toContain('label: "Product Type Registry"');
		expect(appSource).toContain('path="/assets/product-type-registry"');
		expect(appSource).toContain("element={<ProductTypeRegistryPage />}");
	});
});
