import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CopyArchitectureV2LaneCard from "./CopyArchitectureV2LaneCard";

const lane = {
	lane_id: "T2V",
	display_name: "T2V",
	media_kind: "VIDEO",
	copy_policy: "REQUIRED",
	current_api_entry_point: "POST /api/flow/execute-flow-job",
	current_service_entry_point: "workspace_execution_package_service",
	current_page_entry_point: "OperatorPage",
	adapter: "VideoCopyProjection",
	phase3_scope: "bind",
};

function response(body: unknown) {
	return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
}

describe("CopyArchitectureV2LaneCard", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
	});

	it("shows explicit REQUIRED policy and legacy compatibility when flag is off", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn((url: string) =>
				url.endsWith("consumer-status")
					? response({
							version: "2",
							feature_flags: {
								flag_name: "COPY_BLUEPRINT_V2_ENABLED",
								enabled: false,
								shadow_mode: false,
								scope: "",
								pilot_scope: [],
								state: "OFF",
							},
							legacy_path_unchanged: true,
							binding_required_when_enabled: true,
							provider_calls: 0,
							credit_spend: false,
						})
					: response({ version: "2", items: [lane] }),
			),
		);
		render(<CopyArchitectureV2LaneCard lane="T2V" productId="synthetic-product" />);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-policy")).toHaveTextContent("COPY_REQUIRED"),
		);
		expect(screen.getByTestId("copy-v2-readiness")).toHaveTextContent(
			"V2 OFF — LEGACY COMPATIBLE",
		);
		expect(screen.getByTestId("copy-v2-production-valid")).toHaveTextContent(
			"NOT ASSERTED BY V2",
		);
	});

	it("fails closed without a V2 binding when the flag is on", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn((url: string) =>
				url.endsWith("consumer-status")
					? response({
							version: "2",
							feature_flags: {
								flag_name: "COPY_BLUEPRINT_V2_ENABLED",
							enabled: true,
								shadow_mode: false,
								scope: "synthetic",
								pilot_scope: [],
								state: "ON",
							},
							legacy_path_unchanged: false,
							binding_required_when_enabled: true,
							provider_calls: 0,
							credit_spend: false,
						})
					: response({ version: "2", items: [lane] }),
			),
		);
		render(<CopyArchitectureV2LaneCard lane="T2V" productId="synthetic-product" />);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-readiness")).toHaveTextContent("BLOCKED"),
		);
		expect(screen.getByTestId("copy-v2-blockers")).toHaveTextContent(
			"Approved V2 blueprint",
		);
		expect(screen.getByTestId("copy-v2-action-availability")).toHaveTextContent(
			"Blocked",
		);
	});

	it("shows an explicit copy-free adapter receipt with synthetic READY metadata", async () => {
		const copyFreeLane = { ...lane, lane_id: "IMG_FASTLANE", display_name: "IMG Fastlane", media_kind: "IMAGE", copy_policy: "NOT_REQUIRED", adapter: "ImageCopyProjection" };
		vi.stubGlobal(
			"fetch",
			vi.fn((url: string) =>
				url.endsWith("consumer-status")
					? response({
							version: "2",
							feature_flags: { flag_name: "COPY_BLUEPRINT_V2_ENABLED", enabled: true, shadow_mode: false, scope: "synthetic", pilot_scope: [], state: "ON" },
							legacy_path_unchanged: false,
							binding_required_when_enabled: true,
							provider_calls: 0,
							credit_spend: false,
						})
					: response({ version: "2", items: [copyFreeLane] }),
			),
		);
		render(
			<CopyArchitectureV2LaneCard
				lane="IMG_FASTLANE"
				productId="synthetic-product"
				execution={{ status: "READY", copy_policy: "NOT_REQUIRED" }}
			/>,
		);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-policy")).toHaveTextContent("COPY_NOT_REQUIRED"),
		);
		expect(screen.getByTestId("copy-v2-readiness")).toHaveTextContent("READY");
		expect(screen.getByTestId("copy-v2-blueprint")).toHaveTextContent("N/A — copy-free lane");
	});

	it("renders the numeric revision from a real V2 binding receipt", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn((url: string) =>
				url.endsWith("consumer-status")
					? response({
							version: "2",
							feature_flags: {
								flag_name: "COPY_BLUEPRINT_V2_ENABLED",
								enabled: true,
								shadow_mode: false,
								scope: "synthetic",
								pilot_scope: [],
								state: "ON",
							},
							legacy_path_unchanged: false,
							binding_required_when_enabled: true,
							provider_calls: 0,
							credit_spend: false,
						})
					: response({ version: "2", items: [lane] }),
			),
		);
		render(
			<CopyArchitectureV2LaneCard
				lane="T2V"
				productId="synthetic-product"
				execution={{
					status: "READY",
					blueprint_id: "bp-synthetic",
					revision: 7,
					formula_id: "PAS",
					formula_version: "pas.v1",
				}}
			/>,
		);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-blueprint")).toHaveTextContent(
				"bp-synthetic · r7",
			),
		);
	});
});
