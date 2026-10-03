"""Entry point for the sidecar: ``python -m bench_bridge``.

stdout carries the NDJSON event stream and nothing else - the Rust host parses
it line by line. Anything a human might want to read therefore goes to stderr,
because a stray ``print`` on stdout would be read as a malformed event and
could fail the run.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from bench_bridge.run import Runner, spec_from_args

    spec = spec_from_args(argv)
    runner = Runner(spec)
    code = runner.run_guarded()
    # The host reads events until EOF, so the stream must be flushed before exit.
    try:
        sys.stdout.flush()
    except BrokenPipeError:
        return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())