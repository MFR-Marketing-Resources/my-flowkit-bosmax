import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
	modalProps: vi.fn(),
	fetch: vi.fn(),
	products: [] as unknown[],
}));

vi.mock("../api/client", () => ({
	fetchAPI: vi.fn().mockResolvedValue({ engines: [] }),
	csrfToken: () => "test-csrf",
}));
vi.mock("../api/creativeAssets", () => ({
	fetchCreativeAssetEligibilityAudit: vi.fn().mockResolvedValue({ eligible_assets: [] }),
}));
vi.mock("../api/creativeIntelligence", () => ({
	getProductRecipes: vi.fn().mockResolvedValue({ recipes: [], recommended_pretick: [] }),
}));
vi.mock("../api/productVisualOnboarding", () => ({
	fetchProductVisualReadiness: vi.fn().mockResolvedValue(null),
}));
vi.mock("../api/avatarRegistry", () => ({
	avatarRegistryCode: (value: string) => value,
	fetchAvatarRegistryPool: vi.fn().mockResolvedValue([]),
	filterRecipesToEligibleAvatarAssets: (recipes: unknown[]) => recipes,
	filterRecipesToAvatarRegistry: (recipes: unknown[]) => recipes,
	resolveAvatarRegistryCode: (value: string) => value,
}));
vi.mock("../api/workspaceGenerationPackages", () => ({
	createF2VGenerationPackage: vi.fn(),
	createI2VGenerationPackage: vi.fn(),
}));
vi.mock("../api/workspacePackages", () => ({
	compileWorkspacePromptPreview: vi.fn(),
	createWorkspaceExecutionPackage: vi.fn(),
	fetchPromptCompilerRuntimeConfig: vi.fn(() => new Promise<never>(() => {})),
	fetchWorkspacePackageReadiness: vi.fn(),
}));
vi.mock("../hooks/useProductCatalog", () => ({
	useProductCatalog: vi.fn(() => ({
		products: mocks.products,
		isLoadingProducts: false,
		productsError: null,
	})),
}));
vi.mock("../hooks/useStaffIdentity", () => ({
	useStaffIdentity: vi.fn(() => ({
		profiles: [
			{
				staff_id: "staff-ada",
				display_name: "Ada Lovelace",
				active: true,
				created_at: "",
				updated_at: "",
			},
		],
		selectedStaff: {
			staff_id: "staff-ada",
			display_name: "Ada Lovelace",
			active: true,
			created_at: "",
			updated_at: "",
		},
		staffId: "staff-ada",
		loading: false,
		error: "",
		hasStaff: true,
		selectStaff: vi.fn(),
		createProfile: vi.fn(),
		refresh: vi.fn(),
	})),
}));
vi.mock("../components/BackendVersionBanner", () => ({ default: () => null }));
vi.mock("../components/StaffIdentityBar", () => ({ default: () => null }));
vi.mock("../components/copywriting/CopyArchitectureV2LaneCard", () => ({
	default: () => null,
}));
vi.mock("../components/copywriting/CopywritingSourceSelector", () => ({
	default: () => null,
}));
vi.mock("../components/NativeExtendPanel", () => ({ default: () => null }));
vi.mock("../components/reporting/RequestReportPanel", () => ({
	default: () => null,
}));
vi.mock("../components/SocialCopyPackagePanel", () => ({ default: () => null }));
vi.mock("../components/workspace/CanonicalReferenceBindingControls", () => ({
	default: () => null,
	EMPTY_BINDING: {
		productReferenceAssetId: null,
		startFrameAssetId: null,
		endFrameAssetId: null,
		characterReferenceAssetId: null,
		sceneContextReferenceAssetId: null,
		styleReferenceAssetId: null,
	},
}));
vi.mock("../components/workspace/CreativeDirectionSection", () => ({
	default: () => null,
	EMPTY_CREATIVE_DIRECTION: {
		avatarCodes: [],
		recipes: [],
		cameraStyle: "UGC_IPHONE_RAW",
		characterPresence: "VISIBLE_CREATOR",
	},
}));
vi.mock("../components/workspace/IMGModule", () => ({ default: () => null }));
vi.mock("../components/workspace/SceneStrategySummary", () => ({
	default: () => null,
}));
vi.mock("../components/workspace/SearchableProductSelect", () => ({
	default: () => null,
}));
vi.mock("../components/workflow", () => ({
	ResolvedChip: () => null,
	StoryboardStrip: () => null,
	WorkflowStep: ({
	children,
		index,
		title,
	}: {
		children: ReactNode;
		index: number;
		title: string;
	}) => (
		<section data-testid={`workflow-step-${index}`}>
			<h3>{title}</h3>
			{children}
		</section>
	),
}));
vi.mock("../components/execution-approval/FinalPromptApprovalModal", () => ({
	FinalPromptApprovalModal: (props: {
		envelope: Record<string, unknown>;
		approvedBy: string;
		onApproved: (snapshot: Record<string, unknown>) => void;
		onCancel: () => void;
	}) => {
		mocks.modalProps(props);
		return (
			<div
				data-testid="final-prompt-approval-overlay"
				data-approved-by={props.approvedBy}
				data-envelope={JSON.stringify(props.envelope)}
			>
				<button type="button" onClick={props.onCancel}>
					Cancel
				</button>
				<button
					type="button"
					data-testid="test-approve"
					onClick={() =>
						props.onApproved({
							snapshot_id: "snapshot-1",
							final_prompt_text: "approved final prompt",
							scan_clean: 1,
						})
					}
				>
					Approve
				</button>
			</div>
		);
	},
}));

