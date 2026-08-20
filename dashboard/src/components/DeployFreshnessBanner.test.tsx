import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchAPI } from "../api/client";
import DeployFreshnessBanner from "./DeployFreshnessBanner";

vi.mock("../api/client", () => ({ fetchAPI: vi.fn() }));
const mockedFetchAPI = vi.mocked(fetchAPI);

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

const proof = (sha: string) => ({ git_head: sha, dashboard_bundle: `index-${sha.slice(0, 4)}.js` });
const SHA_A = "a".repeat(40);
const SHA_B = "b".repeat(40);

describe("DeployFreshnessBanner", () => {
	it("stays silent while the deployed SHA is unchanged", async () => {
		mockedFetchAPI.mockResolvedValue(proof(SHA_A));
		render(<DeployFreshnessBanner intervalMs={20} onReload={vi.fn()} />);
		// Let several poll cycles run — the SHA never changes, so no banner.
		await new Promise((r) => setTimeout(r, 90));
		expect(screen.queryByTestId("deploy-freshness-banner")).toBeNull();
		expect(mockedFetchAPI.mock.calls.length).toBeGreaterThan(1);
	});

	it("prompts a reload when the deployed SHA changes since the tab loaded", async () => {
		const onReload = vi.fn();
		mockedFetchAPI
			.mockResolvedValueOnce(proof(SHA_A)) // load anchors on SHA_A
			.mockResolvedValue(proof(SHA_B)); // a new release is deployed
		render(<DeployFreshnessBanner intervalMs={20} onReload={onReload} />);

		const banner = await screen.findByTestId("deploy-freshness-banner");
		expect(banner).toBeInTheDocument();
		fireEvent.click(screen.getByTestId("deploy-freshness-reload"));
		expect(onReload).toHaveBeenCalledTimes(1);
	});

	it("can be dismissed without reloading", async () => {
		const onReload = vi.fn();
		mockedFetchAPI
			.mockResolvedValueOnce(proof(SHA_A))
			.mockResolvedValue(proof(SHA_B));
		render(<DeployFreshnessBanner intervalMs={20} onReload={onReload} />);

		await screen.findByTestId("deploy-freshness-banner");
		fireEvent.click(screen.getByTestId("deploy-freshness-dismiss"));
		await waitFor(() =>
			expect(screen.queryByTestId("deploy-freshness-banner")).toBeNull(),
		);
		expect(onReload).not.toHaveBeenCalled();
	});

	it("ignores transient version-proof errors (no false banner)", async () => {
		mockedFetchAPI.mockRejectedValue(new Error("network"));
		render(<DeployFreshnessBanner intervalMs={20} onReload={vi.fn()} />);
		await new Promise((r) => setTimeout(r, 60));
		expect(screen.queryByTestId("deploy-freshness-banner")).toBeNull();
	});
});
