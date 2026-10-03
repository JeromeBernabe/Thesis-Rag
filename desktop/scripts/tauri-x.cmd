@echo off
REM ---------------------------------------------------------------------------
REM tauri-x.cmd - run the Tauri CLI on Windows without Visual Studio Build Tools.
REM
REM `npm run tauri` alone fails on this machine with:
REM
REM   failed to run 'cargo metadata' command to get workspace directory:
REM   program not found
REM
REM because cargo is not on the machine's PATH and, even once it is, the CLI
REM shells out to `cargo build` for the Rust half - so the linker and C compiler
REM have to be in its environment as well. The CLI inherits this process's
REM environment, so setting it up here is what makes it work.
REM
REM The same setup lives in rust-env.cmd, shared with cargo-x.cmd.
REM
REM Usage:
REM   scripts\tauri-x.cmd dev
REM   scripts\tauri-x.cmd build
REM   scripts\tauri-x.cmd icon path\to\icon.png
REM ---------------------------------------------------------------------------
setlocal

call "%~dp0rust-env.cmd"
if errorlevel 1 exit /b %ERRORLEVEL%

REM The CLI is a local dev dependency, so run the installed binary rather than
REM resolving it fresh from the registry.
set "TAURI_BIN=%~dp0..\node_modules\.bin\tauri.cmd"
if not exist "%TAURI_BIN%" (
  echo [tauri-x] ERROR: %TAURI_BIN% not found. 1>&2
  echo [tauri-x] Run `npm install` in desktop\ first. 1>&2
  exit /b 9009
)

call "%TAURI_BIN%" %*
exit /b %ERRORLEVEL%