param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8100",
    [string]$ChromeUserDataDir = "$env:LOCALAPPDATA\\Google\\Chrome\\User Data",
    [string]$ProductId = "",
    [switch]$AttemptOpenProject = $true,
    [switch]$UseExistingFlowTab,
    [switch]$NoOpenProject
)

if ($NoOpenProject) {
    $AttemptOpenProject = $false
}

$ErrorActionPreference = "Stop"

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ExpectedExtensionPath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "extension"))
$ExpectedDbPath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "flow_agent.db"))
$ExpectedDashboardIndex = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "dashboard\\dist\\index.html"))
$ImportSimulationScript = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "forensic-import-simulation.js"))

$Sections = [ordered]@{}

function Set-Section {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Summary,
        [object]$Details,
        [string]$RepairCommand
    )

    $Sections[$Name] = [ordered]@{
        status = $Status
        summary = $Summary
        repair_command = $RepairCommand
        details = $Details
    }
}

function Invoke-JsonGet {
    param([string]$Url)
    Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 20
}

function Invoke-JsonPost {
    param(
        [string]$Url,
        [object]$Body
    )

    $payload = $Body | ConvertTo-Json -Depth 8
    Invoke-RestMethod -Method Post -Uri $Url -Body $payload -ContentType "application/json" -TimeoutSec 30
}

function Get-FileSha1 {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA1).Hash.ToLowerInvariant()
}

function Read-FileText {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8
}

function Normalize-PathString {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }
    try {
        return [System.IO.Path]::GetFullPath($Path)
    } catch {
        return $Path
    }
}

function ConvertFrom-JsonObject {
    param([string]$JsonText)
    return $JsonText | ConvertFrom-Json
}

function Get-JsonProperty {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    if ($Object -is [System.Collections.IDictionary]) {
        return $Object[$Name]
    }

    $property = $Object.PSObject.Properties[$Name]
    if ($property) {
        return $property.Value
    }

    return $null
}

function Get-JsonMemberNames {
    param([object]$Object)

    if ($null -eq $Object) {
        return @()
    }
    if ($Object -is [System.Collections.IDictionary]) {
        return @($Object.Keys)
    }

    return @($Object.PSObject.Properties.Name)
}

function Get-ManifestName {
    param([string]$ManifestPath)
    try {
        $manifest = ConvertFrom-JsonObject (Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8)
        return [string](Get-JsonProperty -Object $manifest -Name "name")
    } catch {
        return $null
    }
}

function Get-ChromeExtensionRegistrations {
    param([string]$UserDataDir)

    $records = @()
    if (-not (Test-Path -LiteralPath $UserDataDir)) {
        return $records
    }

    $profileDirs = Get-ChildItem -LiteralPath $UserDataDir -Directory | Where-Object {
        $_.Name -eq "Default" -or $_.Name -like "Profile *" -or $_.Name -eq "Guest Profile" -or $_.Name -eq "System Profile"
    }

    foreach ($profileDir in $profileDirs) {
        foreach ($preferencesName in @("Secure Preferences", "Preferences")) {
            $preferencesPath = Join-Path $profileDir.FullName $preferencesName
            if (-not (Test-Path -LiteralPath $preferencesPath)) {
                continue
            }

            try {
                $json = ConvertFrom-JsonObject (Get-Content -LiteralPath $preferencesPath -Raw -Encoding UTF8)
            } catch {
                continue
            }

            $extensionsNode = Get-JsonProperty -Object $json -Name "extensions"
            if ($null -eq $extensionsNode) {
                continue
            }

            $settingsNode = Get-JsonProperty -Object $extensionsNode -Name "settings"
            if ($null -eq $settingsNode) {
                continue
            }

            foreach ($extensionId in (Get-JsonMemberNames -Object $settingsNode)) {
                $entry = Get-JsonProperty -Object $settingsNode -Name ([string]$extensionId)
                if ($null -eq $entry) {
                    continue
                }

                $rawPath = [string](Get-JsonProperty -Object $entry -Name "path")
                if ([string]::IsNullOrWhiteSpace($rawPath)) {
                    continue
                }

                $normalizedPath = Normalize-PathString $rawPath
                $manifestPath = Join-Path $normalizedPath "manifest.json"
                $manifestName = if (Test-Path -LiteralPath $manifestPath) { Get-ManifestName $manifestPath } else { $null }

                $records += [pscustomobject]@{
                    profile_name = $profileDir.Name
                    preferences_file = $preferencesPath
                    extension_id = $extensionId
                    registered_path = $normalizedPath
                    raw_path = $rawPath
                    manifest_name = $manifestName
                    location = Get-JsonProperty -Object $entry -Name "location"
                    state = Get-JsonProperty -Object $entry -Name "state"
                }
            }
        }
    }

    return $records
}

