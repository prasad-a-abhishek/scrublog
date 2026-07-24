"""Completion-spec regression tests for scrublog cycle 1.

These tests target gaps not exercised by the original 120-test baseline:
UTF-8 code points split across byte chunks, bounded partial-control buffering,
strictly chunked CLI reads, and README/API truthfulness.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

import scrublog
import scrublog.cli as cli


class RecordingBytesIO(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.read_sizes: list[int] = []

    def read(self, size: int | None = -1) -> bytes:
        self.read_sizes.append(size if size is not None else -1)
        assert size is not None and 0 < size <= cli._STDIN_CHUNK_BYTES
        return super().read(size)


@pytest.mark.parametrize(
    "encoded",
    [
        "é".encode(),
        "€".encode(),
        "🚀".encode(),
        "e\u0301".encode(),
        "العربية".encode(),
    ],
)
def test_stream_iter_preserves_utf8_split_at_every_boundary(encoded: bytes):
    for split in range(1, len(encoded)):
        chunks = [b"prefix ", encoded[:split], encoded[split:], b" suffix"]
        assert "".join(scrublog.stream_iter(chunks)) == (
            b"prefix " + encoded + b" suffix"
        ).decode("utf-8")


def test_stream_iter_preserves_utf8_split_one_byte_per_chunk():
    data = "plain café العربية 🚀 done".encode("utf-8")
    assert "".join(scrublog.stream_iter(bytes([b]) for b in data)) == data.decode()


def test_stream_iter_latin1_fallback_remains_lossless_for_invalid_bytes():
    assert "".join(scrublog.stream_iter([b"ok", b"\xff", b"done"])) == "okÿdone"


def test_cli_stdin_reader_never_uses_unbounded_read():
    fp = RecordingBytesIO(b"x" * (cli._STDIN_CHUNK_BYTES + 7))
    assert b"".join(cli._read_chunks(fp, cli._STDIN_CHUNK_BYTES)) == (
        b"x" * (cli._STDIN_CHUNK_BYTES + 7)
    )
    assert fp.read_sizes == [cli._STDIN_CHUNK_BYTES] * 3


def test_cli_file_reader_never_uses_unbounded_read():
    fp = RecordingBytesIO(b"file payload")
    assert b"".join(cli._read_chunks(fp, 4)) == b"file payload"
    assert fp.read_sizes == [4, 4, 4, 4]


def test_stream_partial_control_tail_never_exceeds_cap(monkeypatch):
    monkeypatch.setattr(scrublog, "_MAX_BUFFER_BYTES", 32)
    payload = "\x1b]" + ("x" * 33)
    assert "".join(scrublog.stream_iter([payload, "visible"])) == payload + "visible"


def test_readme_documents_stream_iter_and_incomplete_tail_policy():
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    assert "stream_iter" in readme
    assert "incomplete" in readme.lower()
    assert "unterminated" in readme.lower()


def test_readme_documents_cli_safety_and_exit_codes():
    readme = (Path(__file__).parents[1] / "README.md").read_text().lower()
    for phrase in ("special file", "follow-symlinks", "exit codes", "terminal emulator"):
        assert phrase in readme


def test_readme_does_not_claim_obsolete_test_count():
    readme = (Path(__file__).parents[1] / "README.md").read_text().lower()
    assert "25 tests" not in readme


def test_readme_single_character_example_matches_implementation():
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    assert "`\\x1bc`" in readme
    assert scrublog.clean("\x1bcvisible") == "visible"
