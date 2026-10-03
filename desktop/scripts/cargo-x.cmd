@echo off
REM ---------------------------------------------------------------------------
REM cargo-x.cmd - build Rust/Tauri on Windows without Visual Studio Build Tools.
REM
REM Supplies three things cargo would otherwise get from an MSVC install:
REM   1. import libraries + headers  -> cargo-xwin cache in %LOCALAPPDATA%
REM   2. a linker                    -> rustup's rust-lld, invoked as lld-link
REM   3. a C/C++ compiler            -> clang-cl from the portable LLVM install
REM
REM (3) exists because tauri's `vswhom-sys` dependency compiles a C shim, and
REM cc-rs refuses to build without a compiler even though the Rust code itself
REM needs none.
REM
REM The environment itself lives in rust-env.cmd, shared with tauri-x.cmd - the
REM Tauri CLI spawns `cargo` in a child process and needs the same variables, so
REM keeping one copy of the setup is what stops the two entry points drifting.
REM
REM Usage:
REM   scripts\cargo-x.cmd build
REM   scripts\cargo-x.cmd test
REM   scripts\cargo-x.cmd clippy --all-targets -- -D warnings
REM ---------------------------------------------------------------------------
setlocal

call "%~dp0rust-env.cmd"
if errorlevel 1 exit /b %ERRORLEVEL%

cargo %*
exit /b %ERRORLEVEL%