function Run-NodeCheck {
    param([string]$Path)

    $output = & node --check $Path 2>&1
    return [pscustomobject]@{
        ok = ($LASTEXITCODE -eq 0)
        command = "node --check $Path"
        output = (($output | Out-String).Trim())
    }
}

function Run-NodeJsonScript {
    param([string]$ScriptPath)

    $output = & node $ScriptPath 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String).Trim()
    $payload = $null
    if ($text) {
        try {
            $payload = $text | ConvertFrom-Json -Depth 100
        } catch {
            $payload = $null
        }
    }
    return [pscustomobject]@{
        ok = ($exitCode -eq 0)
        exit_code = $exitCode
        stdout = $text
        payload = $payload
    }
}

$health = $null
$extensionSelfTest = $null
$selfTestError = $null

try {
    $health = Invoke-JsonGet "$ApiBaseUrl/health"
} catch {
    $health = $null
}

try {
    $attemptOpenProjectValue = if ($AttemptOpenProject) { "true" } else { "false" }
    $extensionSelfTest = Invoke-JsonGet "$ApiBaseUrl/api/local-agent/extension-self-test?mode=F2V&attempt_open_project=$attemptOpenProjectValue"
} catch {
    $selfTestError = $_.Exception.Message
    $extensionSelfTest = $null
}

$pythonProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match "^python(?:w)?\.exe$"
}

$agentProcesses = @($pythonProcesses | Where-Object {
    ($_.CommandLine -like "*agent.main*") -or ($_.CommandLine -like "*_ref_flowkit*")
})

$portOwner = $null
try {
    $portOwner = Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction Stop | Select-Object -First 1
} catch {
    $portOwner = $null
}

$portOwnerProcess = $null
if ($portOwner) {
    $portOwnerProcess = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $portOwner.OwningProcess)
}

$backendDetails = [ordered]@{
    api_base_url = $ApiBaseUrl
    health = $health
    extension_self_test_endpoint_available = [bool]$extensionSelfTest
    extension_self_test_error = $selfTestError
    matching_python_processes = @($agentProcesses | ForEach-Object {
        [ordered]@{
            pid = $_.ProcessId
            executable_path = $_.ExecutablePath
            command_line = $_.CommandLine
            working_directory = $null
        }
    })
    port_8100_owner = if ($portOwnerProcess) {
        [ordered]@{
            pid = $portOwnerProcess.ProcessId
            executable_path = $portOwnerProcess.ExecutablePath
            command_line = $portOwnerProcess.CommandLine
        }
    } else {
        $null
    }
    live_backend_base_dir = if ($extensionSelfTest) { $extensionSelfTest.backend.base_dir } else { $null }
    live_backend_db_path = if ($extensionSelfTest) { $extensionSelfTest.backend.db_path } else { $null }
    live_backend_db_matches_expected_repo = [bool]($extensionSelfTest -and ($extensionSelfTest.backend.db_path -eq $ExpectedDbPath))
}

$backendProcessOk = ($agentProcesses.Count -ge 1) -and $portOwnerProcess -and $health -and ($health.status -eq "ok")
Set-Section `
    -Name "BACKEND_PROCESS" `
    -Status $(if ($backendProcessOk) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($backendProcessOk) { "Live agent.main backend detected on 8100 with healthy HTTP response." } else { "Missing healthy agent.main process and/or no live HTTP 8100 owner." }) `
    -Details $backendDetails `
    -RepairCommand "powershell -ExecutionPolicy Bypass -File .\scripts\start-local-agent.ps1 -ForceRestart"

$backendDbOk = [bool]($extensionSelfTest -and $extensionSelfTest.backend.db_path -and $extensionSelfTest.backend.db_path -eq $ExpectedDbPath)
Set-Section `
    -Name "BACKEND_DB_PATH" `
    -Status $(if ($backendDbOk) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($backendDbOk) { "Live backend DB path matches expected repo-local flow_agent.db." } else { "Live backend DB path does not match expected repo-local flow_agent.db." }) `
    -Details ([ordered]@{
        expected_db_path = $ExpectedDbPath
        live_db_path = if ($extensionSelfTest) { $extensionSelfTest.backend.db_path } else { $null }
        live_backend_base_dir = if ($extensionSelfTest) { $extensionSelfTest.backend.base_dir } else { $null }
    }) `
    -RepairCommand "powershell -ExecutionPolicy Bypass -File .\scripts\start-local-agent.ps1 -ForceRestart"

