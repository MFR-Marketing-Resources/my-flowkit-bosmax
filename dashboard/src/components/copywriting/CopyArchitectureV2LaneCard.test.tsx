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
	ui_surface_state: "ACTIVE",
};

function response(body: unknown) {
	return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
}

function failedResponse(status: number, body: unknown) {
	return Promise.resolve({
		ok: false,
		status,
		text: () => Promise.resolve(JSON.stringify(body)),
	});
}

function stubV2Fetch({
	enabled = true,
	lanes = [lane],
	resolution = { status: "BLOCKED" },
	resolutionFailure,
}: {
	enabled?: boolean;
	lanes?: unknown[];
	resolution?: unknown;
	resolutionFailure?: { status: number; body: unknown };
} = {}) {
	const fetch = vi.fn((url: string) => {
		if (url.endsWith("consumer-status")) {
			return response({
				version: "2",
				feature_flags: {
					flag_name: "COPY_BLUEPRINT_V2_ENABLED",
					enabled,
					shadow_mode: false,
					scope: enabled ? "synthetic" : "",
					pilot_scope: [],
					state: enabled ? "ON" : "OFF",
				},
				legacy_path_unchanged: !enabled,
				binding_required_when_enabled: true,
				provider_calls: 0,
				credit_spend: false,
			});
		}
		if (url.endsWith("/lanes")) {
			return response({ version: "2", items: lanes });
		}
		if (url.includes("/bindings/")) {
			return resolutionFailure
				? failedResponse(resolutionFailure.status, resolutionFailure.body)
				: response(resolution);
		}
		throw new Error(`Unexpected fetch: ${url}`);
	});
	vi.stubGlobal("fetch", fetch);
	return fetch;
}

