# Same-Session Chrome Flow Repair Script
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ExpectedExtensionPath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "extension"))
$ExpectedBuildMarker = "flowkit-f2v-runner-audit-2026-05-28b"
$ApiBaseUrl = "http://127.0.0.1:8100"

Write-Output "=== BOSMAX Same-Session Chrome Flow Repair ==="

# 1. Discover active Chrome instances, user-data-dir, and profile
$chromeProcesses = @(Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" -ErrorAction SilentlyContinue)
$discoveredUserDataDir = $null
$discoveredProfile = $null

foreach ($proc in $chromeProcesses) {
    $cmdLine = $proc.CommandLine
    if ($cmdLine) {
        if ($cmdLine -match '"--user-data-dir=([^"]+)"') {
            $discoveredUserDataDir = $Matches[1]
        } elseif ($cmdLine -match '--user-data-dir="([^"]+)"') {
            $discoveredUserDataDir = $Matches[1]
        } elseif ($cmdLine -match '--user-data-dir=([^\s]+)') {
            $discoveredUserDataDir = $Matches[1]
        }
        if ($cmdLine -match '"--profile-directory=([^"]+)"') {
            $discoveredProfile = $Matches[1]
        } elseif ($cmdLine -match '--profile-directory="([^"]+)"') {
            $discoveredProfile = $Matches[1]
        } elseif ($cmdLine -match '--profile-directory=([^\s]+)') {
            $discoveredProfile = $Matches[1]
        }
    }
    if ($discoveredUserDataDir -and $discoveredProfile) {
        break
    }
}

if (-not $discoveredUserDataDir) {
    $discoveredUserDataDir = "$env:LOCALAPPDATA\Google\Chrome\User Data"
    Write-Output "No active Chrome user-data-dir arg discovered. Defaulting to standard: $discoveredUserDataDir"
} else {
    Write-Output "Discovered active Chrome User Data Dir: $discoveredUserDataDir"
}

function Get-JsonProperty {
    param(
        [object]$Object,
        [string]$Name
    )
    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary]) {
        return $Object[$Name]
    }
    try {
        $property = $Object.PSObject.Properties[$Name]
        if ($property) {
            return $property.Value
        }
    } catch {}
    return $null
}

# Helper to find registrations
function Get-AllFlowKitRegistrations {
    param([string]$UserDataDir)
    $records = @()
    if (-not (Test-Path -LiteralPath $UserDataDir)) { return $records }
    $profileDirs = Get-ChildItem -LiteralPath $UserDataDir -Directory | Where-Object {
        $_.Name -eq "Default" -or $_.Name -like "Profile *" -or $_.Name -eq "Guest Profile" -or $_.Name -eq "System Profile"
    }
    foreach ($pDir in $profileDirs) {
        foreach ($preferencesName in @("Secure Preferences", "Preferences")) {
            $preferencesPath = Join-Path $pDir.FullName $preferencesName
            if (-not (Test-Path -LiteralPath $preferencesPath)) { continue }
            try {
                $json = Get-Content -LiteralPath $preferencesPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $extensionsNode = Get-JsonProperty -Object $json -Name "extensions"
                if ($null -eq $extensionsNode) { continue }
                $settingsNode = Get-JsonProperty -Object $extensionsNode -Name "settings"
                if ($null -eq $settingsNode) { continue }
                foreach ($property in $settingsNode.PSObject.Properties) {
                    $entry = $property.Value
                    if ($null -eq $entry) { continue }
                    $rawPath = [string](Get-JsonProperty -Object $entry -Name "path")
                    if ([string]::IsNullOrWhiteSpace($rawPath)) { continue }
                    $normalizedPath = [System.IO.Path]::GetFullPath($rawPath)
                    $manifestPath = Join-Path $normalizedPath "manifest.json"
                    $manifestName = $null
                    $manifestNode = Get-JsonProperty -Object $entry -Name "manifest"
                    if ($manifestNode) {
                        $manifestName = [string](Get-JsonProperty -Object $manifestNode -Name "name")
                    }
                    if ([string]::IsNullOrWhiteSpace($manifestName) -and (Test-Path -LiteralPath $manifestPath)) {
                        try {
                            $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
                            $manifestName = [string](Get-JsonProperty -Object $manifest -Name "name")
                        } catch {}
                    }
                    if ($manifestName -eq "Flow Kit" -or $property.Name -eq "flowkit" -or $rawPath -like "*flowkit*") {
                        $records += [pscustomobject]@{
                            profile_name = $pDir.Name
                            preferences_file = $preferencesPath
                            extension_id = $property.Name
                            registered_path = $normalizedPath
                            state = Get-JsonProperty -Object $entry -Name "state"
                        }
                    }
                }
            } catch {
                # Silently catch strict mode exceptions for other profile preference trees
            }
        }
    }
    return $records
}