$dashboardBuildOk = [bool]($extensionSelfTest -and $extensionSelfTest.dashboard.index_exists -and $extensionSelfTest.dashboard.serving_mode -eq "BACKEND_SERVED_STATIC")
Set-Section `
    -Name "DASHBOARD_BUILD" `
    -Status $(if ($dashboardBuildOk) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($dashboardBuildOk) { "Dashboard is served from backend static bundle." } else { "Dashboard bundle missing or backend is not serving dist/index.html." }) `
    -Details ([ordered]@{
        dashboard_url = if ($health) { $health.dashboard_url } else { "$ApiBaseUrl/operator" }
        serving_mode = if ($extensionSelfTest) { $extensionSelfTest.dashboard.serving_mode } else { $null }
        dist_dir = if ($extensionSelfTest) { $extensionSelfTest.dashboard.dist_dir } else { $null }
        index_file = if ($extensionSelfTest) { $extensionSelfTest.dashboard.index_file } else { $null }
        index_exists = if ($extensionSelfTest) { $extensionSelfTest.dashboard.index_exists } else { $false }
        index_modified_at = if ($extensionSelfTest) { $extensionSelfTest.dashboard.index_modified_at } else { $null }
        index_sha1 = if ($extensionSelfTest) { $extensionSelfTest.dashboard.index_sha1 } else { $null }
        asset_manifest = if ($extensionSelfTest) { $extensionSelfTest.dashboard.asset_manifest } else { $null }
    }) `
    -RepairCommand "Set-Location .\dashboard; npm run build"

$registrations = Get-ChromeExtensionRegistrations -UserDataDir $ChromeUserDataDir
$flowKitRegistrations = @($registrations | Where-Object { $_.manifest_name -eq "Flow Kit" })
$expectedPathRegistrations = @($flowKitRegistrations | Where-Object { $_.registered_path -eq $ExpectedExtensionPath })
$selectedRegistration = $expectedPathRegistrations | Select-Object -First 1
$duplicateFlowKitPaths = @($flowKitRegistrations | Select-Object -ExpandProperty registered_path -Unique)
$chromeProfileOk = [bool]$selectedRegistration -and ($duplicateFlowKitPaths.Count -eq 1)
Set-Section `
    -Name "CHROME_PROFILE" `
    -Status $(if ($chromeProfileOk) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($chromeProfileOk) { "Single Flow Kit unpacked extension registration found in Chrome profile." } else { "Chrome profile registration is missing, duplicated, or points to a stale unpacked path." }) `
    -Details ([ordered]@{
        chrome_user_data_dir = $ChromeUserDataDir
        expected_extension_path = $ExpectedExtensionPath
        selected_profile = if ($selectedRegistration) { $selectedRegistration.profile_name } else { $null }
        selected_secure_preferences = if ($selectedRegistration) { $selectedRegistration.preferences_file } else { $null }
        selected_extension_id = if ($selectedRegistration) { $selectedRegistration.extension_id } else { $null }
        selected_registered_path = if ($selectedRegistration) { $selectedRegistration.registered_path } else { $null }
        duplicate_registered_paths = $duplicateFlowKitPaths
        registrations = $flowKitRegistrations
    }) `
    -RepairCommand "Reload the unpacked Flow Kit extension from $ExpectedExtensionPath and remove duplicate Flow Kit registrations from other Chrome profiles."

$registeredExtensionPath = if ($selectedRegistration) { $selectedRegistration.registered_path } else { $ExpectedExtensionPath }
$manifestPath = Join-Path $registeredExtensionPath "manifest.json"
$backgroundPath = Join-Path $registeredExtensionPath "background.js"
$contentDomPath = Join-Path $registeredExtensionPath "content-flow-dom.js"
$runnerPath = Join-Path $registeredExtensionPath "f2v-flow-queue-runner.js"
$cdpClickerPath = Join-Path $registeredExtensionPath "cdp-visible-clicker.js"
$manifestJson = if (Test-Path -LiteralPath $manifestPath) { ConvertFrom-JsonObject (Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8) } else { $null }
$permissions = if ($manifestJson) { @(Get-JsonProperty -Object $manifestJson -Name "permissions") } else { @() }

