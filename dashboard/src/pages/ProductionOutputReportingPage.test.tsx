import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProductionOutputReportingPage from "./ProductionOutputReportingPage";
import {
	fetchProductionLedger,
	fetchProductionReport,
	type ProductionLedgerResponse,
	type ProductionReport,
} from "../api/productionOutputReporting";

vi.mock("../api/productionOutputReporting", () => ({
	fetchProductionLedger: vi.fn(),
	fetchProductionReport: vi.fn(),
}));

const mockedReport = vi.mocked(fetchProductionReport);
const mockedLedger = vi.mocked(fetchProductionLedger);

const report: ProductionReport = {
	reporting_timezone: "Asia/Kuala_Lumpur",
	window: { start_date: "2026-08-01", end_date: "2026-08-01", start_utc: "2026-07-31T16:00:00Z", end_utc: "2026-08-01T16:00:00Z", days: 1 },
	metric_definitions: {},
	filters: {
		staff: [{ value: "alice", label: "alice" }],
		media_types: ["VIDEO", "IMAGE", "POSTER"],
		production_recipes: ["HYBRID", "FACELESS", "MONTAGE", "POSTER_BUILDER"],
		origin_surfaces: ["PRODUCTION_STUDIO", "STANDALONE", "POSTER_BUILDER"],
		products: [{ value: "p1", label: "Product One" }],
		providers: ["GOOGLE_FLOW"],
		models: ["veo-3.1"],
		statuses: ["SUCCESS"],
		qa_statuses: ["QA_APPROVED"],
	},
	overview: { total_attempts: 2, successful_outputs: 2, successful_video_outputs: 1, successful_image_poster_outputs: 1, qa_approved: 1, failed_attempts: 0, retry_attempts: 0, success_rate: 1, retry_rate: 0, active_staff: 1, unique_products: 1 },
	video_breakdown: (["HYBRID", "FACELESS", "MONTAGE"] as const).map((production_recipe) => ({ production_recipe, total_attempts: 1, successful_outputs: production_recipe === "HYBRID" ? 1 : 0, successful_video_outputs: production_recipe === "HYBRID" ? 1 : 0, successful_image_poster_outputs: 0, qa_approved: 1, failed_attempts: 0, retry_attempts: 0, success_rate: 1, retry_rate: 0, active_staff: 1, unique_products: 1 })),
	poster_breakdown: [{ production_recipe: "POSTER_BUILDER", total_attempts: 1, successful_outputs: 1, successful_video_outputs: 0, successful_image_poster_outputs: 1, qa_approved: 1, failed_attempts: 0, retry_attempts: 0, success_rate: 1, retry_rate: 0, active_staff: 1, unique_products: 1 }],
	staff_performance: [{ staff: "alice", staff_display_name: "Alice", hybrid: 1, faceless: 0, montage: 0, poster: 1, successful_outputs: 2, qa_approved: 1, failed_attempts: 0, retry_attempts: 0, retry_rate: 0, success_rate: 1, unique_products: 1 }],
	daily_trend: [{ date: "2026-08-01", successful_video: 1, successful_image_poster: 1, failed_attempts: 0 }],
};

const ledger: ProductionLedgerResponse = {
	reporting_timezone: "Asia/Kuala_Lumpur",
	window: report.window,
	total: 1,
	limit: 25,
	offset: 0,
	items: [{ output_id: "out-1", media_type: "VIDEO", production_recipe: "HYBRID", origin_surface: "PRODUCTION_STUDIO", operator_id: "alice", operator_display_name: "Alice", product_id: "p1", product_name: "Product One", plan_or_run_id: "plan-1", production_item_id: "item-1", attempt_id: "attempt-1", attempt_number: 1, provider: "GOOGLE_FLOW", model_key: "veo-3.1", status: "SUCCESS", artifact_media_id: "media-1", qa_status: "QA_APPROVED", created_at: "2026-08-01T01:00:00Z", completed_at: "2026-08-01T01:01:00Z", failure_code: null, retry_count: 0 }],
};

describe("Production Output reporting page", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	mockedReport.mockResolvedValue(report);
	mockedLedger.mockResolvedValue(ledger);
	});

	afterEach(() => cleanup());

	it("renders the management route, current recipe filters, KPIs, staff table, and ledger", async () => {
		render(<ProductionOutputReportingPage />);

		expect(await screen.findByTestId("production-output-reporting-page")).toBeInTheDocument();
		expect(screen.getByText("Production Output")).toBeInTheDocument();
		expect(screen.getByText("Successful video")).toBeInTheDocument();
		expect(screen.getAllByText("Alice").length).toBeGreaterThanOrEqual(1);
		expect(screen.getByText("Poster Builder")).toBeInTheDocument();
		expect(screen.getByText("Generation ledger")).toBeInTheDocument();
		expect(screen.queryByText("T2V")).not.toBeInTheDocument();
	});
});
