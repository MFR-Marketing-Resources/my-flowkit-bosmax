import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/executionApproval", () => ({
  createReviewSnapshot: vi.fn(),
  editSnapshot: vi.fn(),
  approveSnapshot: vi.fn(),
}));

import { FinalPromptApprovalModal } from "./FinalPromptApprovalModal";
import {
  approveSnapshot,
  createReviewSnapshot,
  editSnapshot,
} from "../../api/executionApproval";
import type { ExecutionApprovalSnapshot } from "../../api/executionApproval";

const mockedCreate = vi.mocked(createReviewSnapshot);
const mockedEdit = vi.mocked(editSnapshot);
const mockedApprove = vi.mocked(approveSnapshot);

function snap(overrides: Partial<ExecutionApprovalSnapshot> = {}): ExecutionApprovalSnapshot {
  return {
    snapshot_id: "eas_1",
    approval_state: "REVIEW_REQUIRED",
    surface: "hybrid",
    logical_mode: "F2V",
    final_prompt_text: "A clean provider-ready prompt.",
    prompt_sha256: "aa",
    execution_envelope_sha256: "bb",
    scan_clean: 1,
    ...overrides,
  };
}

const envelope = {
  surface: "hybrid",
  logical_mode: "F2V",
  final_prompt_text: "A clean provider-ready prompt.",
};

describe("FinalPromptApprovalModal", () => {
  beforeEach(() => {
    mockedCreate.mockReset();
    mockedEdit.mockReset();
    mockedApprove.mockReset();
  });
  afterEach(() => cleanup());

  it("loads the review prompt and approves it, returning the approved snapshot", async () => {
    mockedCreate.mockResolvedValue(snap());
    mockedApprove.mockResolvedValue(snap({ approval_state: "APPROVED" }));
    const onApproved = vi.fn();
    render(
      <FinalPromptApprovalModal
        envelope={envelope}
        approvedBy="faris"
        onApproved={onApproved}
        onCancel={() => {}}
      />,
    );
    const ta = (await screen.findByTestId(
      "final-prompt-approval-textarea",
    )) as HTMLTextAreaElement;
    await waitFor(() => expect(ta.value).toBe("A clean provider-ready prompt."));
    fireEvent.click(screen.getByTestId("final-prompt-approve-generate"));
    await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith("eas_1", "faris"));
    await waitFor(() => expect(onApproved).toHaveBeenCalled());
  });

  it("edits and re-scans before approving", async () => {
    mockedCreate.mockResolvedValue(snap());
    mockedEdit.mockResolvedValue(snap({ final_prompt_text: "edited", scan_clean: 1 }));
    mockedApprove.mockResolvedValue(snap({ approval_state: "APPROVED" }));
    render(
      <FinalPromptApprovalModal
        envelope={envelope}
        approvedBy="faris"
        onApproved={() => {}}
        onCancel={() => {}}
      />,
    );
    const ta = await screen.findByTestId("final-prompt-approval-textarea");
    fireEvent.change(ta, { target: { value: "edited" } });
    fireEvent.click(screen.getByTestId("final-prompt-approve-generate"));
    await waitFor(() => expect(mockedEdit).toHaveBeenCalledWith("eas_1", "edited", "faris"));
    await waitFor(() => expect(mockedApprove).toHaveBeenCalled());
  });

  it("blocks approval when the original prompt is not scan-clean", async () => {
    mockedCreate.mockResolvedValue(snap({ scan_clean: 0 }));
    render(
      <FinalPromptApprovalModal
        envelope={envelope}
        approvedBy="faris"
        onApproved={() => {}}
        onCancel={() => {}}
      />,
    );
    await screen.findByTestId("final-prompt-approval-scan-warning");
    expect(screen.getByTestId("final-prompt-approve-generate")).toBeDisabled();
    expect(mockedApprove).not.toHaveBeenCalled();
  });
});
