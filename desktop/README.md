# RAG Benchmark Console

A Tauri desktop app for running and inspecting the DQN-RAG benchmark: start a run
of the retrieval system against a question set, watch it live, and afterwards
compare system A (fixed k) against system B (a reinforcement-learned choice of k).

The Python package in `../bench_bridge` is the sidecar that actually runs the
benchmark. This app never reimplements it - it spawns the sidecar, reads its
event stream, persists it, and renders it.

## Quick start

```powershell
npm install
npm run tauri:dev
```

`npm run tauri:dev` (not `npm run dev`) is the entry point. A plain browser has
no Tauri IPC, so the Run page cannot start anything and the shell shows an
explicit banner saying as much.

## How the two halves fit together

```
bench_bridge (Python)          this app (Rust + React)
─────────────────────          ────────────────────────
one NDJSON object per line  ──▶ runner::pump
log lines to stderr       ──▶ runner log thread → EventConsole
                            └──▶ store::apply → SQLite (the only writer)
                                 └──▶ emit bench://event → Zustand → UI
```

Three properties are load-bearing:

- **Rust is the only thing that touches SQLite.** The sidecar has no database
  code, so a run is never half-persisted, and re-delivering an event replaces it
  rather than duplicating it (`run_events` is keyed on `(run_id, seq)`).
- **stdout is data, stderr is prose.** Anything the sidecar cannot parse is
  skipped with a visible error instead of failing a run that may be hours long.
- **An absent metric is `NULL`, never `0`.** A missing judge score and a score of
  zero are different facts, and the charts depend on the difference.

## Layout

| Path | What lives there |
| --- | --- |
| `src/pages/RunPage.tsx` | Run configuration, live progress, prompt table |
| `src/pages/ResultsPage.tsx` | Stored-run analytics, metric distributions, DQN curves |
| `src/pages/SimulationPage.tsx` | Replay of a stored run, 3D pipeline |
| `src/components/three/` | PCA projection and pipeline, in three.js |
| `src/store/runStore.ts` | Live run state, fed by the `bench://event` subscription |
| `src/lib/api.ts` | Typed wrappers over the Tauri commands |
| `src-tauri/src/runner.rs` | Spawns the sidecar, reads stdout, owns process lifetime |
| `src-tauri/src/store.rs` | Every SQL statement |
| `src-tauri/src/db.rs` | Schema plus the additive migration |
| `e2e/` | Playwright tests over the built app with stubbed IPC |

Results and Simulation are `lazy()`, so the Run page - the thing you most often
open to start something - does not pay for Recharts and three.js up front.

Routing is a hash (`#/results`) rather than the history API. In a packaged build
Tauri serves assets over its own protocol, where `/results` would be a request
for a file that does not exist; the dev server's SPA fallback hides this until
after release.

## Tests

```powershell
npm test          # Vitest, unit and component
npm run e2e       # Playwright, against a production build
npm run typecheck # tsc -b
npm run lint      # oxlint
```

Or everything at once, which is what CI should run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

That covers the Python suite, the Rust suite, the Rust/sidecar subprocess
contract, Rust formatting, TypeScript, lint, Vitest, the production build,
Playwright, and a real sidecar dry run whose NDJSON is parsed and checked.
Useful switches:

```powershell
.\scripts\verify.ps1 -SkipE2E      # skip the Playwright and build steps
.\scripts\verify.ps1 -SkipSidecar   # skip both sidecar steps
```

`-SkipSidecar` drops the two checks that spawn Python. The dry run needs no
models or database - `--dry-run` swaps in in-process fakes - but both steps do
need the package importable from the repository.

The two languages only ever meet as processes, so one check spawns the actual
sidecar with the exact argv the host builds and requires a clean exit, a
terminal event, and the `run_id` that was asked for. That test is
`#[ignore]`d, because a plain `cargo test` cannot assume the Python package is
importable; `verify.ps1` runs the ignored tests as its own step. It exists
because the argv used to be structurally correct and still rejected outright -
the host was assembling `--run-id` and repeated `--system` flags that
`bench_bridge` has never accepted.

