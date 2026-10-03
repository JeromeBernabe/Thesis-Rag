<#
.SYNOPSIS
    Installs the Rust toolchain and MSVC import libraries needed to build the
    Tauri desktop app on Windows *without* Visual Studio Build Tools.

.DESCRIPTION
    Tauri needs a C linker on Windows. This script avoids a ~7 GB VS install by:

      1. Installing the rustup stable-x86_64-pc-windows-msvc toolchain.
      2. Downloading the MSVC CRT + Windows SDK import libraries from Microsoft's
         CDN via the `cargo-xwin` helper (per-user, no elevation).
      3. Linking with the `rust-lld` driver bundled inside the rustup toolchain.

    Step 2 downloads ~2.3 GB into %LOCALAPPDATA%\cargo-xwin.

    If you already have Visual Studio Build Tools with the C++ workload
    installed, skip this script and delete desktop\.cargo\config.toml.

.NOTES
    Re-running is safe: each step is skipped when already satisfied.
    Requires network access. Does not require administrator rights.
#>
[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$desktop = Split-Path -Parent $PSScriptRoot

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    OK: $msg" -ForegroundColor Green }

# ---------------------------------------------------------------- 1. rustup ---
Write-Step 'Checking rustup / cargo'
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    $rustupInit = Join-Path $env:TEMP 'rustup-init.exe'
    Write-Host "    downloading rustup-init..."
    Invoke-WebRequest -Uri 'https://win.rustup.rs/x86_64' -OutFile $rustupInit -UseBasicParsing
    Write-Host "    installing (stable-x86_64-pc-windows-msvc, minimal profile)..."
    & $rustupInit -y --profile minimal --default-toolchain stable-x86_64-pc-windows-msvc --no-modify-path
    if ($LASTEXITCODE -ne 0) { throw "rustup-init failed with exit code $LASTEXITCODE" }
    $env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
}
Write-Ok "cargo $(cargo --version)"

