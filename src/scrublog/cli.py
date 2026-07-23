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

from . import __version__, clean, stream, stream_iter

# 64 KiB read chunk: large enough to amortize syscall overhead, small enough
# that a 100MB scrub doesn't sit idle on the user's monitor.
_STDIN_CHUNK_BYTES = 64 * 1024


def _read_chunks(fp, chunk_size: int):
    """Yield bytes from *fp* in fixed-size chunks until EOF.

    This is intentionally its own helper (rather than reading the whole
    stream into memory) so the CLI can process infinitely-tailed inputs
    like ``docker logs -f | scrublog`` without OOM-ing.
    """
    while True:
        chunk = fp.read(chunk_size)
        if not chunk:
            return
        yield chunk


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

    # ---- Stdin branch: stream chunks, don't buffer ----

    if using_stdin:
        # Read in fixed-size chunks so we don't OOM on large or infinite
        # stdin (e.g. `docker logs -f | scrublog`). 64 KiB matches one
        # common pipe buffer and keeps the per-call overhead small.
        stdin_buf = sys.stdin.buffer
        stdout_buf = sys.stdout
        saw_any_input = False
        ends_with_newline = True  # default so we don't append one unnecessarily
        # Use the package's stream() to handle escape sequences split
        # across chunk boundaries correctly.
        for cleaned in stream_iter(_read_chunks(stdin_buf, _STDIN_CHUNK_BYTES)):
            saw_any_input = True
            stdout_buf.write(cleaned)
            ends_with_newline = cleaned.endswith("\n")
        if saw_any_input and not ends_with_newline:
            stdout_buf.write("\n")
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

    # Symlink protection only applies for write modes (--in-place).
    # For read-only mode (stdout), following a symlink is fine — it's
    # the user's choice and there's no overwrite to defend against.
    if args.in_place and _has_symlink_component(p) and not args.follow_symlinks:
        print(
            f"error: refusing --in-place on path with symlink component {p!s} "
            "(pass --follow-symlinks to override)",
            file=sys.stderr,
        )
        return 1

    # Stream the file in chunks instead of reading it whole. The
    # special-file check above already guards against /dev/zero and
    # similar infinite sources, so we can safely open and iterate.
    try:
        with open(p, "rb") as fp:
            saw_any_input = False
            ends_with_newline = True
            if args.in_place:
                # Use a tempfile + atomic rename so we don't truncate the
                # source until the cleaned content is fully written. This
                # protects against partial writes on disk-full / signal.
                # For --in-place we preserve byte-for-byte equivalence of
                # the file other than the ANSI removal — i.e. we do NOT
                # append a trailing newline if the original lacked one.
                try:
                    import tempfile

                    fd, tmp_path = tempfile.mkstemp(
                        prefix=".scrublog-", dir=str(p.parent)
                    )
                    # Track both so cleanup is correct even if mkstemp
                    # succeeds but fdopen or the cleanup itself raises.
                    tmp_fp = None
                    try:
                        tmp_fp = os.fdopen(fd, "wb")
                        for cleaned in stream_iter(
                            _read_chunks(fp, _STDIN_CHUNK_BYTES)
                        ):
                            tmp_fp.write(cleaned.encode("utf-8"))
                    except BaseException:
                        # Best-effort cleanup on ANY failure (including
                        # KeyboardInterrupt, MemoryError, etc.).
                        if tmp_fp is not None:
                            try:
                                tmp_fp.close()
                            except Exception:
                                pass
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                        raise
                    tmp_fp.flush()
                    tmp_fp.close()
                except OSError as e:
                    print(f"error: {e}", file=sys.stderr)
                    return 1

                # Atomic rename. When --follow-symlinks is set, write
                # through to the resolved target; otherwise the early
                # symlink-component check above already blocked us, and
                # os.replace on the user's path is what they expect.
                try:
                    if args.follow_symlinks:
                        target = p.resolve()
                    else:
                        target = p
                    os.replace(tmp_path, target)
                except OSError as e:
                    print(f"error: {e}", file=sys.stderr)
                    # Clean up the orphan tempfile if the rename failed.
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    return 1
                return 0

            # Plain stdout mode: stream chunks straight to stdout.
            for cleaned in stream_iter(_read_chunks(fp, _STDIN_CHUNK_BYTES)):
                saw_any_input = True
                sys.stdout.write(cleaned)
                ends_with_newline = cleaned.endswith("\n")
            if saw_any_input and not ends_with_newline:
                sys.stdout.write("\n")
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