Playwright runs against `vite preview` on `http://localhost:4173`. Use
`localhost`, not `127.0.0.1`: this machine resolves `localhost` to `::1`, which
is where the preview server binds.

## Verifying the real window

`verify.ps1` stubs the host or talks to the sidecar directly, so a whole layer can
be broken without it noticing. The window is its own gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-window.ps1
```

It starts the app, drives three flows through the actual WebView, and checks the
database afterwards:

1. a dry run that must land as `completed` with its skipped judge metrics still
   `NULL`;
2. a real run that must be interrupted and land as `cancelled`;
3. `get_run_detail`, `get_projection_data` and `delete_run` driven through the
   Results and Simulation pages, ending with the run deleted and every row, prompt
   and event count back where it started.

It finishes by confirming the window still answers.

Flows 1 and 2 happen in the same window on purpose. Cancelling the second run of a
session is what was broken, and only because Tauri keeps the first value it is
given for a managed type: re-managing the per-run handle was silently ignored, so
every cancel after the first one targeted a dead process and the run carried on
to completion while the UI claimed otherwise. `runner::ActiveRunSlot` exists for
that reason - the slot is managed once and the handle is swapped inside it - and
`run_in_progress` was reading the same stale handle, so a second run could also be
started alongside a live one.

Flow 3 runs last because it cleans up after itself, and because by then the picker
has more than one run in it, which is the case a stale default selection would fail.

### Commands with no UI

Six commands are registered, tested at the store layer, and unreachable from the
window, because no page offers an affordance for them: `run_in_progress`,
`get_run_events`, `get_stats`, `get_projection`, `list_projections` and
`import_legacy`. They are referenced only from `src/lib/api.ts` and its mock.
`useRunStore.replay` is unreachable for the same reason - it exists to drive
`get_run_events`, and nothing calls either.

They cannot be driven from a script either - the app does not set
`withGlobalTauri`, so `window.__TAURI__` does not exist and there is no way to
invoke a command without something to click. Either they grow a UI, or they
should be deleted; leaving them means a rename that breaks them is invisible to
every gate here. `get_run_detail` already returns the stats and events that
`get_stats` and `get_run_events` would return separately, which is worth weighing
before wiring those two up.

### Event volume

A 20k-prompt run records around 243k events, four per prompt:
`prompt_started`, `retrieval`, `generation` and `prompt_completed`. Applying each
one as it arrived cost a Zustand update and a React render per event, and the
WebView stopped responding.

`runStore.applyEvent` now queues, and folds a whole frame's worth into a single
update. The commit count is therefore independent of the event rate: the flood
test pushes 243k events through and requires no more than
`ceil(243000 / MAX_PENDING_EVENTS)` updates, where it used to be 243,000.

Two details that are load-bearing:

- The queue is flushed outright past `MAX_PENDING_EVENTS`, because
  `requestAnimationFrame` does not fire in a hidden window and an app that was
  minimised would otherwise accumulate events forever with nothing applying them.
- The reduction reads an accumulator rather than the store, so the superseded-run
  guard sees a run id adopted earlier in the same batch. Reading the store instead
  would let a stale run's events back in.

Nothing is dropped. The database keeps every event, and the console and live
table are unchanged - only the number of updates changed. Note that
`index_progress` is *not* the type worth coalescing: across a whole run it is 56
events out of 243k, so thinning it would buy nothing while adding a timer.

The WebView is attached over the DevTools protocol rather than through
`tauri-driver`, which would need an `msedgedriver` matching the installed
WebView2 runtime version. That needs nothing installed, but it is Windows and
WebView2 only. `-SkipBuild` reuses the existing build.

## The packaged build

`verify.ps1` builds a production bundle and `verify-window.ps1` runs the app from
`tauri dev`, so between them they leave the one thing a release build does
differently untested: the packaged window serves its assets from Tauri's own
`tauri.localhost` protocol instead of the Vite dev server, and every route and
asset reference resolves against that. That is where hash routing would break -
`#/results` becomes a request for a file called `results`, which does not exist
in the bundle - and where the sidecar would fail to launch from a process that
inherits nothing from a dev shell.