$allRegistrations = @(Get-AllFlowKitRegistrations -UserDataDir $discoveredUserDataDir)
Write-Output "Total Flow Kit registrations found: $($allRegistrations.Count)"
foreach ($reg in $allRegistrations) {
    Write-Output "  Found Profile: $($reg.profile_name) | ID: $($reg.extension_id) | Path: $($reg.registered_path)"
}

if (-not $discoveredProfile) {
    $activeRegistrations = @($allRegistrations | Where-Object { $_.registered_path -eq $ExpectedExtensionPath })
    if ($activeRegistrations.Count -gt 0) {
        $discoveredProfile = $activeRegistrations[0].profile_name
        Write-Output "Dynamically resolved active Chrome Profile: $discoveredProfile (owns unpacked registration)"
    } else {
        $discoveredProfile = "Default"
        Write-Output "No active Chrome profile-directory arg discovered or registered. Defaulting to: $discoveredProfile"
    }
} else {
    Write-Output "Discovered active Chrome Profile: $discoveredProfile"
}

# 2. Get and validate registrations
$allRegistrations = Get-AllFlowKitRegistrations -UserDataDir $discoveredUserDataDir
$profileRegistrations = @($allRegistrations | Where-Object { $_.profile_name -eq $discoveredProfile })

if ($profileRegistrations.Count -eq 0) {
    Write-Output "No Flow Kit registration found in the current profile ($discoveredProfile)."
    Write-Output "Please load the unpacked Flow Kit extension manually from: $ExpectedExtensionPath"
    Write-Output "ERR_EXTENSION_PATH_MISMATCH"
    exit 1
}

$primaryRegistration = $profileRegistrations[0]
Write-Output "Primary extension registration details:"
Write-Output "  Profile: $($primaryRegistration.profile_name)"
Write-Output "  Extension ID: $($primaryRegistration.extension_id)"
Write-Output "  Registered Path: $($primaryRegistration.registered_path)"

if ($primaryRegistration.registered_path -ne $ExpectedExtensionPath) {
    Write-Output "ERR_EXTENSION_PATH_MISMATCH"
    Write-Output "  Registered Path: $($primaryRegistration.registered_path)"
    Write-Output "  Expected Path:   $ExpectedExtensionPath"
    exit 1
}

# Identify duplicate registrations
$duplicates = @($allRegistrations | Where-Object { $_.profile_name -ne $discoveredProfile })
if ($duplicates.Count -gt 0) {
    Write-Output "WARNING: Duplicate Flow Kit registrations detected in other profiles:"
    foreach ($dup in $duplicates) {
        Write-Output "  Profile: $($dup.profile_name) | ID: $($dup.extension_id) | Path: $($dup.registered_path) [IRRELEVANT]"
    }
}

# 3. Fetch current status / Self-Test before doing actions
function Get-SelfTest {
    try {
        return Invoke-RestMethod -Method Get -Uri "$ApiBaseUrl/api/local-agent/extension-self-test?mode=F2V&attempt_open_project=false" -TimeoutSec 10
    } catch {
        return $null
    }
}

$selfTest = Get-SelfTest
$savedUrl = $null
if ($selfTest -and $selfTest.PSObject.Properties['extension_self_test'] -and $selfTest.extension_self_test -and $selfTest.extension_self_test.PSObject.Properties['target_tab'] -and $selfTest.extension_self_test.target_tab) {
    $savedUrl = $selfTest.extension_self_test.target_tab.url
    Write-Output "Detected existing Flow editor URL: $savedUrl"
}

# Function to check for redirect or auth failure
function Check-AuthFailed([string]$url) {
    if ($url -like "*accounts.google.com*") {
        Write-Output "ERR_GOOGLE_SESSION_NOT_AUTHENTICATED"
        exit 1
    }
}

if ($savedUrl) {
    Check-AuthFailed -url $savedUrl
}

# 4. Check & Repair Stale Content Script or Build Mismatches
$staleContentRetried = $false

