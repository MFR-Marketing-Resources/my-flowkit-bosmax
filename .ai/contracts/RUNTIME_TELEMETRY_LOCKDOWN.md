# Runtime Telemetry Lockdown

## Mandatory Runtime Handshake
- Background build ID and content build ID must match.
- The content script must prove `RUNTIME_READY`.
- Stale or orphaned content scripts must be detected and rejected.

## Mandatory Telemetry Header
- `request_id`
- `timestamp`
- `git_sha`
- `background_build_id`
- `content_build_id`
- `stage`
- `checkpoint`
- `status`

## Mandatory Failure Context
- selector or actuator used
- DOM or screenshot evidence pointer when applicable
- explicit fail code
- exact first failing stage

## Hard Rejections
- `REQUEST_ID=N/A`
- `build=legacy`
- pass-stage claims without raw telemetry
- screenshots without telemetry