import OperatorPage from "./OperatorPage";

const workspaceExecutionPackage = {
	workspace_execution_package_id: "wep-v4-approval-test",
	mode: "T2V",
	product_id: null,
	prompt_text: "provider-ready prompt",
	prompt_fingerprint: "prompt-fingerprint",
	prompt_blocks: [{ block_index: 1, block_role: "SINGLE", duration_seconds: 8 }],
	generation_mode: "SINGLE",
	target_language: "BM_MS",
	camera_style: "UGC_IPHONE_RAW",
	character_presence: "VISIBLE_CREATOR",
	model: "Veo 3.1 - Lite",
	manual_fallback: {
		copy_prompt_available: false,
		image_generation_required: false,
	},
};

function renderOperator(search = "?v4=1") {
	return render(
		<MemoryRouter
			initialEntries={[
				{
					pathname: "/operator/T2V",
					search,
					state: { workspaceExecutionPackage },
				},
			]}
		>
			<OperatorPage mode="T2V" />
		</MemoryRouter>,
	);
}

function flowGenerateCalls() {
	return mocks.fetch.mock.calls.filter(([input]) =>
		String(input).includes("/api/flow/generate"),
	);
}

function providerCalls() {
	return mocks.fetch.mock.calls.filter(([input]) =>
		/\/api\/(?:provider|flow\/(?:execute-flow-job|video-jobs|native-extend))/.test(
			String(input),
		),
	);
}

beforeEach(() => {
	mocks.modalProps.mockClear();
	mocks.fetch.mockReset();
	mocks.fetch.mockImplementation(async (input: RequestInfo | URL) => {
		const url = String(input);
		if (url.includes("/api/flow/generate-job/")) {
			return { ok: true, json: async () => ({ status: "FAILED", error: "test stop" }) };
		}
		return {
			ok: true,
			json: async () => ({ job_id: "job-v4-approval-test" }),
		};
	});
	vi.stubGlobal("fetch", mocks.fetch);
});

afterEach(() => {
	vi.unstubAllGlobals();
	cleanup();
});

describe("OperatorPage V4 final prompt approval wiring", () => {
	it("opens the existing modal with the canonical envelope and selected Staff Profile", async () => {
		renderOperator();

		const generate = await screen.findByRole("button", {
			name: /Generate 1 clip/i,
		});
		fireEvent.click(generate);

		const overlay = await screen.findByTestId("final-prompt-approval-overlay");
		expect(overlay).toHaveAttribute("data-approved-by", "Ada Lovelace");
		const envelope = JSON.parse(overlay.getAttribute("data-envelope") || "{}");
		expect(envelope).toMatchObject({
			surface: "t2v",
			logical_mode: "T2V",
			final_prompt_text: "provider-ready prompt",
			model: "Veo 3.1 - Lite",
			aspect: "9:16",
			duration_s: 8,
			count: 1,
		});
		expect(mocks.modalProps).toHaveBeenCalled();
		expect(flowGenerateCalls()).toHaveLength(0);
		expect(providerCalls()).toHaveLength(0);
	});

	it("cancels without dispatch and approves through the existing handleExecute path", async () => {
		renderOperator();
		fireEvent.click(
			await screen.findByRole("button", { name: /Generate 1 clip/i }),
		);
		fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
		expect(screen.queryByTestId("final-prompt-approval-overlay")).toBeNull();
		expect(flowGenerateCalls()).toHaveLength(0);
		expect(providerCalls()).toHaveLength(0);

		cleanup();
		renderOperator();
		fireEvent.click(
			await screen.findByRole("button", { name: /Generate 1 clip/i }),
		);
		fireEvent.click(await screen.findByTestId("test-approve"));
		await waitFor(() =>
			expect(
				mocks.fetch.mock.calls.some(([input]) =>
					String(input).includes("/api/flow/generate"),
				),
			).toBe(true),
		);
		const dispatchCall = mocks.fetch.mock.calls.find(([input]) =>
			String(input).endsWith("/api/flow/generate"),
		);
		expect(JSON.parse(dispatchCall?.[1]?.body || "{}")).toMatchObject({
			prompt: "approved final prompt",
			mode: "T2V",
		});
		expect(providerCalls()).toHaveLength(0);
	});

	it("keeps classic view unchanged", async () => {
		renderOperator("?classic=1");
		const root = await screen.findByTestId("hybrid-workflow");
		expect(root).not.toHaveAttribute("data-variant", "v4");
		expect(screen.queryByTestId("final-prompt-approval-overlay")).toBeNull();
	});
});
