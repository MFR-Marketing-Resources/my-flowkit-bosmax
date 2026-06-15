param(
    [string]$ChromeExe = "C:\Program Files\Google\Chrome\Application\chrome.exe",
    [string]$ChromeUserDataDir = "",
    [switch]$ResetUserDataDir,
    [string]$FlowUrl = "https://labs.google/fx/tools/flow",
    [int]$LaunchTimeoutSec = 120,
    [string]$BrowserChannel = "chromium"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\local-agent-common.ps1"

$ExpectedExtensionPath = Join-Path $script:RepoRoot "extension"
$ExpectedBuildId = "flowkit-f2v-runner-audit-2026-06-15a"
$LaunchHelperScript = Join-Path $PSScriptRoot "launch-clean-bosmax-flow-runtime-helper.js"
$LaunchRuntimeStateDir = Join-Path $script:LocalAgentStateDir "chrome-runtime"
$LaunchHelperReport = Join-Path $LaunchRuntimeStateDir "launch-report.json"
$LaunchHelperStdout = Join-Path $LaunchRuntimeStateDir "launch-helper.stdout.log"
$LaunchHelperStderr = Join-Path $LaunchRuntimeStateDir "launch-helper.stderr.log"

if ([string]::IsNullOrWhiteSpace($ChromeUserDataDir)) {
    if ($BrowserChannel -eq "chromium") {
        # Chromium must own its own persistent profile. Reusing a profile that was
        # last touched by branded Chrome causes downgrade/version cleanup crashes
        # before the extension service worker can even come online.
        $ChromeUserDataDir = Join-Path $env:LOCALAPPDATA "BOSMAX\FlowKitChromiumProfile"
    } else {
        $ChromeUserDataDir = Join-Path $env:LOCALAPPDATA "BOSMAX\FlowKitChromeProfile"
    }
}

function Stop-AllChromeProcesses {
    $chromeProcesses = @(Get-Process chrome -ErrorAction SilentlyContinue)
    foreach ($process in $chromeProcesses) {
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
        } catch {
            if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) {
                throw
            }
        }
    }
}

function Stop-AllAgentMainProcesses {
    $candidates = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match "agent\.main"
    })

    foreach ($candidate in $candidates) {
        try {
            Stop-Process -Id $candidate.ProcessId -Force -ErrorAction Stop
        } catch {
            if (Get-Process -Id $candidate.ProcessId -ErrorAction SilentlyContinue) {
                throw
            }
        }
    }

    Clear-LocalAgentPid
}

function Get-FlowKitExtensionRegistration {
    param(
        [Parameter(Mandatory = $true)][string]$UserDataDir,
        [Parameter(Mandatory = $true)][string]$ExpectedPath
    )

    $profileDirs = @()
    $defaultDir = Join-Path $UserDataDir "Default"
    if (Test-Path -LiteralPath $defaultDir) {
        $profileDirs += $defaultDir
    }
    $profileDirs += @(Get-ChildItem -LiteralPath $UserDataDir -Directory -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -like "Profile *"
    } | Select-Object -ExpandProperty FullName)

    foreach ($profileDir in $profileDirs | Select-Object -Unique) {
        foreach ($preferencesFileName in @("Secure Preferences", "Preferences")) {
            $preferencesPath = Join-Path $profileDir $preferencesFileName
            if (-not (Test-Path -LiteralPath $preferencesPath)) {
                continue
            }

            try {
                $json = Get-Content -LiteralPath $preferencesPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $settings = $json.extensions.settings
                if (-not $settings) {
                    continue
                }

                foreach ($property in $settings.PSObject.Properties) {
                    $value = $property.Value
                    $registeredPath = [string]$value.path
                    $manifestName = [string]$value.manifest.name
                    if (
                        $manifestName -eq "Flow Kit" -or
                        ($registeredPath -and $registeredPath -eq $ExpectedPath)
                    ) {
                        return [ordered]@{
                            extension_id = $property.Name
                            profile_dir = $profileDir
                            preferences_path = $preferencesPath
                            registered_path = $registeredPath
                            manifest_name = $manifestName
                        }
                    }
                }
            } catch {
                continue
            }
        }
    }

    return $null
}

function Stop-LaunchHelperProcesses {
    $candidates = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -like "*launch-clean-bosmax-flow-runtime-helper.js*"
    })

    foreach ($candidate in $candidates) {
        try {
            Stop-Process -Id $candidate.ProcessId -Force -ErrorAction Stop
        } catch {
            if (Get-Process -Id $candidate.ProcessId -ErrorAction SilentlyContinue) {
                throw
            }
        }
    }
}

function Invoke-ExtensionSelfTestPayload {
    param(
        [Parameter(Mandatory = $true)][string]$Url
    )

    try {
        return Invoke-RestMethod -Uri $Url -TimeoutSec 12 -ErrorAction Stop
    } catch {
        return $null
    }
}

