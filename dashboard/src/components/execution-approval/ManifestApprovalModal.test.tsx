import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/executionApproval", () => ({
  getManifest: vi.fn(),
  approveManifest: vi.fn(),
  editManifestItem: vi.fn(),
}));

import { ManifestApprovalModal } from "./ManifestApprovalModal";
import {
  approveManifest,
  editManifestItem,
  getManifest,
} from "../../api/executionApproval";
import type {
  ApprovalManifest,
  ExecutionApprovalSnapshot,
} from "../../api/executionApproval";

const mockedGet = vi.mocked(getManifest);
const mockedApprove = vi.mocked(approveManifest);
const mockedEdit = vi.mocked(editManifestItem);

function item(overrides: Partial<ExecutionApprovalSnapshot> = {}): ExecutionApprovalSnapshot {
  return {
    snapshot_id: "eas_1",
    approval_state: "REVIEW_REQUIRED",
    surface: "montage",
    logical_mode: "F2V",
    final_prompt_text: "Scene one clean prompt.",
    prompt_sha256: "aa",
    execution_envelope_sha256: "bb",
    scan_clean: 1,
    manifest_item_key: "scene_1",
    ...overrides,
  };
}

function manifest(overrides: Partial<ApprovalManifest> = {}): ApprovalManifest {
  return {
    manifest_id: "eam_1",
    surface: "montage",
    state: "REVIEW_REQUIRED",
    item_count: 2,
    items: [
      item(),
      item({ snapshot_id: "eas_2", manifest_item_key: "scene_2", final_prompt_text: "Scene two." }),
    ],
    ...overrides,
  };
}

describe("ManifestApprovalModal", () => {
  beforeEach(() => {
    mockedGet.mockReset();
    mockedApprove.mockReset();
    mockedEdit.mockReset();
  });
  afterEach(() => cleanup());

  it("loads every operation and approves the whole manifest", async () => {
    mockedGet.mockResolvedValue(manifest());
    mockedApprove.mockResolvedValue(manifest({ state: "APPROVED" }));
    const onApproved = vi.fn();
    render(
      <ManifestApprovalModal
        manifestId="eam_1"
        approvedBy="faris"
        onApproved={onApproved}
        onCancel={() => {}}
      />,
    );
    await waitFor(() => expect(screen.getAllByTestId("manifest-approval-item")).toHaveLength(2));
    fireEvent.click(screen.getByTestId("manifest-approve-all"));
    await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith("eam_1", "faris"));
    await waitFor(() => expect(onApproved).toHaveBeenCalled());
  });

  it("blocks approval when any item is not scan-clean", async () => {
    mockedGet.mockResolvedValue(
      manifest({ items: [item(), item({ snapshot_id: "eas_2", scan_clean: 0 })] }),
    );
    render(
      <ManifestApprovalModal
        manifestId="eam_1"
        approvedBy="faris"
        onApproved={() => {}}
        onCancel={() => {}}
      />,
    );
    await waitFor(() => expect(screen.getAllByTestId("manifest-approval-item")).toHaveLength(2));
    expect(screen.getByTestId("manifest-approve-all")).toBeDisabled();
    expect(mockedApprove).not.toHaveBeenCalled();
  });
});
