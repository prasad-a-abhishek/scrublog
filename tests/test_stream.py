"""Streaming edge cases for scrublog.stream().

These tests pin down the contract that ``stream()`` must buffer any
incomplete / partial escape sequence (CSI / OSC / DCS / SOS / PM / APC,
and a lone trailing ESC) so it does NOT leak into output even when
the sequence is split across chunks.
"""
from scrublog import stream


def _joined(*chunks):
    return "".join(stream(*chunks))


class TestStreamSplitOscAcrossChunks:
    """OSC = ESC ] ... (BEL | ST). Must be buffered and stripped even
    when the introducer lands in one chunk and the terminator in the next."""

    def test_stream_handles_osc_split_across_chunks(self):
        # Title-set OSC: \x1b]0;title\x07 — split introducer / body / BEL.
        assert _joined("\x1b]0;title", "\x07body") == "body"

    def test_stream_handles_osc_introducer_alone(self):
        # Just the \x1b] in the first chunk.
        assert _joined("\x1b]", "0;title\x07body") == "body"

    def test_stream_handles_osc_terminated_by_st_across_chunks(self):
        # \x1b]8;;url\x1b\\  — hyperlink OSC ending with ST.
        assert _joined("\x1b]8;;url\x1b\\", "link\x1b]8;;\x1b\\") == "link"

    def test_stream_handles_osc_split_into_three_chunks(self):
        # Three chunks: ESC, body, terminator
        assert _joined("\x1b", "]0;title\x07", "body") == "body"

    def test_stream_osc_unterminated_at_end_is_dropped(self):
        # OSC never gets its terminator — must be dropped, not leaked.
        assert _joined("text\x1b]0;title") == "text"


class TestStreamSplitDcsAcrossChunks:
    """DCS / SOS / PM / APC all use ESC P|X|^|_ ... ST."""

    def test_stream_handles_dcs_split_across_chunks(self):
        # DCS body is everything between introducer and ST (per ECMA-48).
        # So \x1bP1;2;3 ... \x1b\\ is one DCS; 'abc' becomes part of the body
        # if it arrives between the introducer and ST. Result: 'end'.
        assert _joined("\x1bP1;2;3", "abc\x1b\\end") == "end"

    def test_stream_handles_dcs_with_terminator_split(self):
        # Split the DCS introducer and a later terminator pair — the body
        # is empty.
        assert _joined("\x1bP", "1;2;3\x1b\\end") == "end"

    def test_stream_handles_apollo_unterminated(self):
        # APC introducer ESC _ never terminated — should be dropped.
        assert _joined("text\x1b_garbage") == "text"


class TestStreamSplitCsiAcrossChunks:
    """CSI = ESC [ ... letter. Buffer partial CSI until the final byte."""

    def test_stream_consumes_partial_csi_between_chunks(self):
        # \x1b[3 in chunk 1, 1mhi\x1b[0m in chunk 2.
        assert _joined("text\x1b[3", "1mhi\x1b[0m") == "texthi"

    def test_stream_handles_csi_split_into_three_chunks(self):
        # ESC, [, rest — three chunks.
        assert _joined("a\x1b", "[3", "1mb\x1b[0m") == "ab"

    def test_stream_partial_csi_at_end_is_dropped(self):
        # No terminator — must be dropped.
        assert _joined("hello\x1b[3") == "hello"


class TestStreamLoneEsc:
    """Lone ESC = ESC with no following introducer (yet)."""

    def test_stream_consumes_lone_esc_between_chunks(self):
        # The trailing ESC is consumed by the next chunk — not leaked.
        assert _joined("text\x1b", "more") == "textmore"

    def test_stream_lone_esc_then_osc_introducer(self):
        # ESC then ] starts an OSC, must be buffered.
        assert _joined("text\x1b", "]0;title\x07body") == "textbody"

    def test_stream_lone_esc_at_end_is_dropped(self):
        # \x1b alone in the last chunk — drop.
        assert _joined("text\x1b") == "text"


class TestStreamUnicode:
    """Streaming must preserve Unicode byte-for-byte."""

    def test_stream_preserves_unicode(self):
        assert _joined("\x1b[31mcafé — 🚀\x1b[0m") == "café — 🚀"

    def test_stream_preserves_unicode_across_chunks(self):
        # Unicode in plain text, escape splits — must preserve.
        assert _joined("café \x1b", "[31mr🚀\x1b[0m") == "café r🚀"


class TestStreamBytesInput:
    """stream() accepts bytes and bytearray too."""

    def test_stream_accepts_bytes(self):
        assert "".join(stream(b"\x1b[31mhi\x1b[0m")) == "hi"

    def test_stream_mixes_bytes_and_str(self):
        assert "".join(stream(b"prefix\x1b", "[31msuf\x1b[0m")) == "prefixsuf"

    def test_stream_latin1_fallback(self):
        # invalid UTF-8 — falls back to latin-1, returns raw bytes decoded.
        result = "".join(stream(b"\xff\xfe\xfd"))
        assert result == "ÿþý"


class TestStreamEmptyAndEdge:
    def test_stream_with_no_args_yields_nothing(self):
        assert list(stream()) == []

    def test_stream_with_empty_chunks_yields_nothing(self):
        assert list(stream("", "", "")) == []

    def test_stream_yields_str_not_bytes(self):
        assert isinstance(next(stream("x")), str)

    def test_stream_yields_only_when_there_is_content(self):
        # Empty head chunks should not produce empty strings.
        outputs = list(stream("\x1b[31mhi\x1b[0m", "more", ""))
        # 'hi' from first chunk, 'more' from second; no empties.
        joined = "".join(outputs)
        assert joined == "himore"
        assert all(isinstance(o, str) for o in outputs)

    def test_stream_does_not_leak_partial_sequence_into_any_chunk(self):
        # The pre-fix bug yielded ['0;title', '\x07body'] — both leaks.
        chunks = list(stream("\x1b]0;title", "\x07body"))
        joined = "".join(chunks)
        assert "\x1b" not in joined
        assert "\x07" not in joined
        assert "0;title" not in joined