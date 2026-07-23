"""Command-line entry point for scrublog.

Usage:
    scrublog <file>          Strip ANSI from <file>, print to stdout.
    scrublog <file> -i       Strip in place (overwrite the file).
    scrublog --stdin         Read from stdin, write to stdout.
    scrublog -               Shorthand for --stdin.

Exit codes:
    0  success
    1  usage / I/O error
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import clean


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scrublog",
        description="Strip ANSI escape codes from logs, byte streams, and CLI output.",
    )
    p.add_argument("path", nargs="?", help="File to clean. Use - or --stdin for stdin.")
    p.add_argument("-i", "--in-place", action="store_true",
                   help="Overwrite the file with cleaned contents.")
    p.add_argument("--stdin", action="store_true",
                   help="Read from stdin (alternative to passing '-' as path).")
    p.add_argument("--version", action="store_true", help="Print version and exit.")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    if args.version:
        print("scrublog 0.1.0")
        return 0

    # Disallow both stdin and a path.
    if args.stdin and args.path not in (None, ""):
        print("error: cannot use --stdin together with a file path", file=sys.stderr)
        raise SystemExit(1)

    if args.stdin or args.path == "-":
        data = sys.stdin.buffer.read()
        sys.stdout.write(clean(data))
        if not data.endswith(b"\n"):
            sys.stdout.write("\n")
        return 0

    if not args.path:
        print("error: provide a file path, '-', or --stdin", file=sys.stderr)
        return 1

    p = Path(args.path)
    try:
        raw = p.read_bytes()
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    cleaned = clean(raw)
    if args.in_place:
        p.write_bytes(cleaned.encode("utf-8"))
    else:
        sys.stdout.write(cleaned)
        if not cleaned.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
