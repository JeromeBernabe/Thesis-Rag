# Verifies the one seam nothing else covers: the real window.
#
# Everything in verify.ps1 either stubs the host or calls the sidecar directly,
# so an entire layer can be broken without any of it noticing - a misregistered
# command, an invoke payload the Rust side cannot deserialise, a cancel that
# never reaches the process. Those are not hypothetical here: cancelling a run
# did nothing at all until this script existed, and the run row stayed `running`
# forever afterwards.
#
# The WebView is attached over the DevTools protocol instead of through
# tauri-driver, which would need an msedgedriver matching the installed runtime
# version. That is a deliberate trade: it needs nothing installed, but it only
# works on Windows with WebView2, which is where this app runs anyway.
#
# Three flows, because they fail in different ways:
#   1. start a dry run, wait for it to land in the database as completed
#   2. start a real run, cancel it, require the row to reach 'cancelled'
#   3. read the run back through Results and Simulation, then delete it
#
# All three run against the same window on purpose. Cancelling the *second* run of
# a session is exactly what was broken for as long as this script existed: Tauri
# keeps the first value it is given for a managed type, so the per-run handle was
# never replaced and every cancel after the first one hit a dead process. Checking
# the flows separately, in fresh windows, would have missed it entirely.
#
# The third flow runs last so it deletes its own run and leaves the counts as it
# found them, and because the two runs above it are then already stored - so its
# picker has more than one entry to choose from, which is the case that would
# catch a stale selection.
#
# Run from the desktop directory:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-window.ps1
#
# -SkipBuild reuses whatever is already built.

[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

$port = 9222
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=$port"
$cdp = "http://127.0.0.1:$port"

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    ok ($msg)" -ForegroundColor Green }
function Die($msg) { throw $msg }

$launcher = $null
$log = 'verify-window.log'

# Python processes already running before this script. The sidecar is a Python
# process, so tearing it down by name alone would also kill whatever else the
# machine happens to be running - an unrelated job is not this script's to stop.
$preexistingPython = @(Get-Process python -ErrorAction SilentlyContinue |
    ForEach-Object { $_.Id })

function Stop-App {
    # Teardown must never turn a passing run into a failing one. `taskkill`
    # complains on stderr when a child has already exited, and under
    # `$ErrorActionPreference = 'Stop'` that would surface as a terminating
    # error from the `finally` block and mask the real result.
    $ErrorActionPreference = 'Continue'
    if ($launcher) {
        # The launcher is cmd.exe; /T takes the vite and cargo children with it,
        # and the app itself goes with those.
        & taskkill /PID $launcher.Id /T /F 2>&1 | Out-Null
    }
    Get-Process thesis-rag-bench -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    # Only sidecars this script started. A Python child outlives a host that was
    # killed outright, and would otherwise keep running and writing.
    Get-Process python -ErrorAction SilentlyContinue |
        Where-Object { $preexistingPython -notcontains $_.Id } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

try {
    Step 'starting the app'
    if (-not $SkipBuild) {
        # Fail early and clearly rather than 40 seconds into the wait. Cargo
        # reports progress on stderr, which PowerShell would otherwise raise as a
        # terminating error and report as a build failure; captured, and printed
        # only if it actually failed.
        $ErrorActionPreference = 'Continue'
        $build = & .\scripts\cargo-x.cmd build --manifest-path .\src-tauri\Cargo.toml 2>&1
        $buildFailed = $LASTEXITCODE -ne 0
        $ErrorActionPreference = 'Stop'
        if ($buildFailed) {
            $build | ForEach-Object { Write-Host $_ }
            Die 'the host does not build'
        }
    }
    if (Test-Path $log) { Remove-Item $log -Force }
    $launcher = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', "npm run tauri:dev > $log 2>&1" `
        -WindowStyle Hidden -PassThru

    # The window is only interesting once the webview is listening for CDP.
    $ready = $false
    foreach ($attempt in 1..60) {
        Start-Sleep -Seconds 2
        try {
            $pages = Invoke-RestMethod -Uri "$cdp/json/list" -TimeoutSec 3
            if ($pages | Where-Object { $_.url -like '*1420*' }) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) {
        Get-Content $log -Tail 30 -ErrorAction SilentlyContinue
        Die 'the app window never became reachable over CDP'
    }
    Ok "window up on $cdp"

    Step 'a run started in the window reaches the database'
    & node .\scripts\drive-window.mjs
    if ($LASTEXITCODE -ne 0) { Die 'the start flow failed' }
    Ok 'completed run persisted'

    Step 'cancelling in the window closes the run out'
    & node .\scripts\cancel-window.mjs
    if ($LASTEXITCODE -ne 0) { Die 'the cancel flow failed' }
    Ok 'cancelled run settled'

    Step 'Results and Simulation read real data back'
    & node .\scripts\pages-window.mjs
    if ($LASTEXITCODE -ne 0) { Die 'the pages flow failed' }
    Ok 'pages read the database and cleaned up'

    Step 'the window is still responsive'
    $title = (Invoke-RestMethod -Uri "$cdp/json/list" -TimeoutSec 5)[0].title
    if ($title -ne 'RAG Benchmark Console') { Die "unexpected window title '$title'" }
    Ok 'responding after a cancel'

    Write-Host "`nWindow verification passed." -ForegroundColor Green
}
finally {
    Stop-App
}