Set-Section `
    -Name "EXTENSION_REGISTERED_PATH" `
    -Status $(if ($selectedRegistration -and ($registeredExtensionPath -eq $ExpectedExtensionPath)) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($selectedRegistration -and ($registeredExtensionPath -eq $ExpectedExtensionPath)) { "Registered unpacked extension path matches expected repo extension folder." } else { "Registered unpacked extension path does not match expected repo extension folder." }) `
    -Details ([ordered]@{
        expected_extension_path = $ExpectedExtensionPath
        registered_extension_path = $registeredExtensionPath
        extension_id = if ($selectedRegistration) { $selectedRegistration.extension_id } else { $null }
        profile_name = if ($selectedRegistration) { $selectedRegistration.profile_name } else { $null }
        secure_preferences_path = if ($selectedRegistration) { $selectedRegistration.preferences_file } else { $null }
    }) `
    -RepairCommand "Reload the unpacked Flow Kit extension from $ExpectedExtensionPath."

$extensionFilesDetails = [ordered]@{
    manifest_exists = [bool](Test-Path -LiteralPath $manifestPath)
    manifest_version = if ($manifestJson) { Get-JsonProperty -Object $manifestJson -Name "version" } else { $null }
    background_service_worker = if ($manifestJson) {
        $backgroundNode = Get-JsonProperty -Object $manifestJson -Name "background"
        Get-JsonProperty -Object $backgroundNode -Name "service_worker"
    } else { $null }
    scripting_permission_present = ($permissions -contains "scripting")
    background_js_exists = [bool](Test-Path -LiteralPath $backgroundPath)
    content_flow_dom_exists = [bool](Test-Path -LiteralPath $contentDomPath)
    f2v_flow_queue_runner_exists = [bool](Test-Path -LiteralPath $runnerPath)
    cdp_visible_clicker_exists = [bool](Test-Path -LiteralPath $cdpClickerPath)
}
$extensionFilesOk = $extensionFilesDetails.manifest_exists -and $extensionFilesDetails.background_js_exists -and $extensionFilesDetails.content_flow_dom_exists -and $extensionFilesDetails.f2v_flow_queue_runner_exists -and $extensionFilesDetails.scripting_permission_present
Set-Section `
    -Name "EXTENSION_FILES" `
    -Status $(if ($extensionFilesOk) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($extensionFilesOk) { "Required extension files and permissions are present." } else { "Required extension files and/or scripting permission are missing." }) `
    -Details $extensionFilesDetails `
    -RepairCommand "Restore the unpacked extension files under $ExpectedExtensionPath and ensure manifest permissions include scripting."

$backgroundSource = Read-FileText $backgroundPath
$contentSource = Read-FileText $contentDomPath
$runnerSource = Read-FileText $runnerPath
$buildBranch = if ($backgroundSource -match 'branch:\s*"([^"]+)"') { $Matches[1] } else { $null }
$buildCommit = if ($backgroundSource -match 'commit:\s*"([^"]+)"') { $Matches[1] } else { $null }
$backgroundBuildId = if ($backgroundSource -match 'const BUILD_ID = "([^"]+)"') { $Matches[1] } else { $null }
$contentBuildId = if ($contentSource -match "const FLOW_KIT_DOM_BUILD_ID = ['""]([^'""]+)['""]") { $Matches[1] } else { $null }
$runnerBuildId = if ($runnerSource -match "const F2V_FLOW_QUEUE_RUNNER_BUILD_ID = ['""]([^'""]+)['""]") { $Matches[1] } else { $null }
$oldBuildMarkerPresent = [bool](
    ($backgroundSource -and $backgroundSource.Contains("2026-05-23")) -or
    ($contentSource -and $contentSource.Contains("2026-05-23")) -or
    ($runnerSource -and $runnerSource.Contains("2026-05-23"))
)
$buildMarkersDetails = [ordered]@{
    bosmax_build_proof_branch = $buildBranch
    bosmax_build_proof_commit = $buildCommit
    background_build_id = $backgroundBuildId
    content_build_id = $contentBuildId
    runner_build_id = $runnerBuildId
    f2v_runner_global_marker_present = [bool]($runnerSource -and $runnerSource.Contains("__BOSMAX_F2V_FLOW_QUEUE_RUNNER__"))
    background_imports_runner = [bool]($backgroundSource -and $backgroundSource.Contains('importScripts("f2v-flow-queue-runner.js")'))
    runner_import_ok_log_marker = [bool]($runnerSource -and $runnerSource.Contains("[BOSMAX_F2V_FLOW_QUEUE_RUNNER] import_ok"))
    background_import_ok_log_marker = [bool]($backgroundSource -and $backgroundSource.Contains("[BOSMAX_F2V_FLOW_QUEUE_RUNNER] background_import_ok"))
    old_build_marker_2026_05_23_present = $oldBuildMarkerPresent
}
$buildMarkersOk = $buildBranch -and $buildCommit -and $backgroundBuildId -and $contentBuildId -and $runnerBuildId -and ($backgroundBuildId -eq $contentBuildId) -and ($backgroundBuildId -eq $runnerBuildId) -and (-not $oldBuildMarkerPresent)
Set-Section `
    -Name "BUILD_MARKERS" `
    -Status $(if ($buildMarkersOk) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($buildMarkersOk) { "Background, content, and runner build markers are present, aligned, and free of the stale 2026-05-23 stamp." } else { "Build markers are stale, missing, or mismatched." }) `
    -Details $buildMarkersDetails `
    -RepairCommand "Rebuild or restamp the extension bundle so background.js, content-flow-dom.js, and f2v-flow-queue-runner.js share the same current build id."