function Verify-State {
    param($selfTestResult)

    if (-not $selfTestResult) {
        return $false
    }

    $runtime = $selfTestResult.extension_self_test
    if (-not $runtime) {
        return $false
    }

    if ($runtime.connected -ne $true -or $runtime.runner_loaded -ne $true) {
        return $false
    }

    $target = $runtime.target_tab
    if (-not $target) {
        Write-Output "ERR_FLOW_EDITOR_TAB_NOT_OPEN"
        exit 1
    }

    Check-AuthFailed -url $target.url

    if ($target.tab_kind -ne "EDITOR") {
        Write-Output "ERR_FLOW_EDITOR_TAB_NOT_OPEN"
        exit 1
    }

    $liveBuild = [string]$runtime.background_build_id
    if ([string]::IsNullOrWhiteSpace($liveBuild)) { $liveBuild = [string]$runtime.build_id }
    if ([string]::IsNullOrWhiteSpace($liveBuild)) { $liveBuild = [string]$runtime.buildId }

    if ($liveBuild -ne $ExpectedBuildMarker) {
        Write-Output "Build mismatch detected! Live build: '$liveBuild' vs Expected: '$ExpectedBuildMarker'"
        return "BUILD_MISMATCH"
    }

    $pageDiag = $runtime.page_diagnostic
    if ($pageDiag -and $pageDiag.content_script_alive -ne $true) {
        return "STALE_CONTENT"
    }

    # Verify diagnostic keys
    if ($pageDiag) {
        if ($pageDiag.composer_found -ne $true -or $pageDiag.prompt_field_found -ne $true -or $pageDiag.generate_button_found -ne $true) {
            return "STALE_CONTENT"
        }
        $showsVideoFrames = [bool](
            ($pageDiag.current_mode_visible -like "*Video/Frames*") -or
            (($pageDiag.visible_project_editor_markers -contains "Video") -and ($pageDiag.visible_project_editor_markers -contains "Frames"))
        )
        if (-not $showsVideoFrames) {
            return "STALE_CONTENT"
        }
    } else {
        return "STALE_CONTENT"
    }

    return "OK"
}

$state = Verify-State -selfTestResult $selfTest

if ($state -eq "STALE_CONTENT" -and -not $staleContentRetried) {
    Write-Output "Stale content script detected. Refreshing existing Flow editor tab once..."
    try {
        $reloadRes = Invoke-RestMethod -Method Get -Uri "$ApiBaseUrl/api/local-agent/reload-flow-tab" -TimeoutSec 15
        Write-Output "Reload triggered: $($reloadRes | ConvertTo-Json -Compress)"
    } catch {
        Write-Output "Direct reload API failed: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 4
    $selfTest = Get-SelfTest
    $state = Verify-State -selfTestResult $selfTest
    if ($state -eq "STALE_CONTENT") {
        Write-Output "ERR_STALE_CONTENT_SCRIPT"
        exit 1
    }
}

if ($state -eq "BUILD_MISMATCH" -or $state -eq $false) {
    Write-Output "Build mismatch or extension disconnected. Performing Same-Profile Chrome Restart..."
    
    # Grab active Chrome path
    $chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
    if (-not (Test-Path -LiteralPath $chromePath)) {
        $chromePath = "chrome.exe"
    }

    Write-Output "Stopping running Chrome processes..."
    Stop-Process -Name chrome -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    $launchUrl = if ($savedUrl) { $savedUrl } else { "https://labs.google/fx/tools/flow/project/ff250f80-7d0c-4f0e-9b26-9d341c47697c" }
    Write-Output "Restarting Chrome in same session/profile..."
    $procArgs = "--user-data-dir=`"$discoveredUserDataDir`" --profile-directory=`"$discoveredProfile`" `"$launchUrl`""
    Start-Process -FilePath $chromePath -ArgumentList $procArgs
    
    Write-Output "Waiting 8 seconds for Chrome and extension to reconnect..."
    Start-Sleep -Seconds 8

    $selfTest = Get-SelfTest
    $state = Verify-State -selfTestResult $selfTest
    if ($state -ne "OK") {
        if ($state -eq "BUILD_MISMATCH") {
            Write-Output "ERR_EXTENSION_BUILD_MISMATCH"
            exit 1
        } else {
            Write-Output "ERR_RUNTIME_SELF_TEST_FAILED"
            exit 1
        }
    }
}

Write-Output "Same-session verification: OK"
Write-Output "READY_FOR_SINGLE_LIVE_F2V_UAT"
exit 0
