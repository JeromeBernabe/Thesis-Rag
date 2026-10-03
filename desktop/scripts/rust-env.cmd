@echo off
REM ---------------------------------------------------------------------------
REM rust-env.cmd - put a buildable Rust toolchain on the current environment.
REM
REM Shared by cargo-x.cmd and tauri-x.cmd. Exports everything cargo needs to
REM compile and link the x86_64-pc-windows-msvc target on a machine with no
REM Visual Studio Build Tools, then returns to the caller with those variables
REM still set.
REM
REM Intended to be used with `call`, not executed:
REM
REM   call scripts\rust-env.cmd
REM   cargo build
REM
REM Deliberately no `setlocal`: the point is to leak these variables into the
REM calling script's environment. A `setlocal` here would discard them the
REM moment this file returns, which is the single easiest way to get a confusing
REM "linker not found" further down. The callers own the scope instead.
REM
REM Callers that shell out to their own sub-tools - the Tauri CLI in particular -
REM need this as much as cargo does, because they spawn `cargo` themselves and
REM would otherwise fail with "failed to run 'cargo metadata'".
REM ---------------------------------------------------------------------------

REM ---------------------------------------------------------------- 0. cargo ---
REM Cargo is not on the machine's PATH, so add it. Everything below shells out
REM to rustc, which resolves its own sysroot, so this is the only PATH entry
REM strictly required.
if not exist "%USERPROFILE%\.cargo\bin\cargo.exe" (
  echo [rust-env] ERROR: cargo not found at "%USERPROFILE%\.cargo\bin". 1>&2
  echo [rust-env] Run scripts\setup-toolchain.ps1 first. 1>&2
  exit /b 9009
)
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

REM --------------------------------------------------- 1. MSVC headers + libs ---
REM Without Build Tools there is no Windows SDK, so cargo-xwin's extracted copy
REM stands in for both the CRT headers and the import libraries.
set "XWIN=%LOCALAPPDATA%\cargo-xwin\xwin"
if not exist "%XWIN%\crt\include\excpt.h" (
  echo [rust-env] ERROR: MSVC headers missing under "%XWIN%\crt\include". 1>&2
  echo [rust-env] Run scripts\setup-toolchain.ps1 first. 1>&2
  exit /b 9009
)
if not exist "%XWIN%\crt\lib\x86_64\msvcrt.lib" (
  echo [rust-env] ERROR: MSVC import libraries missing under "%XWIN%\crt\lib". 1>&2
  echo [rust-env] Run scripts\setup-toolchain.ps1 first. 1>&2
  exit /b 9009
)

set "LIB=%XWIN%\crt\lib\x86_64;%XWIN%\sdk\lib\ucrt\x86_64;%XWIN%\sdk\lib\um\x86_64"
set "INCLUDE=%XWIN%\crt\include;%XWIN%\sdk\include\ucrt;%XWIN%\sdk\include\um;%XWIN%\sdk\include\shared"

REM ------------------------------------------------------------ 2. C compiler ---
REM setup-toolchain.ps1 records the resolved clang-cl directory here.
set "LLVM_BIN="
for /f "delims=" %%I in ('dir /b /ad "%LOCALAPPDATA%\llvm-*" 2^>nul') do set "LLVM_CAND=%LOCALAPPDATA%\%%I"
if defined LLVM_CAND (
  if exist "!LLVM_CAND!\bin\clang-cl.exe" set "LLVM_BIN=!LLVM_CAND!\bin"
)
REM Recurse one level: the archive unpacks to llvm-VER\clang+llvm-VER-...\ .
if not defined LLVM_BIN (
  for /d %%D in ("%LOCALAPPDATA%\llvm-*") do (
    if exist "%%D\bin\clang-cl.exe" set "LLVM_BIN=%%D\bin"
    if not defined LLVM_BIN (
      for /d %%E in ("%%D\*") do (
        if exist "%%E\bin\clang-cl.exe" set "LLVM_BIN=%%E\bin"
      )
    )
  )
)
if not defined LLVM_BIN (
  echo [rust-env] ERROR: clang-cl.exe not found under "%LOCALAPPDATA%\llvm-*". 1>&2
  echo [rust-env] Run scripts\setup-toolchain.ps1 to install portable LLVM. 1>&2
  exit /b 9009
)

set "PATH=%LLVM_BIN%;%PATH%"
REM Tauri's `vswhom-sys` dependency compiles a C shim, and cc-rs refuses to build
REM without a compiler even though the Rust code itself needs none.
set "CC_x86_64_pc_windows_msvc=%LLVM_BIN%\clang-cl.exe"
set "CXX_x86_64_pc_windows_msvc=%LLVM_BIN%\clang-cl.exe"
set "AR_x86_64_pc_windows_msvc=%LLVM_BIN%\llvm-lib.exe"
REM tauri-winres shells out to rc.exe to build the Win32 icon resource that
REM gets embedded in the .exe. llvm-rc understands the same MSVC-style flags.
set "RC=%LLVM_BIN%\llvm-rc.exe"
set "RC_x86_64_pc_windows_msvc=%LLVM_BIN%\llvm-rc.exe"

REM --------------------------------------------------------------- 3. linker ---
REM Copy lld-link into a repo-local gitignored dir on every invocation. Doing it
REM per-run (rather than once) keeps it correct across rustup toolchain upgrades.
set "LLCACHE=%~dp0..\.toolchain"
if not exist "%LLCACHE%" mkdir "%LLCACHE%" >nul 2>&1
for /f "delims=" %%I in ('rustc --print sysroot') do set "SYSROOT=%%I"
set "RUSTLLD=%SYSROOT%\lib\rustlib\x86_64-pc-windows-msvc\bin\rust-lld.exe"
if not exist "%RUSTLLD%" (
  echo [rust-env] ERROR: rust-lld.exe not found under "%SYSROOT%". 1>&2
  echo [rust-env] The x86_64-pc-windows-msvc Rust target may be missing. 1>&2
  exit /b 9009
)
copy /y "%RUSTLLD%" "%LLCACHE%\lld-link.exe" >nul
set "PATH=%LLCACHE%;%PATH%"

REM Set the linker as an env var rather than relying on .cargo/config.toml:
REM Cargo discovers config relative to the *current directory*, so a
REM `--manifest-path` invocation from the repo root would silently fall back to
REM link.exe and fail. The env var applies regardless of where cargo runs.
set "CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER=%LLCACHE%\lld-link.exe"