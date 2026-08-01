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
	addAngles: vi.fn(),
	suggestAngles: vi.fn(),
}));

import {
	addAngles,
	authorCopyComponents,
	composeCopyFromComponents,
	fetchCopyCapacity,
	listCopyComponents,
	suggestAngles,
} from "../api/copyComponents";

const mockedCap = vi.mocked(fetchCopyCapacity);
const mockedList = vi.mocked(listCopyComponents);
const mockedCompose = vi.mocked(composeCopyFromComponents);
const mockedAuthor = vi.mocked(authorCopyComponents);
const mockedAddAngles = vi.mocked(addAngles);
const mockedSuggest = vi.mocked(suggestAngles);

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
				expect.objectContaining({ product_id: "p1", count: 500 }),
			),
		);
		await waitFor(() => expect(onComposed).toHaveBeenCalled());
		expect(await screen.findByTestId("cc-success")).toHaveTextContent(/FREE/i);
	});

	it("renders the current angles and the angle counter", async () => {
		primeLoad();
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		expect(await screen.findByTestId("cc-angle-list")).toHaveTextContent(
			"Anak menangis malam",
		);
		expect(screen.getByTestId("cc-angle-cap")).toHaveTextContent("2/12");
	});

	it("add-angle is free: sends the typed use-cases and shows the new count", async () => {
		primeLoad();
		mockedAddAngles.mockResolvedValue({
			ok: true, angle_count: 4, added: 2,
			approved: false, review_required: true, draft_id: "d1",
		});
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		const box = await screen.findByTestId("cc-pains");
		fireEvent.change(box, { target: { value: "masuk angin\nsakit belakang" } });
		fireEvent.click(screen.getByTestId("cc-add-angles"));
		await waitFor(() =>
			expect(mockedAddAngles).toHaveBeenCalledWith({
				product_id: "p1",
				pains: ["masuk angin", "sakit belakang"],
			}),
		);
		// 08D: angles are STAGED review-required — never silently approved.
		const success = await screen.findByTestId("cc-success");
		expect(success).toHaveTextContent(/2 angle\(s\) staged/i);
		expect(success).toHaveTextContent(/REVIEW REQUIRED/i);
	});

	it("add-angle surfaces a CLAIM_BLOCKED refusal without throwing", async () => {
		primeLoad();
		mockedAddAngles.mockResolvedValue({
			ok: false,
			error: "CLAIM_BLOCKED",
			claim_tokens: ["cure"],
		});
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		fireEvent.change(await screen.findByTestId("cc-pains"), {
			target: { value: "guaranteed cure" },
		});
		fireEvent.click(screen.getByTestId("cc-add-angles"));
		expect(await screen.findByTestId("cc-error")).toHaveTextContent(/banned/i);
	});

	it("author requires confirmation before spending tokens", async () => {
		primeLoad();
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		fireEvent.click(await screen.findByTestId("cc-author"));
		// Confirm modal appears with an explicit token warning; author NOT fired yet.
		expect(await screen.findByText(/spend DeepSeek tokens/i)).toBeInTheDocument();
		expect(mockedAuthor).not.toHaveBeenCalled();
	});

	it("compose is disabled when the pool cannot compose anything", async () => {
		primeLoad({ total_combinations: 0, component_count: 0, per_angle: [] });
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		expect(await screen.findByTestId("cc-compose")).toBeDisabled();
	});

	it("compose count auto-defaults to the composable capacity (not hardcoded)", async () => {
		primeLoad(); // total_combinations 2304 -> min(500, 2304) = 500
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		expect(await screen.findByTestId("cc-compose-count")).toHaveValue(500);
	});

	it("author continues past a failed slot instead of aborting the batch", async () => {
		primeLoad();
		// The first slot fails on BOTH its initial call and its retry; every other
		// slot succeeds. 2 angles x 4 types = 8 slots must ALL still be attempted.
		let calls = 0;
		mockedAuthor.mockImplementation(async () => {
			calls += 1;
			if (calls <= 2) throw new Error("502 provider hiccup");
			return { created_count: 4 };
		});
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		fireEvent.click(await screen.findByTestId("cc-author"));
		fireEvent.click(await screen.findByRole("button", { name: /Yes, author/i }));
		await waitFor(() =>
			expect(mockedAuthor.mock.calls.length).toBeGreaterThanOrEqual(8),
		);
		expect(await screen.findByTestId("cc-error")).toHaveTextContent(/slot\(s\) failed/i);
	});

	it("suggest opens a confirm modal and spends nothing until confirmed", async () => {
		primeLoad();
		mockedSuggest.mockResolvedValue({
			ok: true,
			suggestions: ["lampin bocor waktu malam", "kembung perut bayi"],
		});
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		fireEvent.click(await screen.findByTestId("cc-suggest-angles"));
		expect(await screen.findByText(/Suggest angles with AI/i)).toBeInTheDocument();
		expect(mockedSuggest).not.toHaveBeenCalled();
	});

	it("suggest fills the textarea with AI angles after confirming", async () => {
		primeLoad();
		mockedSuggest.mockResolvedValue({
			ok: true,
			suggestions: ["lampin bocor waktu malam", "kembung perut bayi"],
		});
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		fireEvent.click(await screen.findByTestId("cc-suggest-angles"));
		fireEvent.click(
			screen.getByRole("button", { name: "Yes, suggest (spend a little)" }),
		);
		await waitFor(() =>
			expect(mockedSuggest).toHaveBeenCalledWith(
				expect.objectContaining({ product_id: "p1" }),
			),
		);
		expect(screen.getByTestId("cc-pains")).toHaveValue(
			"lampin bocor waktu malam\nkembung perut bayi",
		);
		expect(await screen.findByTestId("cc-success")).toHaveTextContent(
			/suggested by AI/i,
		);
	});

	it("suggest surfaces a not-configured provider without throwing", async () => {
		primeLoad();
		mockedSuggest.mockRejectedValue(
			new Error("409 AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED"),
		);
		render(<CopyComponentsPanel productId="p1" onComposed={vi.fn()} />);
		fireEvent.click(await screen.findByTestId("cc-suggest-angles"));
		fireEvent.click(
			screen.getByRole("button", { name: "Yes, suggest (spend a little)" }),
		);
		expect(await screen.findByTestId("cc-error")).toHaveTextContent(
			/not configured/i,
		);
	});
});