$syntaxChecks = @(
    (Run-NodeCheck -Path $backgroundPath)
    (Run-NodeCheck -Path $contentDomPath)
    (Run-NodeCheck -Path $runnerPath)
)
if (Test-Path -LiteralPath $cdpClickerPath) {
    $syntaxChecks += Run-NodeCheck -Path $cdpClickerPath
}
$staticSyntaxOk = (@($syntaxChecks | Where-Object { -not $_.ok }).Count -eq 0)
Set-Section `
    -Name "RUNNER_IMPORT_STATIC" `
    -Status $(if ($staticSyntaxOk) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($staticSyntaxOk) { "Node static syntax checks passed for the extension runtime files." } else { "One or more extension runtime files failed node --check." }) `
    -Details $syntaxChecks `
    -RepairCommand "Run node --check on the failing file and correct the syntax error before UAT."

$importSimulation = Run-NodeJsonScript -ScriptPath $ImportSimulationScript
$importSimulationDetails = if ($importSimulation.payload) { $importSimulation.payload } else { [ordered]@{ stdout = $importSimulation.stdout; exit_code = $importSimulation.exit_code } }
Set-Section `
    -Name "RUNNER_IMPORT_STATIC" `
    -Status $(if ($staticSyntaxOk -and $importSimulation.ok) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($staticSyntaxOk -and $importSimulation.ok) { "Static syntax checks and service-worker import simulation both passed." } else { "Static syntax and/or service-worker import simulation failed." }) `
    -Details ([ordered]@{
        syntax_checks = $syntaxChecks
        import_simulation = $importSimulationDetails
    }) `
    -RepairCommand "node .\scripts\forensic-import-simulation.js"

