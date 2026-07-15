import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProductRegistrationPage from "./ProductRegistrationPage";

// Mock the API client so the page's on-mount draft fetch resolves harmlessly.
vi.mock("../api/client", () => ({
	getAPI: vi.fn().mockResolvedValue([]),
	postAPI: vi.fn().mockResolvedValue({}),
}));

// Stub heavy child components — the bridge card under test lives on the page itself.
vi.mock("../components/product-registration/RegistrationReviewDraftPanel", () => ({
	default: () => <div data-testid="stub-registration-panel" />,
}));
vi.mock("../components/product-registration/ProductKnowledgeIntakeForm", () => ({
	default: () => <div data-testid="stub-intake-form" />,
}));
vi.mock("../components/product-registration/ProductKnowledgeResultPanel", () => ({
	default: () => <div data-testid="stub-result-panel" />,
}));
vi.mock("../components/product-registration/BulkFastMossConvertTab", () => ({
	default: () => <div data-testid="stub-bulk-tab" />,
}));
vi.mock("../components/product-registration/AIFormPack", () => ({
	default: () => <div data-testid="stub-ai-form-pack" />,
}));

describe("ProductRegistrationPage — Product Intelligence bridge", () => {
	afterEach(() => cleanup());

	it("shows a bridge to Product Intelligence / AI Fill Missing that links to the /products INTELLIGENCE tab", () => {
		render(
			<MemoryRouter>
				<ProductRegistrationPage />
			</MemoryRouter>,
		);

		expect(screen.getByTestId("product-intelligence-bridge")).toBeInTheDocument();
		const link = screen.getByTestId("open-product-intelligence-link");
		expect(link).toHaveAttribute("href", "/products?tab=INTELLIGENCE");
		expect(link).toHaveTextContent(/Open Product Intelligence \/ AI Fill Missing/i);
	});

	it("explains the workflow: Copy Intelligence vs Product Truth vs Copy Registry, and that Recompute is deterministic while AI Fill Missing is DeepSeek", () => {
		render(
			<MemoryRouter>
				<ProductRegistrationPage />
			</MemoryRouter>,
		);

		const bridge = screen.getByTestId("product-intelligence-bridge");
		expect(bridge).toHaveTextContent(/Copy Intelligence/i);
		expect(bridge).toHaveTextContent(/Copy Registry/i);
		expect(bridge).toHaveTextContent(/deterministic/i);
		expect(bridge).toHaveTextContent(/DeepSeek/i);
		// Manual + imported parity is stated for the demo.
		expect(bridge).toHaveTextContent(/Manual and imported products/i);
	});
});
