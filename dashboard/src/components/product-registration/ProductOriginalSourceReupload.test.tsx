import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
	fetchProductVisualReadinessMock,
	saveProductVisualSetupMock,
	uploadOriginalSourceCandidateMock,
} = vi.hoisted(() => ({
	fetchProductVisualReadinessMock: vi.fn(),
	saveProductVisualSetupMock: vi.fn(),
	uploadOriginalSourceCandidateMock: vi.fn(),
}));

vi.mock("../../api/productVisualOnboarding", async () => {
	const actual = await vi.importActual<typeof import("../../api/productVisualOnboarding")>(
		"../../api/productVisualOnboarding",
	);
	return {
		...actual,
		fetchProductVisualReadiness: fetchProductVisualReadinessMock,
		saveProductVisualSetup: saveProductVisualSetupMock,
		uploadOriginalSourceCandidate: uploadOriginalSourceCandidateMock,
	};
});

import ProductOriginalSourceReupload from "./ProductOriginalSourceReupload";
import type { ProductVisualReadiness } from "../../types";

const readiness: ProductVisualReadiness = {
	product_id: "product-1",
	canonical_media_status: "AVAILABLE",
	canonical_source_media_id: "old-media",
	canonical_source_sha256: "1".repeat(64),
	original_source_reauthorization_required: true,
	reference_pack_status: "PENDING_REVIEW",
	visual_grounding_status: "VISUAL_GROUNDING_READY",
	visual_grounding_source: "PRODUCT_TRUTH_LOCK_SOURCE",
	cutout_status: "REJECTED",
	cutout_review_status: "REJECTED",
	exact_commerce_status: "EXACT_COMMERCE_REVIEW_REQUIRED",
	blockers: [],
	warnings: [],
	provider_operations: 0,
	created_without_credit: true,
	can_prepare_cutout: false,
	can_review_cutout: false,
	can_approve_cutout: false,
	can_rebuild_cutout: false,
	can_open_source: true,
	can_view: true,
};

describe("ProductOriginalSourceReupload", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		fetchProductVisualReadinessMock.mockResolvedValue({
			...readiness,
			canonical_source_sha256: "1".repeat(64),
		});
		saveProductVisualSetupMock.mockResolvedValue({});
		uploadOriginalSourceCandidateMock.mockResolvedValue({
			product_id: "product-1",
			media_id: "new-media",
			sha256: "2".repeat(64),
			filename: "new-source.jpg",
			mime: "image/jpeg",
			bytes: 128,
			width: 120,
			height: 160,
			status: "PENDING_REAUTHORIZATION",
			created_without_credit: true,
		});
	});

	it("uploads, previews, and explicitly reauthorizes the selected source", async () => {
		const onChanged = vi.fn();
		render(
			<ProductOriginalSourceReupload
				productId="product-1"
				readiness={readiness}
				onChanged={onChanged}
			/>,
		);

		const file = new File(["new image bytes"], "new-source.jpg", { type: "image/jpeg" });
		fireEvent.change(screen.getByTestId("original-source-upload-input"), {
			target: { files: [file] },
		});

		await waitFor(() => expect(screen.getByAltText("Replacement product source preview")).toBeInTheDocument());
		expect(uploadOriginalSourceCandidateMock).toHaveBeenCalledWith("product-1", file);
		expect(saveProductVisualSetupMock).not.toHaveBeenCalled();

		fireEvent.change(screen.getByTestId("original-source-reviewer"), { target: { value: "operator-1" } });
		fireEvent.change(screen.getByTestId("original-source-note"), { target: { value: "Owner confirmed the newer source." } });
		for (const testId of [
			"original-confirm-identity",
			"original-confirm-label-logo",
			"original-confirm-geometry-scale",
			"original-confirm-product-isolation",
		]) {
			fireEvent.click(screen.getByTestId(testId));
		}

		fireEvent.click(screen.getByTestId("save-original-source-reauthorization"));
		await waitFor(() => expect(saveProductVisualSetupMock).toHaveBeenCalledTimes(1));
		expect(saveProductVisualSetupMock).toHaveBeenCalledWith("product-1", {
			selected_visual: "ORIGINAL_SOURCE_REAUTHORIZE",
			reviewed_by: "operator-1",
			review_note: "Owner confirmed the newer source.",
			confirm_identity: true,
			confirm_label_logo: true,
			confirm_geometry_scale: true,
			confirm_product_isolation: true,
			expected_previous_canonical_sha256: "1".repeat(64),
			expected_replacement_sha256: "2".repeat(64),
			replacement_media_id: "new-media",
		});
		await waitFor(() => expect(onChanged).toHaveBeenCalled());
	});
});