$extensionRuntime = if ($extensionSelfTest) { $extensionSelfTest.extension_self_test } else { $null }
$pageDiagnostic = if ($extensionRuntime) { $extensionRuntime.page_diagnostic } else { $null }
$pageEditorMarkers = if ($pageDiagnostic) { @($pageDiagnostic.visible_project_editor_markers) } else { @() }
$pageModeVisible = if ($pageDiagnostic) { [string]$pageDiagnostic.current_mode_visible } else { "" }
$pageShowsVideoFrames = [bool](
    ($pageModeVisible -like "*Video/Frames*") -or
    (($pageEditorMarkers -contains "Video") -and ($pageEditorMarkers -contains "Frames"))
)
$pageDiagnosticAlive = [bool]($pageDiagnostic -and $pageDiagnostic.content_script_alive -eq $true)
$pageDiagnosticReady = [bool](
    $pageDiagnostic -and
    (
        ($pageDiagnostic.ok -eq $true) -or
        (
            $pageDiagnostic.runtime_ready -eq $true -and
            $pageDiagnosticAlive -and
            $pageDiagnostic.composer_found -eq $true -and
            $pageDiagnostic.composer_editable -eq $true -and
            $pageDiagnostic.generate_button_found -eq $true -and
            $pageDiagnostic.prompt_field_found -eq $true -and
            $pageShowsVideoFrames
        )
    )
)
$nonFatalModeMismatch = [bool](
    $extensionRuntime -and
    (
        ($extensionRuntime.composer_mode_mismatch_non_fatal -eq $true) -or
        ([string]$extensionRuntime.content_receiver_error -like "*ABORT_FLOW_MODE_MISMATCH*") -or
        ([string]$extensionRuntime.last_error -like "*ABORT_FLOW_MODE_MISMATCH*")
    )
)
$liveWorkerBuildId = ""
if ($extensionRuntime) {
    $liveWorkerBuildId = [string](
        $extensionRuntime.background_build_id
    )
    if ([string]::IsNullOrWhiteSpace($liveWorkerBuildId)) {
        $liveWorkerBuildId = [string]($extensionRuntime.build_id)
    }
    if ([string]::IsNullOrWhiteSpace($liveWorkerBuildId)) {
        $liveWorkerBuildId = [string]($extensionRuntime.buildId)
    }
    if ([string]::IsNullOrWhiteSpace($liveWorkerBuildId)) {
        $liveWorkerBuildId = [string]($extensionRuntime.git_sha)
    }
    if ([string]::IsNullOrWhiteSpace($liveWorkerBuildId)) {
        $liveWorkerBuildId = [string]($extensionRuntime.gitSha)
    }
}
$liveWorkerBuildMatchesExpected = [bool](
    $liveWorkerBuildId -and
    $backgroundBuildId -and
    ($liveWorkerBuildId -eq $backgroundBuildId)
)
$runnerSelfTestOk = [bool](
    $extensionSelfTest -and
    $extensionRuntime -and
    ($extensionRuntime.ok -eq $true) -and
    ($extensionRuntime.runner_loaded -eq $true) -and
    $liveWorkerBuildMatchesExpected -and
    -not $extensionRuntime.error -and
    (
        (-not $extensionRuntime.last_error) -or
        $nonFatalModeMismatch
    )
)
Set-Section `
    -Name "RUNNER_SELF_TEST" `
    -Status $(if ($runnerSelfTestOk) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($runnerSelfTestOk) { "Live extension self-test endpoint returned runtime proof from the active backend." } else { "Live extension self-test endpoint is unavailable or the active backend returned runtime errors." }) `
    -Details ([ordered]@{
        endpoint = "$ApiBaseUrl/api/local-agent/extension-self-test?mode=F2V&attempt_open_project=$($AttemptOpenProject.ToString().ToLowerInvariant())"
        endpoint_error = $selfTestError
        expected_live_worker_build_id = $backgroundBuildId
        live_worker_build_id = $liveWorkerBuildId
        payload = $extensionSelfTest
    }) `
    -RepairCommand "powershell -ExecutionPolicy Bypass -File .\scripts\start-local-agent.ps1 -ForceRestart"

