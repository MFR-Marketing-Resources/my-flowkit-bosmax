import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResultsSidebar from "./ResultsSidebar";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

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

	it("discovers a video registered during the mounted session", async () => {
		const fetchMock = vi.fn().mockResolvedValue({
			ok: true,
			json: async () => ({
				artifacts: [
					{
						media_id: "14482c9d-1972-4df3-9fa2-1fdbaa1964a7",
						artifact_kind: "video",
						size_mb: 1.54,
						created_at: new Date(Date.now() + 1000).toISOString(),
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
			/>,
		);

		await waitFor(() => expect(container.querySelector("video")).not.toBeNull());
		expect(container.querySelector("video")).toHaveAttribute(
			"src",
			"/api/flow/retrieved/14482c9d-1972-4df3-9fa2-1fdbaa1964a7",
		);
		expect(fetchMock).toHaveBeenCalledWith(
			"/api/flow/artifacts?limit=20&kind=video",
		);
	});
});
