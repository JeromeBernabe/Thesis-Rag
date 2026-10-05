<#
.SYNOPSIS
    Re-run all four datasets to recover generator token usage and retrain Hotpot.

.DESCRIPTION
    The committed results CSVs predate the token-logging fix: their
    prompt_tokens/completion_tokens hold the judge's counts, so section 4.1 and
    4.3 of the report cannot be published from them. Regenerating requires
    re-running, because generator tokens are only known at generation time.

    This writes to a separate directory and a separate checkpoint directory, so
    the committed CSVs and the thesis checkpoints are untouched. Each dataset is
    run as its own process and writes its own CSV, so a failure or an interrupt
    costs at most one dataset and the run is resumable.

    Roughly 10 hours total: the judge is 83% of wall-clock and Ollama serialises
    one request per model on this machine, so there is no parallelism to exploit.
#>
param(
    [string]$OutDir = "$env:TEMP\rerun-2026-10-05",
    [int]$Limit = 0
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$ckpt = Join-Path $OutDir 'checkpoints'
New-Item -ItemType Directory -Force -Path $OutDir, $ckpt | Out-Null
$env:BENCH_CHECKPOINTS_DIR = $ckpt

$limitArg = if ($Limit -gt 0) { @('--limit', "$Limit") } else { @() }
$log = Join-Path $OutDir 'rerun.log'

"[{0}] starting; out={1} ckpt={2} limit={3}" -f (Get-Date -Format s), $OutDir, $ckpt, $Limit |
    Tee-Object -FilePath $log -Append

foreach ($ds in @('hotpot', 'ragtruth', 'fintech', 'math')) {
    $csv = Join-Path $OutDir "ragas_results_${ds}_logged.csv"
    if (Test-Path $csv) {
        "[{0}] {1}: already present, skipping" -f (Get-Date -Format s), $ds | Tee-Object -FilePath $log -Append
        continue
    }

    "[{0}] {1}: starting" -f (Get-Date -Format s), $ds | Tee-Object -FilePath $log -Append
    $sw = [Diagnostics.Stopwatch]::StartNew()

    # Not `& python ... *>&1 | Tee-Object`. Python's logging writes to stderr, so
    # merging stderr into the pipeline raises NativeCommandError, which under
    # $ErrorActionPreference='Stop' kills the script on the first log line -
    # the run exits seconds in and looks like it simply produced no rows.
    # Redirecting the two streams to separate files avoids that entirely.
    $stdout = Join-Path $OutDir "${ds}.stdout.log"
    $stderr = Join-Path $OutDir "${ds}.stderr.log"
    $argList = @('run_experiment_logged.py', '--dataset', $ds) + $limitArg +
        @('--results', $csv, '--training-csv', (Join-Path $OutDir "training_${ds}_logged.csv"))
    $proc = Start-Process -FilePath 'python' -ArgumentList $argList -WorkingDirectory $root `
        -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $proc.WaitForExit()
    $sw.Stop()

    Get-Content $stderr -Tail 3 -ErrorAction SilentlyContinue |
        ForEach-Object { "    $_" } | Tee-Object -FilePath $log -Append

    if (Test-Path $csv) {
        $rows = (Import-Csv $csv).Count
        "[{0}] {1}: done in {2:n0}s, {3} rows" -f (Get-Date -Format s), $ds, $sw.Elapsed.TotalSeconds, $rows |
            Tee-Object -FilePath $log -Append
    }
    else {
        "[{0}] {1}: FAILED after {2:n0}s (no CSV)" -f (Get-Date -Format s), $ds, $sw.Elapsed.TotalSeconds |
            Tee-Object -FilePath $log -Append
    }
}

"[{0}] all datasets attempted" -f (Get-Date -Format s) | Tee-Object -FilePath $log -Append