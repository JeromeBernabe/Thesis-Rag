# Runs the whole verification stack and reports one verdict.
#
# Order matters only in that it is cheapest-first: the Python and Rust suites are
# fast and catch protocol regressions, the frontend suite is faster still, and the
# end-to-end suite and the production build are the slow ones. Everything here is
# read-only apart from the build outputs.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File desktop\scripts\verify.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File desktop\scripts\verify.ps1 -SkipE2E
#
# Written for Windows PowerShell 5.1, not just pwsh: the native-command helpers
# below cannot use `ProcessStartInfo.ArgumentList` (that is .NET Core 2.1+ and
# 5.1 is .NET Framework) and cannot run a `.cmd` shim with
# `UseShellExecute = $false`, which is why they invoke commands through
# PowerShell instead.
#
# The Tauri window itself is not launched here: a GUI window cannot be asserted on
# from a script, so it is verified by hand with `npm run tauri:dev`. The real
# sidecar round trip is covered by the smoke run documented in desktop/README.md.

[CmdletBinding()]
param(
    # Skips the Playwright suite and the production build. Useful while iterating,
    # since those two dominate the runtime.
    [switch] $SkipE2E,
    # Skips the sidecar dry run. It needs no models and no database - `--dry-run`
    # swaps in in-process fakes - so this is only worth skipping if the Python
    # package itself is not importable yet.
    [switch] $SkipSidecar
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Desktop = Join-Path $RepoRoot 'desktop'
$TauriManifest = Join-Path $Desktop 'src-tauri\Cargo.toml'

# Prefer the repo's Cargo wrapper: it selects the right linker and target triple,
# which plain `cargo` does not pick up reliably on Windows.
$CargoWrapper = Join-Path $PSScriptRoot 'cargo-x.cmd'

$script:Failures = [System.Collections.Generic.List[string]]::new()
$script:Started = Get-Date

function Invoke-Step {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [scriptblock] $Body
    )

    Write-Host ''
    Write-Host "==> $Name" -ForegroundColor Cyan

    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        & $Body
        $timer.Stop()
        Write-Host ("    ok ({0:n1}s)" -f $timer.Elapsed.TotalSeconds) -ForegroundColor Green
    }
    catch {
        $timer.Stop()
        $message = $_.Exception.Message
        Write-Host ("    FAILED ({0:n1}s): {1}" -f $timer.Elapsed.TotalSeconds, $message) -ForegroundColor Red
        $script:Failures.Add("$Name - $message")
    }
}

function Test-Command {
    param([Parameter(Mandatory)] [string] $Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "'$Name' is not on PATH. Install it before running this script."
    }
}

