import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ResultsSidebar from "./ResultsSidebar";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

beforeEach(() => window.sessionStorage.clear());

describe("ResultsSidebar video lane", () => {
	it("uses video wording and renders one canonical Video Library link", () => {
		render(
			<ResultsSidebar
				generating
				libraryHref="/library/videos"
				mediaKind="video"
				results={[]}
			/>,
		);

		expect(screen.getByText(/Generating video/)).toBeInTheDocument();
		expect(
			screen.getAllByRole("link", { name: "Video Library" }),
		).toHaveLength(1);
		expect(
			screen.queryByRole("link", { name: "Image Library" }),
		).not.toBeInTheDocument();
		expect(screen.getByRole("link", { name: "Results" })).toHaveAttribute(
			"href",
			"/results",
		);
	});

	it("queries durable identity and does not globally recover recent artifacts", async () => {
		const fetchMock = vi.fn().mockResolvedValue({
			ok: true,
			json: async () => ({
				results: [
					{
						media_id: "14482c9d-1972-4df3-9fa2-1fdbaa1964a7",
						size_mb: 1.54,
						retrieved_url: "/api/flow/retrieved/14482c9d-1972-4df3-9fa2-1fdbaa1964a7",
					},
				],
			}),
		});
		vi.stubGlobal("fetch", fetchMock);

		const { container } = render(
			<ResultsSidebar
				libraryHref="/library/videos"
				mediaKind="video"
				results={[]}
				requestId="req-session"
				staffId="staff-session"
				surfaceLane="FACELESS"
			/>,
		);

		await waitFor(() => expect(container.querySelector("video")).not.toBeNull());
		expect(container.querySelector("video")).toHaveAttribute(
			"src",
			"/api/flow/retrieved/14482c9d-1972-4df3-9fa2-1fdbaa1964a7",
		);
		expect(fetchMock).toHaveBeenCalledWith(
			"/api/results/recover?request_id=req-session&staff_id=staff-session&surface_lane=FACELESS",
		);
		expect(fetchMock).not.toHaveBeenCalledWith(
			expect.stringContaining("/api/flow/artifacts"),
		);
	});
});
