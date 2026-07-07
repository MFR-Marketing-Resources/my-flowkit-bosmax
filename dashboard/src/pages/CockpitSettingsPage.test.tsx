import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CockpitSettingsPage from "./CockpitSettingsPage";

vi.mock("../api/posterBuilderSettings", () => {
	const settings = {
		poster_objectives: [
			{ id: "Product awareness", label: "Product awareness", default: true },
			{ id: "Sales conversion", label: "Sales conversion" },
		],
		poster_types: [
			{ id: "Product-only hero poster", label: "Product-only hero poster", default: true },
		],
		languages: [{ id: "ms", label: "Malay", default: true }],
		visual_routes: [{ id: "Premium commercial", label: "Premium commercial", default: true }],
		human_presence_modes: [
			{ id: "No human / product-forward", label: "No human / product-forward", default: true },
		],
		text_density_options: [{ id: "medium", label: "Medium", default: true }],
		flow_mirror: {
			aspect_ratios: ["9:16", "1:1", "16:9", "4:3", "3:4"],
			counts: [1, 2, 3, 4],
			image_models: [
				{ key: "NANO_BANANA_2", label: "Nano Banana 2", pending: false },
				{ key: "NANO_BANANA_2_LITE", label: "Nano Banana 2 Lite", pending: true },
			],
			defaults: { aspect_ratio: "9:16", count: 1, image_model: "Nano Banana 2" },
			source: "models.json",
		},
		copy_components: {
			routes: ["DIRECT", "STEALTH", "REVIEW_REQUIRED"],
			copy_sets_scope: "product",
			copy_sets_endpoint: "/api/copy-sets/product/{product_id}",
			landbank_products: 0,
			source: "copy_signals+landbank",
		},
		ai_provider: {
			lane: "text_assist",
			configured: true,
			status: "configured",
			provider_id: "deepseek",
			model_id: "deepseek-chat",
			execution_enabled: true,
			source: "ai_provider",
		},
		sources: {
			poster_dimensions: "config",
			flow_mirror: "models.json",
			copy_components: "copy_signals+landbank",
			ai_provider: "ai_provider",
		},
	};
	return {
		usePosterBuilderSettings: () => settings,
		fetchPosterBuilderSettings: vi.fn().mockResolvedValue(settings),
		POSTER_BUILDER_SETTINGS_FALLBACK: settings,
		defaultOptionId: (opts: { id: string; default?: boolean }[]) =>
			(opts.find((o) => o.default) ?? opts[0])?.id ?? "",
	};
});

describe("CockpitSettingsPage", () => {
	afterEach(() => cleanup());

	it("renders all SSOT sections from the settings hook", () => {
		render(<CockpitSettingsPage />);
		expect(screen.getByTestId("cockpit-settings-page")).toBeInTheDocument();
		expect(screen.getByTestId("cockpit-dim-objectives")).toBeInTheDocument();
		expect(screen.getByTestId("cockpit-dim-languages")).toBeInTheDocument();
		expect(screen.getByTestId("cockpit-flow-mirror")).toBeInTheDocument();
		expect(screen.getByTestId("cockpit-copy-components")).toBeInTheDocument();
		expect(screen.getByTestId("cockpit-ai-status")).toBeInTheDocument();
	});

	it("shows poster dimension values and the pending image model flag", () => {
		render(<CockpitSettingsPage />);
		expect(screen.getByText("Product awareness")).toBeInTheDocument();
		expect(screen.getByText(/Nano Banana 2 Lite/)).toBeInTheDocument();
		expect(screen.getByText("pending id")).toBeInTheDocument();
	});

	it("surfaces AI provider status and copy routes without secrets", () => {
		render(<CockpitSettingsPage />);
		expect(screen.getByTestId("cockpit-ai-status-value")).toHaveTextContent(
			"configured",
		);
		expect(screen.getByText(/DIRECT/)).toBeInTheDocument();
		// no key/secret text is rendered
		expect(screen.queryByText(/api[_-]?key/i)).not.toBeInTheDocument();
	});

	it("tags each section with its source", () => {
		render(<CockpitSettingsPage />);
		const tags = screen.getAllByTestId("cockpit-source-tag");
		expect(tags.length).toBeGreaterThan(0);
		expect(tags.some((t) => t.textContent?.includes("models.json"))).toBe(true);
	});
});
