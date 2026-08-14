import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import ResultsSidebar from "./ResultsSidebar";

afterEach(cleanup);

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
});