function Invoke-Native {
    <#
      Runs a native command and returns its combined output and exit code.

      PowerShell 5.1 wraps anything a native tool writes to stderr into an
      ErrorRecord, which - combined with `$ErrorActionPreference = 'Stop'` above -
      aborts the script. Every tool here logs to stderr while succeeding (cargo
      prints progress, pytest prints warnings, the sidecar logs its own progress),
      so the preference is relaxed for the call and only the exit code decides
      whether the step passed.

      The command is invoked by PowerShell itself rather than through
      `ProcessStartInfo`, because the `npm`/`cargo` entry points are `.cmd` shims:
      .NET Framework's `ProcessStartInfo` cannot run a `.cmd` with
      `UseShellExecute = $false`, and it has no `ArgumentList` to pass one.
    #>
    param(
        [Parameter(Mandatory)] [string] $FilePath,
        [string[]] $ArgumentList = @(),
        [string] $WorkingDirectory
    )

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        Push-Location $WorkingDirectory
        try {
            $output = & $FilePath @ArgumentList 2>&1 | ForEach-Object { "$_" }
            $exitCode = $LASTEXITCODE
        }
        finally { Pop-Location }

        return [pscustomobject]@{
            ExitCode = $exitCode
            Output   = ($output -join "`n")
        }
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Invoke-NativeStdout {
    <#
      Runs a native command and returns stdout, stderr and the exit code separately.

      Needed where stdout is data to be parsed rather than a message for a human:
      the sidecar writes its protocol to stdout and its progress log to stderr, so
      merging the two would put log lines into the event stream.
    #>
    param(
        [Parameter(Mandatory)] [string] $FilePath,
        [string[]] $ArgumentList = @(),
        [string] $WorkingDirectory
    )

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $stderrFile = [System.IO.Path]::GetTempFileName()
    try {
        Push-Location $WorkingDirectory
        try {
            $stdout = & $FilePath @ArgumentList 2>$stderrFile | ForEach-Object { "$_" }
            $exitCode = $LASTEXITCODE
        }
        finally { Pop-Location }

        return [pscustomobject]@{
            ExitCode = $exitCode
            StdOut   = ($stdout -join "`n")
            StdErr   = (Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue)
        }
    }
    finally {
        $ErrorActionPreference = $previous
        Remove-Item -LiteralPath $stderrFile -ErrorAction SilentlyContinue
    }
}

function Test-RustFmt {
    # rustfmt ships as a separate component, so a working toolchain does not
    # guarantee it. Report it rather than silently passing or failing.
    $probe = Invoke-Native -FilePath $CargoWrapper -ArgumentList @('fmt', '--version')
    return ($probe.ExitCode -eq 0)
}

Write-Host 'DQN-RAG desktop verification' -ForegroundColor White
Write-Host "repo: $RepoRoot"

Invoke-Step 'python suite' {
    Test-Command 'python'
    $result = Invoke-Native -FilePath 'python' -ArgumentList @('-m', 'pytest', '-q') -WorkingDirectory $RepoRoot
    if ($result.ExitCode -ne 0) {
        Write-Host $result.Output
        throw "pytest exited $($result.ExitCode)"
    }
    Write-Host (($result.Output -split "`n" | Where-Object { $_ -match 'passed' } | Select-Object -Last 1).Trim())
}

Invoke-Step 'rust suite' {
    $result = Invoke-Native -FilePath $CargoWrapper -ArgumentList @('test', '--manifest-path', $TauriManifest) -WorkingDirectory $RepoRoot
    if ($result.ExitCode -ne 0) {
        Write-Host $result.Output
        throw "cargo test exited $($result.ExitCode)"
    }
    # Only the tally, not every test name.
    Write-Host (($result.Output -split "`n" | Where-Object { $_ -match 'test result:' } | Select-Object -First 1).Trim())
}

if (-not $SkipSidecar) {
    Invoke-Step 'sidecar subprocess contract' {
        # The Rust host and the Python sidecar only meet as two processes, so this
        # spawns the real sidecar with the exact argv the host builds and requires
        # a clean exit, a terminal event, and the run id we asked for. Marked
        # `#[ignore]` because it needs the Python package importable from the
        # repository, which a plain `cargo test` cannot assume.
        $result = Invoke-Native -FilePath $CargoWrapper -ArgumentList @(
            'test', '--manifest-path', $TauriManifest, '--', '--ignored'
        ) -WorkingDirectory $RepoRoot
        if ($result.ExitCode -ne 0) {
            Write-Host $result.Output
            throw "the sidecar subprocess test exited $($result.ExitCode)"
        }
        Write-Host (($result.Output -split "`n" | Where-Object { $_ -match 'test result:' } | Select-Object -First 1).Trim())
    }
}

Invoke-Step 'rust formatting' {
    if (-not (Test-RustFmt)) {
        Write-Host '    skipped: rustfmt is not installed (rustup component add rustfmt)'
        return
    }
    $result = Invoke-Native -FilePath $CargoWrapper -ArgumentList @('fmt', '--manifest-path', $TauriManifest, '--', '--check') -WorkingDirectory $RepoRoot
    if ($result.ExitCode -ne 0) {
        Write-Host $result.Output
        throw 'cargo fmt --check reported differences'
    }
}

Invoke-Step 'frontend types' {
    $result = Invoke-Native -FilePath 'npm' -ArgumentList @('run', '--silent', 'typecheck') -WorkingDirectory $Desktop
    if ($result.ExitCode -ne 0) {
        Write-Host $result.Output
        throw "tsc exited $($result.ExitCode)"
    }
}

Invoke-Step 'frontend lint' {
    $result = Invoke-Native -FilePath 'npm' -ArgumentList @('run', '--silent', 'lint') -WorkingDirectory $Desktop
    if ($result.ExitCode -ne 0) {
        Write-Host $result.Output
        throw "oxlint exited $($result.ExitCode)"
    }
}

Invoke-Step 'frontend tests' {
    $result = Invoke-Native -FilePath 'npm' -ArgumentList @('run', '--silent', 'test') -WorkingDirectory $Desktop
    if ($result.ExitCode -ne 0) {
        Write-Host $result.Output
        throw "vitest exited $($result.ExitCode)"
    }
    Write-Host (($result.Output -split "`n" | Where-Object { $_ -match 'Tests\s+\d+ passed' } | Select-Object -First 1).Trim())
}

if (-not $SkipE2E) {
    Invoke-Step 'frontend production build' {
        $result = Invoke-Native -FilePath 'npm' -ArgumentList @('run', '--silent', 'build') -WorkingDirectory $Desktop
        if ($result.ExitCode -ne 0) {
            Write-Host $result.Output
            throw "vite build exited $($result.ExitCode)"
        }
    }

    Invoke-Step 'end to end' {
        $result = Invoke-Native -FilePath 'npm' -ArgumentList @('run', '--silent', 'e2e') -WorkingDirectory $Desktop
        if ($result.ExitCode -ne 0) {
            Write-Host $result.Output
            throw "playwright exited $($result.ExitCode)"
        }
        Write-Host (($result.Output -split "`n" | Where-Object { $_ -match '\d+ passed' } | Select-Object -Last 1).Trim())
    }
}

if (-not $SkipSidecar) {
    Invoke-Step 'sidecar dry run' {
        # The cheapest end-to-end proof that the two sides still agree on the
        # protocol: real subprocess, real NDJSON, no models and no database.
        $result = Invoke-NativeStdout -FilePath 'python' -ArgumentList @(
            '-m', 'bench_bridge', '--dataset', 'hotpot', '--systems', 'A,B',
            '--limit', '2', '--dry-run', '--skip-projection'
        ) -WorkingDirectory $RepoRoot

        if ($result.ExitCode -ne 0) {
            Write-Host $result.StdErr
            throw "sidecar exited $($result.ExitCode)"
        }

        $events = @($result.StdOut -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
        $terminal = @($events | Where-Object { $_.type -in @('run_finished', 'run_failed') })
        if ($terminal.Count -eq 0) { throw 'no terminal event in the sidecar output' }
        if ($terminal[-1].type -ne 'run_finished') { throw "sidecar ended with $($terminal[-1].type)" }

        $completed = @($events | Where-Object { $_.type -eq 'prompt_completed' })
        $missingRow = @($completed | Where-Object { -not $_.data.row })
        if ($missingRow.Count -gt 0) { throw "$($missingRow.Count) prompt_completed events carry no row" }
        if ($completed.Count -eq 0) { throw 'no prompt_completed events in the dry run' }

        $steps = @($events | Where-Object { $_.type -eq 'train_step' })
        $missingQ = @($steps | Where-Object { @($_.data.q_values).Count -ne 5 })
        if ($missingQ.Count -gt 0) { throw "$($missingQ.Count) train_step events lack five q_values" }

        Write-Host ("    {0} events, {1} completed rows, {2} training steps" -f `
            $events.Count, $completed.Count, $steps.Count)
    }
}

$elapsed = (Get-Date) - $script:Started

Write-Host ''
if ($script:Failures.Count -eq 0) {
    Write-Host "All checks passed in $([int]$elapsed.TotalSeconds)s." -ForegroundColor Green
    Write-Host 'For the real window: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-window.ps1' -ForegroundColor Yellow
    exit 0
}

Write-Host "$($script:Failures.Count) check(s) failed after $([int]$elapsed.TotalSeconds)s:" -ForegroundColor Red
foreach ($failure in $script:Failures) { Write-Host "  - $failure" -ForegroundColor Red }
exit 1