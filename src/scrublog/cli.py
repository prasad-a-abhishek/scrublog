"""Command-line entry point for scrublog.

Usage:
    scrublog <file>                  Strip ANSI from <file>, print to stdout.
    scrublog <file> -i               Strip in place (overwrite the file).
    scrublog <file> -i --follow-symlinks
                                     Allow in-place write through a symlink.
                                     Default: refuse (security).
    scrublog <file> --allow-special-files
                                     Allow reading from /dev/zero, /dev/urandom,
                                     and other special files. Default: refuse.
    scrublog --stdin                 Read from stdin, write to stdout.
    scrublog -                       Shorthand for --stdin.

Exit codes:
    0  success
    1  I/O error (incl. refused symlink, special file, nonexistent path)
    2  usage error (e.g. --stdin --in-place together)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, clean


def _is_special_file(p: Path) -> bool:
    """True if path resolves into /dev/ (or similar special device dir on Linux).

    Used to refuse files that look regular but are actually infinite streams
    (/dev/zero) or never-ending random sources (/dev/urandom). These will OOM
    the process if read with .read_bytes().
    """
    try:
        real = p.resolve()
    except OSError:
        return False
    return str(real).startswith("/dev/")


def _has_symlink_component(p: Path) -> bool:
    """True if any component of *p* (other than the final one) is a symlink,
    or if *p* itself is a symlink.

    We walk parents because a path like /link-dir/file.log has the symlink
    in an intermediate directory. Without this check, an attacker could
    bypass the is_symlink() check by creating /link-dir → /target/ and then
    asking scrublog to --in-place /link-dir/file.log. The naive check on
    the final component only would let it through.
    """
    try:
        # Walk up to the root but stop at the first parent (don't check /).
        parent = p.parent
        while parent != parent.parent:
            if parent.is_symlink():
                return True
            parent = parent.parent
        # And finally the final component itself.
        return p.is_symlink()
    except OSError:
        # If we can't stat something, err on the side of caution and refuse.
        return True


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scrublog",
        description=(
            "Strip ANSI escape codes from logs, byte streams, and CLI output. "
            "Refuses to follow symlinks for --in-place and refuses /dev/* files "
            "by default; pass --follow-symlinks or --allow-special-files to override."
        ),
    )
    p.add_argument("path", nargs="?", help="File to clean. Use - or --stdin for stdin.")
    p.add_argument("-i", "--in-place", action="store_true",
                   help="Overwrite the file with cleaned contents.")
    p.add_argument("--follow-symlinks", action="store_true",
                   help="With --in-place: follow symlinks instead of refusing.")
    p.add_argument("--allow-special-files", action="store_true",
                   help="Allow reading from /dev/zero, /dev/urandom, etc.")
    p.add_argument("--stdin", action="store_true",
                   help="Read from stdin (alternative to passing '-' as path).")
    p.add_argument("--version", action="store_true", help="Print version and exit.")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    if args.version:
        print(f"scrublog {__version__}")
        return 0

    # ---- Reject nonsensical argument combinations (exit code 2) ----

    # --stdin (or '-') together with --in-place has no meaning.
    using_stdin = args.stdin or args.path == "-"
    if using_stdin and args.in_place:
        print(
            "error: --in-place cannot be used with --stdin or '-' "
            "(there is no file to write back to)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # --stdin (or '-') together with a real file path is contradictory: which
    # input do we use? Refuse.
    if using_stdin and args.path not in (None, "-"):
        print(
            "error: cannot use --stdin (or '-') together with a file path",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # ---- Stdin branch ----

    if using_stdin:
        data = sys.stdin.buffer.read()
        sys.stdout.write(clean(data))
        if not data.endswith(b"\n"):
            sys.stdout.write("\n")
        return 0

    # ---- File branch ----

    if not args.path:
        print("error: provide a file path, '-', or --stdin", file=sys.stderr)
        return 1

    p = Path(args.path)

    # Special-file DoS protection: /dev/zero and friends will OOM the process
    # if we try to .read_bytes() them. Refuse unless explicitly allowed.
    if not args.allow_special_files and _is_special_file(p):
        print(
            f"error: refusing to read special file {p!s} "
            "(pass --allow-special-files to override; "
            "see: scrublog /dev/zero would exhaust memory)",
            file=sys.stderr,
        )
        return 1

    try:
        raw = p.read_bytes()
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    cleaned = clean(raw)

    if args.in_place:
        # Symlink protection: refuse to overwrite through a symlink unless the
        # user explicitly opts in. Without this, `sudo scrublog -i link.log`
        # can be tricked into clobbering whatever the link points at.
        # We check both the final component AND any directory components in
        # the path so a path like /link-dir/file.log is also caught.
        if _has_symlink_component(p) and not args.follow_symlinks:
            print(
                f"error: refusing --in-place on path with symlink component {p!s} "
                "(pass --follow-symlinks to override)",
                file=sys.stderr,
            )
            return 1
        try:
            # O_NOFOLLOW is an extra defense-in-depth: even if a symlink was
            # created between the is_symlink() check above and the open() call,
            # the kernel will refuse. Skipped when the user opts in to following.
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_NOFOLLOW") and not args.follow_symlinks:
                flags |= os.O_NOFOLLOW
            fd = os.open(p, flags, 0o644)
            try:
                os.write(fd, cleaned.encode("utf-8"))
            finally:
                os.close(fd)
        except OSError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0

    sys.stdout.write(cleaned)
    if not cleaned.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
