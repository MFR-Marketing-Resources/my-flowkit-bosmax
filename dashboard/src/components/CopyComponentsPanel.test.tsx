import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CopyComponentsPanel from "./CopyComponentsPanel";

vi.mock("../api/copyComponents", () => ({
	COMPONENT_TYPES: ["HOOK", "SUBHOOK", "USP_SET", "CTA"],
	COMPONENT_TYPE_LABEL: {
		HOOK: "Hook",
		SUBHOOK: "Subhook",
		USP_SET: "USP set",
		CTA: "CTA",
	},
	COMPONENT_STATUS_REVIEW: "COMPONENT_REVIEW_REQUIRED",
	COMPONENT_STATUS_APPROVED: "COMPONENT_APPROVED",
	fetchCopyCapacity: vi.fn(),
	listCopyComponents: vi.fn(),
	composeCopyFromComponents: vi.fn(),
	authorCopyComponents: vi.fn(),
	approveCopyComponent: vi.fn(),
}));

import {
	authorCopyComponents,
	composeCopyFromComponents,
	fetchCopyCapacity,
	listCopyComponents,
} from "../api/copyComponents";

const mockedCap = vi.mocked(fetchCopyCapacity);
const mockedList = vi.mocked(listCopyComponents);
const mockedCompose = vi.mocked(composeCopyFromComponents);
const mockedAuthor = vi.mocked(authorCopyComponents);

const CAPACITY = {
	product_id: "p1",
	angles_derived: true,
	angle_warnings: [],
	component_count: 80,
	total_combinations: 2304,
	per_angle: [
		{ angle_key: "a1", angle_label: "Anak menangis malam" },
		{ angle_key: "a2", angle_label: "Sengal badan" },
	],
	next_best: null,
};

function primeLoad(capOver: Record<string, unknown> = {}) {
	mockedCap.mockResolvedValue({ ...CAPACITY, ...capOver } as never);
	mockedList.mockResolvedValue({ product_id: "p1", items: [], count: 0 } as never);
}

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe("CopyComponentsPanel", () => {
	it("shows capacity, angle and component counts after load", async () => {
		primeLoad();
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		expect(await screen.findByTestId("cc-capacity")).toHaveTextContent(/2[,.]?304/);
		expect(screen.getByTestId("cc-angle-count")).toHaveTextContent("2");
		expect(screen.getByTestId("cc-component-count")).toHaveTextContent("80");
	});

	it("compose is free: calls compose and onComposed, shows PERCUMA", async () => {
		primeLoad();
		mockedCompose.mockResolvedValue({
			created: 50,
			deduped: 0,
			coverage: { status: "COVERAGE_OK" },
		});
		const onComposed = vi.fn();
		render(<CopyComponentsPanel productId="p1" onComposed={onComposed} />);
		fireEvent.click(await screen.findByTestId("cc-compose"));
		await waitFor(() =>
			expect(mockedCompose).toHaveBeenCalledWith(
				expect.objectContaining({ product_id: "p1", count: 50 }),
			),
		);
		await waitFor(() => expect(onComposed).toHaveBeenCalled());
		expect(await screen.findByTestId("cc-success")).toHaveTextContent(/PERCUMA/i);
	});

	it("author requires confirmation before spending tokens", async () => {
		primeLoad();
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		fireEvent.click(await screen.findByTestId("cc-author"));
		// Confirm modal appears with an explicit token warning; author NOT fired yet.
		expect(await screen.findByText(/guna token DeepSeek/i)).toBeInTheDocument();
		expect(mockedAuthor).not.toHaveBeenCalled();
	});

	it("compose is disabled when the pool cannot compose anything", async () => {
		primeLoad({ total_combinations: 0, component_count: 0, per_angle: [] });
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		expect(await screen.findByTestId("cc-compose")).toBeDisabled();
	});
});