`smoke-packaged.ps1` covers it, driving the built executable on a separate port:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke-packaged.ps1
```

It is a separate script on purpose. Sharing one with `verify-window.ps1` would
mean the launch was conditional on which mode was under test, and the mode is
the thing being tested.

Note that `cargo build --release` is not a substitute for `npm run tauri build`
here. A plain cargo build bakes `devUrl` into the binary, so the result loads
`localhost:1420` and looks healthy while testing nothing. The smoke script's
`tauri.localhost` assertion is what catches that, which is the argument for
asserting on the URL at all.

## Runs left behind by a dead host

Every settlement path - `fail_run`, `cancel_run`, the terminal event handlers -
runs *inside* the host, so it only sees outcomes it was still alive to observe. A
host killed outright (`taskkill /F`, a crash, a power cut) reaches none of them,
and the row stays `running` forever. That is not cosmetic: the Run page refuses
to start while anything looks in progress, so one phantom run wedges the app
permanently.

`Store::reconcile_interrupted_runs` sweeps those at startup, where a `running`
row is stale by definition - the process that owned it is the one that just
exited. It marks them `failed` rather than `cancelled`, because nothing asked for
them to stop, and records why in the error column.

The reasoning depends on there being one host per database, which is the same
assumption the single `ActiveRunSlot` and the single-writer SQLite connection
already make. A real deployment wants `tauri-plugin-single-instance` in front of
`setup`, and the doc comment on the sweep says so.

When a run misbehaves, `scripts/run-timeline.py` prints its events with offsets
from the first, which distinguishes "carried on after the cancel" from "was
killed and then overwritten" - two failures that look identical in the run row.

```powershell
python .\scripts\run-timeline.py ..\data\bench\runs.sqlite3 <run-id>
```

## Building without Visual Studio Build Tools

This machine has no MSVC install, so `cargo` alone cannot link. Two wrappers set
up a working toolchain:

```powershell
.\scripts\cargo-x.cmd test          # cargo, with headers, a linker and clang-cl
.\scripts\tauri-x.cmd dev           # the Tauri CLI, same environment
```

Both delegate to `scripts/rust-env.cmd`, which points `LIB`/`INCLUDE` at
cargo-xwin's cached Windows SDK, uses rustup's `rust-lld` as the linker and
portable LLVM's `clang-cl` as the C compiler. They are shared rather than
duplicated because the Tauri CLI spawns `cargo` in a child process and inherits
this environment - with `cargo` off `PATH` it fails immediately with
`failed to run 'cargo metadata'`.

`npm run tauri` is wired to `tauri-x.cmd`, so `npm run tauri:dev` and
`npm run tauri:build` work without any of this being set up by hand.

## Adding a database column

`CREATE TABLE IF NOT EXISTS` will not add a column to a table that already
exists, so opening a database written by an older build would leave it missing
that column and every later insert would fail. `src-tauri/src/db.rs` therefore
keeps a second list, `ADDED_COLUMNS`, which `migrate` diffs against
`PRAGMA table_info` on every open.

To add one: append it to **both** `SCHEMA` (for a fresh database) and
`ADDED_COLUMNS` (for an existing one). Additive only - a rename or a narrowed
type needs an explicit migration and a `SCHEMA_VERSION` bump.

Only nullable or defaulted columns are listed, because SQLite's
`ALTER TABLE ADD COLUMN` cannot add a constraint. That is also why old rows keep
their `NULL`s instead of being back-filled with a fabricated zero.