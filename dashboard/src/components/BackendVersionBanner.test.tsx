import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchAPI } from "../api/client";
import BackendVersionBanner from "./BackendVersionBanner";

vi.mock("../api/client", () => ({ fetchAPI: vi.fn() }));

const mockedFetchAPI = vi.mocked(fetchAPI);

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

const healthyProof = {
	pid: 123,
	process_started_at: "2026-07-28T00:00:00Z",
	git_head: "a".repeat(40),
	git_branch: "main",
	route_count: 5,
	critical_routes: { "/api/flow/generate": true },
	dashboard_bundle: "index-test.js",
	source_stale_since_start: false,
	stale_source_sample: [],
};

describe("BackendVersionBanner", () => {
	it("locks actions and names changed sources while the backend is stale", async () => {
		const staleChange = vi.fn();
		mockedFetchAPI.mockResolvedValue({
			...healthyProof,
			source_stale_since_start: true,
			stale_source_sample: ["agent/services/ugc_video_prompt_compiler_service.py"],
		});

		render(<BackendVersionBanner onRuntimeStaleChange={staleChange} />);

		expect(await screen.findByText(/Backend needs restart/)).toBeInTheDocument();
		expect(screen.getByText(/ugc_video_prompt_compiler_service.py/)).toBeInTheDocument();
		expect(screen.getByText(/production actions are locked/i)).toBeInTheDocument();
		expect(staleChange).toHaveBeenCalledWith(true);
	});

	it("clears the stale lock after a successful refresh", async () => {
		const staleChange = vi.fn();
		mockedFetchAPI
			.mockResolvedValueOnce({
				...healthyProof,
				source_stale_since_start: true,
				stale_source_sample: ["agent/services/ugc_video_prompt_compiler_service.py"],
			})
			.mockResolvedValueOnce(healthyProof);

		render(<BackendVersionBanner onRuntimeStaleChange={staleChange} />);
		await screen.findByText(/Backend needs restart/);
		fireEvent.click(screen.getByRole("button", { name: /Refresh version check/i }));

		await waitFor(() => expect(staleChange).toHaveBeenLastCalledWith(false));
		expect(screen.queryByText(/production actions are locked/i)).toBeNull();
	});
});
