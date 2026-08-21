import { getAPI } from "./client";

export type ProductionMediaType = "VIDEO" | "IMAGE" | "POSTER";
export type ProductionRecipe = "HYBRID" | "FACELESS" | "MONTAGE" | "POSTER_BUILDER";
export type ProductionOriginSurface = "PRODUCTION_STUDIO" | "STANDALONE" | "POSTER_BUILDER";

export interface ProductionFilterOptions {
	staff: { value: string; label: string }[];
	media_types: ProductionMediaType[];
	production_recipes: ProductionRecipe[];
	origin_surfaces: ProductionOriginSurface[];
	products: { value: string; label: string }[];
	providers: string[];
	models: string[];
	statuses: string[];
	qa_statuses: string[];
}

export interface ProductionMetricBlock {
	total_attempts: number;
	successful_outputs: number;
	successful_video_outputs: number;
	successful_image_poster_outputs: number;
	qa_approved: number;
	failed_attempts: number;
	retry_attempts: number;
	success_rate: number | null;
	retry_rate: number | null;
	active_staff: number;
	unique_products: number;
}

export interface ProductionBreakdown extends ProductionMetricBlock {
	production_recipe: ProductionRecipe;
}

export interface ProductionStaffRow {
	staff: string;
	staff_display_name: string;
	hybrid: number;
	faceless: number;
	montage: number;
	poster: number;
	successful_outputs: number;
	qa_approved: number;
	failed_attempts: number;
	retry_attempts: number;
	retry_rate: number | null;
	success_rate: number | null;
	unique_products: number;
}

export interface ProductionTrendRow {
	date: string;
	successful_video: number;
	successful_image_poster: number;
	failed_attempts: number;
}

export interface ProductionWindow {
	start_date: string;
	end_date: string;
	start_utc: string;
	end_utc: string;
	days: number;
}

export interface ProductionReport {
	reporting_timezone: string;
	window: ProductionWindow;
	metric_definitions: Record<string, string>;
	filters: ProductionFilterOptions;
	overview: ProductionMetricBlock;
	video_breakdown: ProductionBreakdown[];
	poster_breakdown: ProductionBreakdown[];
	staff_performance: ProductionStaffRow[];
	daily_trend: ProductionTrendRow[];
}

export interface ProductionLedgerRow {
	output_id: string | null;
	media_type: ProductionMediaType | null;
	production_recipe: ProductionRecipe | null;
	origin_surface: ProductionOriginSurface | null;
	operator_id: string | null;
	operator_display_name: string | null;
	product_id: string | null;
	product_name: string | null;
	plan_or_run_id: string | null;
	production_item_id: string | null;
	attempt_id: string | null;
	attempt_number: number;
	provider: string | null;
	model_key: string | null;
	status: string;
	artifact_media_id: string | null;
	qa_status: string;
	created_at: string | null;
	completed_at: string | null;
	failure_code: string | null;
	retry_count: number;
}

export interface ProductionLedgerResponse {
	reporting_timezone: string;
	window: ProductionWindow;
	items: ProductionLedgerRow[];
	total: number;
	limit: number;
	offset: number;
}

export interface ProductionQuery {
	start_date: string;
	end_date: string;
	staff?: string;
	media_type?: ProductionMediaType;
	production_recipe?: ProductionRecipe;
	origin_surface?: ProductionOriginSurface;
	product_id?: string;
	provider?: string;
	model_key?: string;
	status?: string;
	qa_status?: string;
}

function queryString(query: ProductionQuery, extra?: Record<string, string | number | undefined>) {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries({ ...query, ...extra })) {
		if (value !== undefined && value !== "") params.set(key, String(value));
	}
	return params.toString();
}

export function fetchProductionReport(query: ProductionQuery) {
	return getAPI<ProductionReport>(`/api/reporting/production?${queryString(query)}`);
}

export function fetchProductionLedger(query: ProductionQuery, limit = 25, offset = 0) {
	return getAPI<ProductionLedgerResponse>(
		`/api/reporting/production/ledger?${queryString(query, { limit, offset })}`,
	);
}
