"""Tests for scrublog — TDD RED phase. All tests should fail initially."""

import io
import pytest
from scrublog import clean, has_ansi, count_ansi, ScrubError


class TestClean:
    def test_clean_returns_str_for_str_input(self):
        assert clean("\x1b[31mhello\x1b[0m") == "hello"

    def test_clean_returns_str_for_bytes_input(self):
        assert clean(b"\x1b[31mhello\x1b[0m") == "hello"

    def test_clean_passes_through_plain_text(self):
        assert clean("no escapes here") == "no escapes here"

    def test_clean_strips_color_sgr_sequences(self):
        # Bold red, then normal text, then reset
        assert clean("\x1b[1;31mERROR\x1b[0m: bad") == "ERROR: bad"

    def test_clean_strips_256_color_sequences(self):
        # 256-color fg: \x1b[38;5;208m
        assert clean("\x1b[38;5;208morange\x1b[0m") == "orange"

    def test_clean_strips_truecolor_rgb_sequences(self):
        # Truecolor: \x1b[38;2;255;100;0m
        assert clean("\x1b[38;2;255;100;0mhi\x1b[0m") == "hi"

    def test_clean_strips_cursor_movement(self):
        assert clean("a\x1b[2Jb\x1b[Hc") == "abc"

    def test_clean_strips_osc_hyperlinks(self):
        # OSC 8 hyperlinks: \x1b]8;;https://x.com\x1b\\link\x1b]8;;\x1b\\
        assert clean("\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\") == "link"

    def test_clean_handles_incomplete_sequence_at_end(self):
        # Trailing ESC with nothing after it — should be dropped, not crash
        assert clean("hello\x1b") == "hello"
        assert clean("hello\x1b[") == "hello"
        assert clean("hello\x1b[3") == "hello"

    def test_clean_handles_bel_terminated_osc(self):
        # OSC terminated by \x07 (BEL) instead of ST (\x1b\\)
        assert clean("\x1b]0;title\x07body") == "body"

    def test_clean_preserves_unicode(self):
        assert clean("\x1b[31mcafé — naïve 🚀\x1b[0m") == "café — naïve 🚀"

    def test_clean_empty_string(self):
        assert clean("") == ""
        assert clean(b"") == ""

    def test_clean_only_escape_codes(self):
        assert clean("\x1b[0m\x1b[1;31m\x1b[0m") == ""


class TestHasAnsi:
    def test_has_ansi_true_for_color_sequence(self):
        assert has_ansi("\x1b[31mred\x1b[0m") is True

    def test_has_ansi_true_for_bytes(self):
        assert has_ansi(b"\x1b[31mred\x1b[0m") is True

    def test_has_ansi_false_for_plain_text(self):
        assert has_ansi("plain") is False

    def test_has_ansi_false_for_empty(self):
        assert has_ansi("") is False
        assert has_ansi(b"") is False


class TestCountAnsi:
    def test_count_ansi_counts_each_sequence(self):
        # Sequences: \x1b[31m \x1b[0m \x1b[1m \x1b[0m \x1b[2J = 5 distinct ones
        assert count_ansi("\x1b[31ma\x1b[0m \x1b[1mb\x1b[0m \x1b[2Jc") == 5

    def test_count_ansi_zero_for_plain(self):
        assert count_ansi("plain text") == 0


class TestStreamCleaning:
    def test_stream_iter_returns_chunks_without_ansi(self):
        from scrublog import stream
        chunks = list(stream(b"\x1b[31mhel\x1b[0mlo\x1b[32m!\x1b[0m"))
        assert "".join(chunks) == "hello!"

    def test_stream_split_across_escape_boundary(self):
        # The escape sequence is split across two chunks — stream must still strip it
        from scrublog import stream
        chunks = list(stream(b"\x1b[3", b"1mhi\x1b[0m"))
        assert "".join(chunks) == "hi"


class TestCli:
    def test_cli_reads_from_stdin_strips_and_writes_stdout(self, capsys, monkeypatch):
        import scrublog.cli as cli_mod
        fake_buffer = io.BytesIO(b"\x1b[31mhello\x1b[0m\n")
        monkeypatch.setattr(cli_mod.sys, "stdin", io.TextIOWrapper(fake_buffer))
        rc = cli_mod.main(["--stdin"])
        out = capsys.readouterr().out
        assert rc == 0
        assert out == "hello\n"

    def test_cli_rejects_both_stdin_and_file(self, tmp_path, capsys):
        f = tmp_path / "x.log"
        f.write_text("data")
        from scrublog.cli import main
        with pytest.raises(SystemExit) as exc:
            main([str(f), "--stdin"])
        assert exc.value.code == 1

    def test_cli_strips_file_and_writes_to_stdout(self, tmp_path, capsys):
        f = tmp_path / "log.txt"
        f.write_bytes(b"\x1b[1;31mERROR\x1b[0m: boom\n\x1b[32mOK\x1b[0m: done\n")
        from scrublog.cli import main
        rc = main([str(f)])
        out = capsys.readouterr().out
        assert rc == 0
        assert out == "ERROR: boom\nOK: done\n"

    def test_cli_in_place_flag_overwrites_file(self, tmp_path, capsys):
        f = tmp_path / "log.txt"
        f.write_bytes(b"\x1b[31mhi\x1b[0m")
        from scrublog.cli import main
        rc = main([str(f), "--in-place"])
        assert rc == 0
        assert f.read_bytes() == b"hi"