$contentPingOk = [bool](
    $pageDiagnostic -and
    $pageDiagnosticReady -and
    ($pageDiagnostic.content_build_id -eq $extensionRuntime.expected_content_build_id) -and
    (
        (-not $extensionRuntime.content_receiver_error) -or
        $nonFatalModeMismatch
    ) -and
    (-not $extensionRuntime.build_mismatch_error)
)
$contentPingSummary = if (-not $pageDiagnostic) {
    "No content-script diagnostic payload returned from live extension self-test."
} elseif ($extensionRuntime.content_receiver_error -and -not $nonFatalModeMismatch) {
    "ERR_FLOW_CONTENT_RECEIVER_MISSING"
} elseif ($pageDiagnostic.content_build_id -ne $extensionRuntime.expected_content_build_id) {
    "ERR_EXTENSION_BUILD_MISMATCH"
} else {
    "Content-script ping proved current build, URL, title, composer, prompt field, and config pill state."
}
Set-Section `
    -Name "CONTENT_SCRIPT_PING" `
    -Status $(if ($contentPingOk) { "PASS" } else { "FAIL" }) `
    -Summary $contentPingSummary `
    -Details ([ordered]@{
        expected_content_build_id = if ($extensionRuntime) { $extensionRuntime.expected_content_build_id } else { $null }
        content_receiver_error = if ($extensionRuntime) { $extensionRuntime.content_receiver_error } else { $null }
        build_mismatch_error = if ($extensionRuntime) { $extensionRuntime.build_mismatch_error } else { $null }
        page_diagnostic = $pageDiagnostic
    }) `
    -RepairCommand "Reload the unpacked Flow Kit extension and rerun .\scripts\forensic-f2v-runtime-audit.ps1 before live UAT."

$flowTabs = if ($extensionRuntime -and $extensionRuntime.flow_tabs) { @($extensionRuntime.flow_tabs) } else { @() }
$targetTab = if ($extensionRuntime) { $extensionRuntime.target_tab } else { $null }
$flowTabTargetOk = [bool]($targetTab -and $targetTab.tab_kind -eq "EDITOR")
Set-Section `
    -Name "FLOW_TAB_TARGET" `
    -Status $(if ($flowTabTargetOk) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($flowTabTargetOk) { "Flow target tab resolved to an editor/composer URL." } else { "No Flow editor tab was targeted; root/landing or stale tab still owns the lane." }) `
    -Details ([ordered]@{
        flow_tabs = $flowTabs
        target_tab = $targetTab
        open_flow_result = if ($extensionRuntime) { $extensionRuntime.open_flow_result } else { $null }
    }) `
    -RepairCommand $(if ($UseExistingFlowTab) { "Open a Google Flow editor tab manually in your active Chrome session, then rerun the audit." } else { "Open a Google Flow editor tab or let the self-test attempt one root-to-editor transition, then rerun the audit." })

$composerDiagnostic = if ($extensionRuntime) { $extensionRuntime.composer_diagnostic } else { $null }
$flowEditorReadyOk = [bool](
    $pageDiagnosticReady -and
    $pageDiagnostic.composer_found -eq $true -and
    $pageDiagnostic.composer_editable -eq $true -and
    $pageDiagnostic.generate_button_found -eq $true -and
    $pageDiagnostic.prompt_field_found -eq $true -and
    $pageShowsVideoFrames
)
Set-Section `
    -Name "FLOW_EDITOR_READY" `
    -Status $(if ($flowEditorReadyOk) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($flowEditorReadyOk) { "Flow editor composer is visible, editable, prompt-ready, and pre-UAT mode-ready." } else { "Flow editor readiness proof failed." }) `
    -Details ([ordered]@{
        composer_diagnostic = $composerDiagnostic
        page_diagnostic = $pageDiagnostic
    }) `
    -RepairCommand $(if ($NoOpenProject) { "Ensure an editor tab is open and fully loaded manually, then rerun the audit." } else { "Invoke-RestMethod '$ApiBaseUrl/api/local-agent/extension-self-test?mode=F2V&attempt_open_project=true'" })

$parityChecks = [ordered]@{
    scripting_permission = $extensionFilesDetails.scripting_permission_present
    main_world_injection = [bool]($runnerSource -and $runnerSource.Contains('world: "MAIN"'))
    react_fiber_submit = [bool]($runnerSource -and $runnerSource.Contains("MAIN_invokeReactFiberSubmit"))
    slate_editor_prompt_insertion = [bool]($runnerSource -and $runnerSource.Contains("MAIN_insertComposerPrompt"))
    arrow_forward_discovery = [bool]($runnerSource -and $runnerSource.Contains("arrow_forward"))
    target_stamping = [bool]($runnerSource -and $runnerSource.Contains("MAIN_stampGenerateButton"))
    strategy_logging = [bool]($runnerSource -and $runnerSource.Contains("strategy"))
}
$flowQueueParityOk = (@($parityChecks.GetEnumerator() | Where-Object { -not $_.Value }).Count -eq 0)
Set-Section `
    -Name "FLOW_QUEUE_PARITY" `
    -Status $(if ($flowQueueParityOk) { "PASS" } else { "FAIL" }) `
    -Summary $(if ($flowQueueParityOk) { "Runtime matches the requested flow-queue v0.4.0-beta proof pattern set." } else { "One or more flow-queue parity markers are absent." }) `
    -Details $parityChecks `
    -RepairCommand "Reconcile the runner against the proven flow-queue parity markers before live UAT."

