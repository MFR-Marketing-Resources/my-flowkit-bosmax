# Production Readiness Operator Action Plan

This document outlines the step-by-step workflow for the operator to approve manual products safely in batches.

## Step-by-Step Approval Workflow

1. **Review and Approve Batch 1 (Lowest Risk)**
   - **Count**: 20 products
   - **Operator Action**: Send POST claim-safe approvals for each product in Batch 1 using confirmation phrase `APPROVE_CLAIM_SAFE_COPY_REVIEW`.

2. **Review and Approve Batch 2 (Low/Medium Risk)**
   - **Count**: 50 products
   - **Operator Action**: Perform a manual copy verification of the rewrite USP/hook angles, then approve.

3. **Review and Approve Batch 3 (Remaining Low/Medium)**
   - **Count**: 103 products
   - **Operator Action**: Complete validation of the claim-safe rewrite payloads, then approve.

4. **Senior Copy Audit (High Risk)**
   - **Count**: 23 products
   - **Operator Action**: A senior copy editor must verify that no medical, supplement, or sensitive skin claims are present before approving.

5. **Resolve Image Blockers**
   - Place valid real product images for the manual products under `data/products/images/` before triggering production prompt approvals.