describe("CopyArchitectureV2LaneCard", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
	});

	it("shows explicit REQUIRED policy but never treats maintenance mode as ready", async () => {
		stubV2Fetch({ enabled: false });
		render(<CopyArchitectureV2LaneCard lane="T2V" productId="synthetic-product" />);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-policy")).toHaveTextContent("COPY_REQUIRED"),
		);
		expect(screen.getByTestId("copy-v2-readiness")).toHaveTextContent(
			"V2 MAINTENANCE MODE",
		);
		expect(screen.getByTestId("copy-v2-production-valid")).toHaveTextContent(
			"NOT ASSERTED BY V2",
		);
	});

	it("shows READY from persisted resolution with no WEP receipt", async () => {
		const fetch = stubV2Fetch({
			resolution: {
				status: "READY",
				blueprint_id: "bp-persisted",
				revision: 3,
				projection: { derived_copy: { hook: "Canonical approved hook" } },
			},
		});
		render(<CopyArchitectureV2LaneCard lane="T2V" productId="synthetic-product" />);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-readiness")).toHaveTextContent("READY"),
		);
		expect(screen.getByTestId("copy-v2-blueprint")).toHaveTextContent(
			"bp-persisted · r3",
		);
		expect(screen.getByTestId("copy-v2-approved-hook")).toHaveTextContent(
			"Canonical approved hook",
		);
		expect(fetch.mock.calls.some(([url]) => String(url).includes("/bindings/"))).toBe(true);
	});

	it("keeps a complete WEP receipt READY while persisted resolution stays authoritative", async () => {
		stubV2Fetch({
			resolution: { status: "READY", blueprint_id: "bp-canonical", revision: 1 },
		});
		render(
			<CopyArchitectureV2LaneCard
				lane="T2V"
				productId="synthetic-product"
				execution={{
					status: "READY",
					blueprint_id: "bp-canonical",
					revision: 1,
					formula_id: "PAS",
					formula_version: "pas.v1",
				}}
			/>,
		);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-readiness")).toHaveTextContent("READY"),
		);
	});

	it("does not let a narrower WEP receipt downgrade persisted READY", async () => {
		stubV2Fetch({
			resolution: { status: "READY", blueprint_id: "bp-persisted", revision: 2 },
		});
		render(
			<CopyArchitectureV2LaneCard
				lane="T2V"
				productId="synthetic-product"
				execution={{ copy_policy: "REQUIRED" }}
			/>,
		);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-readiness")).toHaveTextContent("READY"),
		);
	});

	it("blocks an explicit stale WEP receipt even when persisted resolution is READY", async () => {
		stubV2Fetch({
			resolution: { status: "READY", blueprint_id: "bp-persisted", revision: 1 },
		});
		render(
			<CopyArchitectureV2LaneCard
				lane="T2V"
				productId="synthetic-product"
				execution={{ status: "STALE", error_code: "WEP_RECEIPT_STALE" }}
			/>,
		);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-readiness")).toHaveTextContent("BLOCKED"),
		);
		expect(screen.getByTestId("copy-v2-blockers")).toHaveTextContent(
			"WEP_RECEIPT_STALE",
		);
	});

	it("fails closed when persisted resolution is non-ready even if WEP says READY", async () => {
		stubV2Fetch({
			resolution: {
				status: "BLOCKED",
				blockers: ["PERSISTED_BINDING_BLOCKED"],
			},
		});
		render(
			<CopyArchitectureV2LaneCard
				lane="T2V"
				productId="synthetic-product"
				execution={{ status: "READY" }}
			/>,
		);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-readiness")).toHaveTextContent("BLOCKED"),
		);
		expect(screen.getByTestId("copy-v2-blockers")).toHaveTextContent(
			"PERSISTED_BINDING_BLOCKED",
		);
	});

	it("renders structured backend errors from persisted resolution", async () => {
		stubV2Fetch({
			resolutionFailure: {
				status: 409,
				body: {
					detail: {
						error_code: "COPY_V2_RESOLUTION_FAILED",
						message: "Binding proof is stale",
					},
				},
			},
		});
		render(<CopyArchitectureV2LaneCard lane="T2V" productId="synthetic-product" />);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-readiness")).toHaveTextContent(
				"UNAVAILABLE — persisted V2 resolution failed",
			),
		);
		expect(screen.getByTestId("copy-v2-blockers")).toHaveTextContent(
			"COPY_V2_RESOLUTION_FAILED: Binding proof is stale",
		);
	});

	it("cannot let product A's package mark product B READY", async () => {
		const fetch = vi.fn((url: string) => {
			if (url.endsWith("consumer-status")) {
				return response({
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
				});
			}
			if (url.endsWith("/lanes")) return response({ version: "2", items: [lane] });
			if (url.includes("product-a")) return response({ status: "READY", blueprint_id: "bp-a" });
			return response({ status: "BLOCKED", blockers: ["PRODUCT_B_NOT_READY"] });
		});
		vi.stubGlobal("fetch", fetch);
		const view = render(
			<CopyArchitectureV2LaneCard
				lane="T2V"
				productId="product-a"
				execution={{ status: "READY", blueprint_id: "bp-a" }}
			/>,
		);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-readiness")).toHaveTextContent("READY"),
		);
		view.rerender(
			<CopyArchitectureV2LaneCard
				lane="T2V"
				productId="product-b"
				execution={{ status: "READY", blueprint_id: "bp-a" }}
			/>,
		);
		await waitFor(() =>
			expect(screen.getByTestId("copy-v2-readiness")).toHaveTextContent("BLOCKED"),
		);
		expect(screen.getByTestId("copy-v2-blockers")).toHaveTextContent(
			"PRODUCT_B_NOT_READY",
		);
		expect(screen.getByTestId("copy-v2-lane-card")).toHaveAttribute(
			"data-copy-v2-product",
			"product-b",
		);
	});

	it("shows a copy-free adapter only when its persisted receipt is READY", async () => {
		const copyFreeLane = {
			...lane,
			lane_id: "IMG_FASTLANE",
			display_name: "IMG Fastlane",
			media_kind: "IMAGE",
			copy_policy: "NOT_REQUIRED",
			adapter: "ImageCopyProjection",
		};
		stubV2Fetch({
			lanes: [copyFreeLane],
			resolution: { status: "READY", copy_policy: "NOT_REQUIRED" },
		});
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
		expect(screen.getByTestId("copy-v2-blueprint")).toHaveTextContent(
			"N/A — copy-free lane",
		);
	});
});