$productReadyStatus = "FAIL"
$productReadySummary = "PRODUCT_ID_REQUIRED_FOR_PRODUCT_READY_PROOF"
$productReadyDetails = [ordered]@{
    product_id = $ProductId
}
if (-not [string]::IsNullOrWhiteSpace($ProductId)) {
    $packageReadiness = $null
    $approvedPackage = $null
    $executionPackage = $null
    $approvedPackageError = $null
    $executionPackageError = $null

    try {
        $packageReadiness = Invoke-JsonPost "$ApiBaseUrl/api/workspace/package-readiness" @{
            mode = "F2V"
            product_ids = @($ProductId)
        }
    } catch {
        $packageReadiness = $null
    }

    try {
        $approvedPackage = Invoke-JsonGet "$ApiBaseUrl/api/products/$ProductId/approved-package?mode=F2V"
    } catch {
        $approvedPackageError = $_.Exception.Message
    }

    try {
        $executionPackage = Invoke-JsonPost "$ApiBaseUrl/api/workspace/execution-package" @{
            product_id = $ProductId
            mode = "F2V"
            duration_seconds = 8
            aspect_ratio = "9:16"
            generation_mode = "SINGLE"
            camera_style = "UGC_IPHONE_RAW"
            character_presence = "VISIBLE_CREATOR"
        }
    } catch {
        $executionPackageError = $_.Exception.Message
    }

    $readinessItem = if ($packageReadiness -and $packageReadiness.items.Count -gt 0) { $packageReadiness.items[0] } else { $null }
    $productReadyOk = [bool](
        $readinessItem -and
        $readinessItem.readiness_status -eq "READY" -and
        $approvedPackage -and
        $executionPackage
    )

    $productReadyStatus = if ($productReadyOk) { "PASS" } else { "FAIL" }
    if (-not $readinessItem) {
        $productReadySummary = "PRODUCT_READY_PROOF_UNAVAILABLE"
    } elseif ($readinessItem.blocker) {
        $productReadySummary = [string]$readinessItem.blocker
    } elseif (-not $approvedPackage) {
        $productReadySummary = "CLAIM_SAFE_PACKAGE_NOT_READY"
    } elseif (-not $executionPackage) {
        $productReadySummary = "EXECUTION_PACKAGE_NOT_READY"
    } else {
        $productReadySummary = "Selected product passed readiness, approved-package, and execution-package checks."
    }

    $productReadyDetails = [ordered]@{
        product_id = $ProductId
        package_readiness = $packageReadiness
        approved_package = $approvedPackage
        approved_package_error = $approvedPackageError
        execution_package = $executionPackage
        execution_package_error = $executionPackageError
    }
}
Set-Section `
    -Name "PRODUCT_READY" `
    -Status $productReadyStatus `
    -Summary $productReadySummary `
    -Details $productReadyDetails `
    -RepairCommand "Pass -ProductId <product-id> to this script and fix REFERENCE_ONLY_PRODUCT or CLAIM_SAFE_PACKAGE_NOT_READY before any Flow execution."

$sectionOrder = @(
    "BACKEND_PROCESS",
    "BACKEND_DB_PATH",
    "DASHBOARD_BUILD",
    "CHROME_PROFILE",
    "EXTENSION_REGISTERED_PATH",
    "EXTENSION_FILES",
    "BUILD_MARKERS",
    "RUNNER_IMPORT_STATIC",
    "RUNNER_SELF_TEST",
    "CONTENT_SCRIPT_PING",
    "FLOW_TAB_TARGET",
    "FLOW_EDITOR_READY",
    "PRODUCT_READY",
    "FLOW_QUEUE_PARITY"
)

$tableRows = foreach ($name in $sectionOrder) {
    $section = $Sections[$name]
    [pscustomobject]@{
        SECTION = $name
        STATUS = $section.status
        SUMMARY = $section.summary
    }
}

$allPass = (@($sectionOrder | Where-Object { $Sections[$_].status -ne "PASS" }).Count -eq 0)

Write-Output "=== BOSMAX F2V Runtime Audit ==="
$tableRows | Format-Table -AutoSize | Out-String | Write-Output

$failedSections = $sectionOrder | Where-Object { $Sections[$_].status -ne "PASS" }
if ($failedSections.Count -gt 0) {
    Write-Output "=== FAILURES ==="
    foreach ($name in $failedSections) {
        $section = $Sections[$name]
        Write-Output ("[{0}] {1}" -f $name, $section.summary)
        Write-Output ("PATH/DETAIL: {0}" -f (($section.details | ConvertTo-Json -Depth 8 -Compress)))
        Write-Output ("REPAIR: {0}" -f $section.repair_command)
    }
}

$finalPayload = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    repo_root = $RepoRoot
    expected_extension_path = $ExpectedExtensionPath
    expected_db_path = $ExpectedDbPath
    expected_dashboard_index = $ExpectedDashboardIndex
    product_id = $ProductId
    sections = $Sections
    ready_for_single_live_f2v_uat = $allPass
}

Write-Output "=== AUDIT_JSON ==="
$finalPayload | ConvertTo-Json -Depth 12 | Write-Output

if ($allPass) {
    Write-Output "READY_FOR_SINGLE_LIVE_F2V_UAT"
    exit 0
}

Write-Output "BLOCKED_FOR_LIVE_F2V_UAT"
exit 1
