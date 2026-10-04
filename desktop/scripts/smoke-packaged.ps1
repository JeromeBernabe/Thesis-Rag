# Smoke-tests the packaged executable, which nothing else does.
#
# verify.ps1 builds a production bundle and verify-window.ps1 runs the app from
# `tauri dev`. Between them they leave the one thing a release build does
# differently untested: the packaged window serves its assets from Tauri's own
# `tauri.localhost` protocol instead of the Vite dev server, and every route and
# asset reference is resolved against that.
#
# The failures that leaves open are all packaging-shaped rather than behavioural,
# and none are reachable from the dev server:
#   - hash routing dying because `#/results` becomes a request for a file called
#     `results`, which does not exist in the bundle;
#   - an asset or chunk 404ing because the built output references it differently;
#   - the sidecar failing to launch because the packaged process has a different
#     working directory and inherits nothing from a dev shell.
#
# A separate script from verify-window.ps1 on purpose. That one launches the dev
# server and waits for `localhost:1420`; this one launches a finished binary on a
# different port and waits for `tauri.localhost`. Sharing a script would mean one
# of the two launches was conditional on which mode was being tested, and the
# mode is exactly what is under test.
#
# The database assertions are the same ones the dev-window flow makes, because
# "the window opened" is not evidence the app works - a run reaching SQLite is.
#
# Run from the desktop directory:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke-packaged.ps1
#
# -SkipBuild reuses whatever bundle is already built, which is only safe once the
# working tree is clean: -SkipBuild will happily smoke-test a stale binary.

[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

# Deliberately not 9222. If a dev window is still up from verify-window.ps1, this
# must attach to the packaged one rather than silently testing the wrong build.
$port = 9223
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=$port"
$env:CDP_URL = "http://127.0.0.1:$port"

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    ok ($msg)" -ForegroundColor Green }
function Die($msg) { throw $msg }

$exe = 'src-tauri\target\release\thesis-rag-bench.exe'
$stderr = Join-Path $env:TEMP 'smoke-packaged-stderr.txt'

# As in verify-window.ps1: the sidecar is a Python process, so only ones this
# script started may be torn down. An unrelated job is not this script's to stop.
$preexistingPython = @(Get-Process python -ErrorAction SilentlyContinue |
    ForEach-Object { $_.Id })

function Stop-App {
    # Teardown must never turn a passing run into a failing one: taskkill
    # complains on stderr when a child has already exited, and under
    # `$ErrorActionPreference = 'Stop'` that would surface from the `finally`
    # block and mask the real result.
    $ErrorActionPreference = 'Continue'
    Get-Process thesis-rag-bench -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process python -ErrorAction SilentlyContinue |
        Where-Object { $preexistingPython -notcontains $_.Id } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

try {
    Step 'building the bundle'
    if (-not $SkipBuild) {
        # Capture cargo's progress instead of letting it raise as a terminating
        # error, and only report it if the build actually failed.
        $ErrorActionPreference = 'Continue'
        $build = & .\scripts\tauri-x.cmd build 2>&1
        $buildFailed = $LASTEXITCODE -ne 0
        $ErrorActionPreference = 'Stop'
        if ($buildFailed) {
            $build | ForEach-Object { Write-Host $_ }
            Die 'the bundle does not build'
        }
    }
    if (-not (Test-Path $exe)) { Die "no packaged executable at $exe" }
    $bundle = Get-ChildItem src-tauri\target\release\bundle -Recurse -Include *.exe,*.msi -ErrorAction SilentlyContinue
    Ok "bundle built ($($bundle.Count) installer artefact(s))"

    Step 'starting the packaged executable'
    if (Test-Path $stderr) { Remove-Item $stderr -Force }
    $app = Start-Process -FilePath $exe -PassThru -WindowStyle Normal `
        -RedirectStandardError $stderr -RedirectStandardOutput "$env:TEMP\smoke-packaged-stdout.txt"

    # The window is only interesting once its webview is listening for CDP. Its
    # assets come from tauri.localhost, so matching on the dev server's port here
    # would wait forever.
    $ready = $false
    foreach ($attempt in 1..60) {
        Start-Sleep -Seconds 2
        try {
            $pages = Invoke-RestMethod -Uri "$($env:CDP_URL)/json/list" -TimeoutSec 3
            if ($pages | Where-Object { $_.url -like '*tauri.localhost*' }) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) {
        Get-Content $stderr -Tail 30 -ErrorAction SilentlyContinue
        Die 'the packaged window never became reachable over CDP'
    }
    Ok "window up on $($env:CDP_URL), serving bundled assets"

    Step 'the packaged app routes, reads the database and launches the sidecar'
    & node .\scripts\smoke-packaged.mjs
    if ($LASTEXITCODE -ne 0) { Die 'the packaged smoke test failed' }
    Ok 'packaged binary works end to end'

    # The startup sweep is the packaged binary's own stderr, so it is worth
    # reading directly: a release build that quietly leaves runs stuck in
    # `running` blocks every future run. Nothing to report is the normal case -
    # the previous session ended cleanly - so this reports rather than asserts,
    # and what it must never do is fail on a healthy database.
    $stderrText = Get-Content $stderr -Raw -ErrorAction SilentlyContinue
    if (-not $stderrText) { $stderrText = '' }
    $swept = @([regex]::Matches($stderrText, 'closed (\d+) run\(s\) left running')).Value
    if ($swept) {
        Ok "startup sweep closed a stale run: $($swept -join '; ')"
    } else {
        Ok 'no stale runs to reconcile at startup'
    }

    Write-Host "`nPackaged smoke test passed." -ForegroundColor Green
}
finally {
    Stop-App
}