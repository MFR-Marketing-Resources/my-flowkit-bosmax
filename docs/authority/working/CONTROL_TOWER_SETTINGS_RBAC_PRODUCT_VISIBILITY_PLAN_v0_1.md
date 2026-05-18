# CONTROL TOWER SETTINGS RBAC PRODUCT VISIBILITY PLAN v0.1

## 1. Document Control

| Field | Value |
| --- | --- |
| `file_id` | `CONTROL_TOWER_SETTINGS_RBAC_PRODUCT_VISIBILITY_PLAN` |
| `version` | `v0.1` |
| `status` | `APPROVED_FOR_IMPLEMENTATION_PLANNING` |
| `implementation_status` | `NO_IMPLEMENTATION_INSIDE_THIS_FILE` |
| `repo` | `farisdatosheikh/my-flowkit-bosmax` |
| `decision_source` | `User Control Tower requirement + Issue #71` |

## 2. Executive Decision

The future system governance wave is:

```text
CONTROL_TOWER_SETTINGS_RBAC_PRODUCT_VISIBILITY
```

Purpose:

Create an admin-managed Control Tower where system owner and admins can
update logic, config, users, and product visibility without requiring
code changes.

## 3. Current Problem

Prompt compiler settings, durations, character library, camera shots,
product display eligibility, and user or page access are not yet
managed through admin UI.

This creates:

1. maintenance dependency on Codex and coding
1. slow policy iteration
1. weak operational governance
1. unsafe access risk when non-owner users can reach product
   registration, settings, or broader system controls

## 4. Control Tower Sections

### A. Prompt Compiler Settings

1. generation modes
1. durations
1. WPS policy
1. shot count policy
1. camera styles
1. target languages
1. engine and mode capability

### B. Character and Persona Library

1. name
1. persona archetype
1. age range
1. gender or presentation where relevant
1. wardrobe
1. speaking tone
1. language style
1. continuity notes
1. allowed product categories and silos
1. active or archive status

### C. Camera and Shot Library

1. `UGC_IPHONE_RAW`
1. `CINEMATIC_PRO`
1. `CU / MCU / medium / wide / product close-up`
1. lens equivalent
1. motion or jitter
1. lighting
1. shot-count presets
1. active or archive status

### D. Product Content Eligibility and Visibility

1. `content_enabled`
1. allowed modes `T2V / F2V / I2V / IMG`
1. product visibility by role
1. approved package readiness
1. claim-safe readiness
1. image readiness
1. lifecycle status
1. blocked reason
1. display or hide in workspace

### E. User Management

1. invite or register user by email
1. phone number
1. approval by admin
1. deactivate or reactivate
1. assign role
1. view status

### F. RBAC and Roles

Defined roles:

1. `OWNER / SUPER_ADMIN`
1. `ADMIN`
1. `EDITOR / MANAGER`
1. `AUTHOR`
1. `CONTRIBUTOR`
1. `SUBSCRIBER`
1. `VIEWER / REPORT_VIEWER`

Role baseline:

1. `OWNER / SUPER_ADMIN` has full access
1. `ADMIN` manages products, settings, users, and reports
1. `EDITOR / MANAGER` reviews and approves content or products
1. `AUTHOR` creates content from approved products and config only
1. `CONTRIBUTOR` drafts content only where workflow requires approval
1. `SUBSCRIBER` has limited subscription or premium access
1. `VIEWER / REPORT_VIEWER` has reports-only access

### G. Page Permission Matrix

The future wave must define page access for each role.

Example `AUTHOR / SUBSCRIBER` allowed:

1. Workspace `T2V`
1. Workspace `F2V`
1. Workspace `I2V`
1. Workspace `IMG`
1. TikTokShop product link intake if enabled
1. display reports if allowed

Example `AUTHOR / SUBSCRIBER` forbidden:

1. Smart Registration
1. canonical product editor
1. Control Tower settings
1. user management
1. role management
1. product delete or purge
1. system config

### H. Data Lifecycle

Each Control Tower managed entity should support:

1. add
1. edit
1. archive
1. unarchive or reactivate
1. purge only where safe and role-authorized

Purge must remain restricted.

### I. Subscription-Readiness

Prepare for future subscription support:

1. subscriber role
1. account approval and deactivation
1. page-level access
1. content-generation permissions
1. product visibility by role
1. report access limits

Explicitly out of scope:

1. payment processing
1. billing integration
1. subscription checkout

## 5. Relationship to UGC Compiler Wave

1. UGC compiler wave may use central config or service now
1. Control Tower future wave will make that config editable
1. current UGC implementation must not be blocked waiting for full
   Control Tower UI
1. compiler settings must not be scattered in code in a way that cannot
   later move to Control Tower

## 6. Source-of-Truth Decision

Future Control Tower truth should own:

1. prompt compiler config
1. character library
1. camera and shot library
1. product content eligibility
1. role and permission matrix
1. user lifecycle

## 7. Out of Scope

1. payment or subscription billing
1. Google Flow DOM
1. Chrome extension runtime
1. prompt compiler implementation itself
1. product scraper implementation
1. broad marketplace scraping
1. result download or import automation

## 8. Acceptance Criteria for Future Implementation

1. Admin can manage compiler settings
1. Admin can manage character and persona library
1. Admin can manage camera and shot library
1. Admin can control product display eligibility
1. Admin can invite, approve, and deactivate users
1. Admin can assign roles
1. Page access respects role permissions
1. Authors cannot access product registration, settings, or system config
1. Subscribers have limited access
1. Product visibility affects workspace product selector
1. Archive and unarchive work for managed settings
1. Purge is restricted

## 9. Validation Matrix for Future Implementation

1. backend settings service tests
1. RBAC permission tests
1. page route guard tests
1. product visibility tests
1. role matrix UI tests
1. Control Tower CRUD tests
1. dashboard build
1. `npx tsx scripts/mandor-check.ts`
1. changed-file `npx @biomejs/biome check`
1. scoped `npx depcruise`

## 10. Final Delivery Report Format for Future PR

Future implementation PR must report:

```text
# STATUS
# BASELINE
# PLANNING_AUTHORITY
# CONTROL_TOWER_SUMMARY
# RBAC_PROOF
# PRODUCT_VISIBILITY_PROOF
# COMPILER_SETTINGS_PROOF
# USER_MANAGEMENT_PROOF
# VALIDATION_RESULTS
# CHANGED_FILES
# PR
# MERGE_READINESS
```
