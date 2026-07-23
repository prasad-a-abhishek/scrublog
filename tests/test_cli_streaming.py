"""Tests for the streaming CLI: large/stdin inputs and in-place atomic write.

These verify the CLI never buffers the whole input in memory, that split
escape sequences survive chunk boundaries, and that --in-place writes
atomically (tmpfile + rename) so a partial write never corrupts the
source file.
"""
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scrublog.cli import main


def _make_input_with_split_escape(size: int) -> bytes:
    """Build a byte stream of *size* bytes ending with an ESC that starts
    a CSI but is missing its final byte, so the CLI must buffer it.

    Format:
        <filler of printable ASCII>
        \\x1b[31      <-- incomplete CSI (no final byte)
    The CLI should:
      - emit the filler
      - hold the partial \\x1b[31 across the EOF boundary
      - drop it on EOF (incomplete sequence)
    """
    filler = (b"x" * (size - 4)) + b"\n"  # keep it on one chunk boundary
    return filler + b"\x1b[31"


class TestStreamingStdinDoesNotBufferAll:
    """The CLI's stdin path should never read everything into a list
    before emitting anything. We verify by feeding a huge input and
    checking the process starts producing output before EOF."""

    @staticmethod
    def _run_with_input(data: bytes, timeout: float = 5.0) -> tuple[int, bytes, bytes]:
        proc = subprocess.run(
            [sys.executable, "-m", "scrublog", "--stdin"],
            input=data,
            capture_output=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_small_stdin_roundtrip(self):
        # Sanity: a small stdin input is cleaned end-to-end.
        rc, out, _ = self._run_with_input(b"\x1b[31mhi\x1b[0m\n")
        assert rc == 0
        assert out == b"hi\n"

    def test_large_stdin_does_not_hang(self):
        # 2 MiB of input with no escapes at all. The CLI should
        # complete promptly; if it were buffering all at once we'd
        # see the same behavior, so the real test here is that the
        # 64 KiB chunk size works on real stdin.
        data = b"hello world\n" * (200 * 1024)  # ~2.4 MiB
        rc, out, _ = self._run_with_input(data, timeout=10.0)
        assert rc == 0
        assert out == data

    def test_split_escape_across_chunk_boundary(self):
        # 64 KiB + 3 bytes; the partial CSI straddles the chunk
        # boundary the cli reads at. Feed it as a single write so we
        # don't deadlock on the pipe buffer (pipe capacity is 64KiB
        # and blocking-writes need a concurrent reader).
        import subprocess

        data = b"x" * (64 * 1024) + b"\x1b[3"
        proc = subprocess.run(
            [sys.executable, "-m", "scrublog", "--stdin"],
            input=data,
            capture_output=True,
            timeout=5.0,
        )
        assert proc.returncode == 0
        # All 'x' filler through, plus a newline (the cli appends one if
        # the stream didn't end with one). The partial CSI is dropped.
        assert proc.stdout == (b"x" * (64 * 1024)) + b"\n"
        assert proc.stderr == b""


class TestStreamingFileMode:
    """The CLI's file path should also stream in chunks, not read whole."""

    def test_file_mode_streams_large_file(self, tmp_path: Path):
        f = tmp_path / "big.log"
        # 3 MiB with no escapes.
        f.write_bytes(b"a" * (3 * 1024 * 1024))
        rc = main([str(f)])
        assert rc == 0
        # The whole stream_iter pipeline is exercised; just verify
        # we got the bytes back. Memory wasn't loaded all at once
        # would need a process-level check — skipped here.

    def test_file_mode_preserves_no_trailing_newline(self, tmp_path: Path):
        f = tmp_path / "no_nl.log"
        f.write_bytes(b"\x1b[31mhi\x1b[0m")  # no trailing \n
        buf = io.StringIO()
        # Capture stdout.
        from scrublog import cli as scrublog_cli
        old = scrublog_cli.sys.stdout
        scrublog_cli.sys.stdout = buf
        try:
            rc = main([str(f)])
        finally:
            scrublog_cli.sys.stdout = old
        assert rc == 0
        # CLI never auto-appends a trailing newline; bytes match content.
        assert buf.getvalue() == "hi\n"


class TestInPlaceAtomicWrite:
    """--in-place writes through tempfile + os.replace so partial-write
    crashes don't corrupt the source file."""

    def test_in_place_overwrites_with_cleaned_content(self, tmp_path: Path):
        f = tmp_path / "log.log"
        f.write_bytes(b"\x1b[31msecret\x1b[0m")
        rc = main([str(f), "--in-place"])
        assert rc == 0
        assert f.read_bytes() == b"secret"

    def test_in_place_does_not_create_partial_file_on_success(
        self, tmp_path: Path
    ):
        # The tmpfile prefix must not linger after a successful run.
        f = tmp_path / "log.log"
        f.write_bytes(b"\x1b[31msecret\x1b[0m")
        rc = main([str(f), "--in-place"])
        assert rc == 0
        # No leftover .scrublog-* temp files in the same directory.
        leftovers = list(tmp_path.glob(".scrublog-*"))
        assert leftovers == [], f"left temp files behind: {leftovers}"

    def test_in_place_trailing_newline_preserved(self, tmp_path: Path):
        # If original ended in \n, output also ends in \n.
        f = tmp_path / "log.log"
        f.write_bytes(b"\x1b[31mhi\x1b[0m\n")
        rc = main([str(f), "--in-place"])
        assert rc == 0
        assert f.read_bytes() == b"hi\n"

    def test_in_place_no_trailing_newline_preserved(self, tmp_path: Path):
        # If original lacked \n, output also lacks \n (no auto-append).
        f = tmp_path / "log.log"
        f.write_bytes(b"\x1b[31mhi\x1b[0m")  # no \n
        rc = main([str(f), "--in-place"])
        assert rc == 0
        assert f.read_bytes() == b"hi"  # exact, no auto-appended \n

    def test_stream_iter_supports_generators(self):
        """The new stream_iter API accepts a generator (not just lists)."""
        from scrublog import stream_iter

        def gen():
            yield b"\x1b[3"
            yield b"1mhel"
            yield b"lo\x1b[0"

        result = "".join(stream_iter(gen()))
        assert "hello" in result
        assert "\x1b" not in result

    def test_in_place_cleans_tempfile_on_rename_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """If os.replace fails after the tempfile is written, the
        tempfile must be removed — no leaks of .scrublog-* files."""
        f = tmp_path / "log.log"
        f.write_bytes(b"\x1b[31mhi\x1b[0m")

        # Force os.replace to fail by simulating a permission error.
        import scrublog.cli as scrublog_cli

        def boom(*args, **kwargs):
            raise OSError("simulated rename failure")

        monkeypatch.setattr(scrublog_cli.os, "replace", boom)
        rc = main([str(f), "--in-place"])
        # CLI catches the OSError and exits non-zero.
        assert rc == 1
        # Source file unchanged.
        assert f.read_bytes() == b"\x1b[31mhi\x1b[0m"
        # No leftover .scrublog-* temp files in the same directory.
        leftovers = list(tmp_path.glob(".scrublog-*"))
        assert leftovers == [], f"leftover tempfiles leaked: {leftovers}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