function Test-RuntimeActivationReady {
    param(
        [Parameter(Mandatory = $true)]$Payload,
        [Parameter(Mandatory = $true)][string]$ExpectedBuildId
    )

    if (-not $Payload) { return $false }
    $runtime = $Payload.extension_self_test
    if (-not $runtime) { return $false }

    $liveBuildId = [string]($runtime.background_build_id)
    if ([string]::IsNullOrWhiteSpace($liveBuildId)) {
        $liveBuildId = [string]($runtime.build_id)
    }
    if ([string]::IsNullOrWhiteSpace($liveBuildId)) {
        $liveBuildId = [string]($runtime.buildId)
    }
    if ([string]::IsNullOrWhiteSpace($liveBuildId)) {
        $liveBuildId = [string]($runtime.expected_content_build_id)
    }

    return [bool](
        $runtime.connected -eq $true -and
        $runtime.runner_loaded -eq $true -and
        $liveBuildId -eq $ExpectedBuildId -and
        @($runtime.flow_tabs).Count -gt 0 -and
        $null -ne $runtime.target_tab
    )
}

Set-Location $script:RepoRoot
Ensure-LocalAgentDirectories
New-Item -ItemType Directory -Force -Path $LaunchRuntimeStateDir | Out-Null

if ($BrowserChannel -eq "chrome" -and -not (Test-Path -LiteralPath $ChromeExe)) {
    throw "Chrome executable not found at $ChromeExe"
}

if (-not (Test-Path -LiteralPath $ExpectedExtensionPath)) {
    throw "Expected extension path missing at $ExpectedExtensionPath"
}

if (-not (Test-Path -LiteralPath $LaunchHelperScript)) {
    throw "Launch helper script missing at $LaunchHelperScript"
}

Stop-AllChromeProcesses
Start-Sleep -Seconds 2
Stop-AllAgentMainProcesses
Start-Sleep -Seconds 2
Stop-LaunchHelperProcesses
Start-Sleep -Seconds 1

if ($ResetUserDataDir -and (Test-Path -LiteralPath $ChromeUserDataDir)) {
    Remove-Item -LiteralPath $ChromeUserDataDir -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $ChromeUserDataDir | Out-Null
Remove-Item -LiteralPath $LaunchHelperReport,$LaunchHelperStdout,$LaunchHelperStderr -Force -ErrorAction SilentlyContinue

powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "start-local-agent.ps1") -ForceRestart | Out-Host

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    throw "Node.js executable not found in PATH."
}

$helperArgs = @(
    $LaunchHelperScript,
    "--user-data-dir", $ChromeUserDataDir,
    "--extension-path", $ExpectedExtensionPath,
    "--flow-url", $FlowUrl,
    "--report-path", $LaunchHelperReport,
    "--timeout-ms", [string]($LaunchTimeoutSec * 1000),
    "--channel", $BrowserChannel,
    "--keep-alive", "true"
)

$helperProc = Start-Process `
    -FilePath $nodeCommand.Source `
    -ArgumentList $helperArgs `
    -WorkingDirectory $script:RepoRoot `
    -RedirectStandardOutput $LaunchHelperStdout `
    -RedirectStandardError $LaunchHelperStderr `
    -PassThru

$extensionSelfTestUrl = "http://127.0.0.1:8100/api/local-agent/extension-self-test?mode=F2V&attempt_open_project=false"
$healthDeadline = (Get-Date).AddSeconds($LaunchTimeoutSec)
$registration = $null
$latestPayload = $null
$launchReport = $null

while ((Get-Date) -lt $healthDeadline) {
    Start-Sleep -Seconds 3

    if (Test-Path -LiteralPath $LaunchHelperReport) {
        try {
            $launchReport = Get-Content -LiteralPath $LaunchHelperReport -Raw -Encoding UTF8 | ConvertFrom-Json
        } catch {
            $launchReport = $null
        }
    }

    if ($helperProc.HasExited -and -not $launchReport) {
        break
    }

    $latestPayload = Invoke-ExtensionSelfTestPayload -Url $extensionSelfTestUrl
    if (Test-RuntimeActivationReady -Payload $latestPayload -ExpectedBuildId $ExpectedBuildId) {
        break
    }

    if (-not $registration) {
        $registration = Get-FlowKitExtensionRegistration -UserDataDir $ChromeUserDataDir -ExpectedPath $ExpectedExtensionPath
    }
}

$latestPayload = Invoke-ExtensionSelfTestPayload -Url $extensionSelfTestUrl
$success = Test-RuntimeActivationReady -Payload $latestPayload -ExpectedBuildId $ExpectedBuildId

$result = [ordered]@{
    ok = $success
    launch_helper_pid = $helperProc.Id
    chrome_user_data_dir = $ChromeUserDataDir
    expected_extension_path = $ExpectedExtensionPath
    expected_build_id = $ExpectedBuildId
    browser_channel = $BrowserChannel
    launch_helper_report = $launchReport
    launch_helper_stdout = $LaunchHelperStdout
    launch_helper_stderr = $LaunchHelperStderr
    registration = $registration
    extension_self_test = $latestPayload
}

$result | ConvertTo-Json -Depth 10 | Write-Output

if (-not $success) {
    exit 1
}

exit 0
