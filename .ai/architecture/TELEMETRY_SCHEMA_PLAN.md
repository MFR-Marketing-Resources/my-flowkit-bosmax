# Telemetry Schema Plan

## Required Header
- `request_id`
- `timestamp`
- `git_sha`
- `background_build_id`
- `content_build_id`
- `stage`
- `checkpoint`
- `status`

## Required Diagnostics
- selector or actuator used
- root context
- evidence pointer
- fail code
- first fail stage

## Failure Policy
- fail closed on missing build IDs
- fail closed on missing `request_id`
- reject reports that flatten raw telemetry into narrative-only summaries