# ------------------------------------------------------------- 2. cargo-xwin ---
$xwin = Join-Path $env:LOCALAPPDATA 'cargo-xwin\xwin'
$msvcrt = Join-Path $xwin 'crt\lib\x86_64\msvcrt.lib'
if ((Test-Path $msvcrt) -and -not $Force) {
    Write-Ok "MSVC import libraries already cached at $xwin"
} else {
    Write-Step 'Fetching MSVC CRT + Windows SDK import libraries (cargo-xwin)'
    $cargoBin = Join-Path $env:USERPROFILE '.cargo\bin'
    $cargoXwin = Join-Path $cargoBin 'cargo-xwin.exe'
    if (-not (Test-Path $cargoXwin)) {
        Write-Host "    downloading prebuilt cargo-xwin (building it from source"
        Write-Host "    would itself require a linker, which is what we are installing)."
        $ver = 'v0.23.1'
        $zip = Join-Path $env:TEMP 'cargo-xwin.zip'
        Invoke-WebRequest -Uri "https://github.com/rust-cross/cargo-xwin/releases/download/$ver/cargo-xwin-$ver.windows-x64.zip" `
            -OutFile $zip -UseBasicParsing
        Expand-Archive -LiteralPath $zip -DestinationPath $env:TEMP -Force
        Copy-Item -LiteralPath (Join-Path $env:TEMP 'cargo-xwin.exe') -Destination $cargoXwin -Force
    }
    Write-Host "    downloading ~2.3 GB, this takes a few minutes..."
    & $cargoXwin xwin cache xwin
    if (-not (Test-Path $msvcrt)) {
        throw "cargo-xwin did not produce $msvcrt"
    }
}
Write-Ok "import libraries present"

# ------------------------------------------------------------------ 3. LLVM ---
# A linker is not enough: tauri's `vswhom-sys` dependency compiles a C shim, so
# cc-rs needs a C compiler, and tauri-winres needs a resource compiler. Both ship
# with LLVM, which we install portable (no admin, no registry).
$llvmBin = $null
foreach ($candidate in (Get-ChildItem "$env:LOCALAPPDATA\llvm-*" -Directory -ErrorAction SilentlyContinue)) {
    $direct = Join-Path $candidate.FullName 'bin\clang-cl.exe'
    if (Test-Path $direct) { $llvmBin = Join-Path $candidate.FullName 'bin'; break }
    $nested = Get-ChildItem $candidate.FullName -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName 'bin\clang-cl.exe' } |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($nested) { $llvmBin = Split-Path $nested -Parent; break }
}

if ($llvmBin) {
    Write-Ok "clang-cl at $llvmBin"
} else {
    Write-Step 'Installing portable LLVM (provides clang-cl, llvm-rc, llvm-lib)'
    $arch = 'x86_64-pc-windows-msvc'
    try {
        $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/llvm/llvm-project/releases/latest' `
            -Headers @{ 'User-Agent' = 'setup-toolchain' } -TimeoutSec 30
        $asset = $release.assets |
            Where-Object { $_.name -match "${arch}\.tar\.xz$" } | Select-Object -First 1
        if (-not $asset) { throw 'no Windows LLVM tarball in the latest release' }

        $version = ($release.tag_name -replace 'llvmorg-', '')
        $dest = Join-Path $env:LOCALAPPDATA "llvm-$version"
        $archive = Join-Path $env:TEMP "clang-llvm-$version.tar.xz"

        if (-not (Test-Path $archive)) {
            Write-Host "    downloading ~860 MB LLVM $version..."
            & curl.exe -L --retry 5 --retry-delay 3 -o $archive $asset.browser_download_url
            if ($LASTEXITCODE -ne 0) { throw "LLVM download failed ($LASTEXITCODE)" }
        }
        Write-Host '    extracting...'
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        & tar.exe -xf $archive -C $dest
        if ($LASTEXITCODE -ne 0) { throw "LLVM extraction failed ($LASTEXITCODE)" }

        $llvmBin = Get-ChildItem $dest -Recurse -Filter clang-cl.exe |
            Select-Object -First 1 | ForEach-Object { $_.Directory.FullName }
        if (-not $llvmBin) { throw 'clang-cl.exe not found after extraction' }
        Write-Ok "clang-cl at $llvmBin"
    } catch {
        throw @"
Could not install LLVM automatically: $($_.Exception.Message)

This is needed because one Tauri dependency compiles C code.
Either install Visual Studio Build Tools (with the C++ workload) instead,
or download a portable LLVM manually and re-run this script.
"@
    }
}

# ------------------------------------------------------------------ 4. node ---
Write-Step 'Checking node / npm'
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'node not found on PATH. Install Node.js 20+ then re-run.'
}
Write-Ok "node $(node --version)"

# ------------------------------------------------------------ 5. npm install ---
Write-Step 'Installing desktop npm dependencies'
Push-Location $desktop
try {
    if (-not (Test-Path 'node_modules')) {
        & npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install failed with exit code $LASTEXITCODE" }
    }
    Write-Ok 'node_modules present'
} finally {
    Pop-Location
}

# ----------------------------------------------------------------- 6. icons ---
if (-not (Test-Path (Join-Path $desktop 'src-tauri\icons\icon.ico'))) {
    Write-Step 'Generating Tauri icons'
    & python (Join-Path $PSScriptRoot 'gen-icons.py')
    if ($LASTEXITCODE -ne 0) { throw 'icon generation failed' }
}

Write-Host ''
Write-Host 'Toolchain ready.' -ForegroundColor Green
Write-Host '  Build the Rust side:  desktop\scripts\cargo-x.cmd build --manifest-path desktop\src-tauri\Cargo.toml'
Write-Host '  Run the desktop app:  cd desktop; npm run tauri dev'
Write-Host '  Run all tests:        desktop\scripts\verify.ps1'