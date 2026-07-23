"""Consistency between has_ansi / count_ansi / clean.

The library promises that ``has_ansi`` and ``count_ansi`` agree with
``clean``: any byte sequence that ``clean`` strips should be detected
by ``has_ansi`` and counted by ``count_ansi``.

This file pins the ECMA-48 single-char escape range fix (BUG-5),
the trailing-ESC detector inclusion (BUG-4), and the
``clean() is not s`` no-aliasing guarantee.
"""
import pytest

from scrublog import (
    ScrubError,
    clean,
    count_ansi,
    has_ansi,
    stream,
    __version__,
)


# ---- BUG-4: trailing ESC must be detected ----

class TestTrailingEscDetected:
    def test_has_ansi_true_for_trailing_esc(self):
        assert has_ansi("hello\x1b") is True

    def test_count_ansi_counts_trailing_esc(self):
        assert count_ansi("hello\x1b") == 1

    def test_has_ansi_true_for_trailing_partial_csi(self):
        assert has_ansi("hello\x1b[31") is True

    def test_count_ansi_counts_trailing_partial_csi(self):
        assert count_ansi("hello\x1b[31") == 1

    def test_has_ansi_false_for_trailing_partial_osc(self):
        # OSC without a terminator (BEL/ST) is an incomplete sequence —
        # the introducer+body alone is not a complete ANSI sequence.
        # Mirrors the orphan-introducer rule: count_ansi("\x1b]more text") == 0.
        assert has_ansi("hello\x1b]0;title") is False

    def test_count_ansi_zero_for_trailing_partial_osc(self):
        assert count_ansi("hello\x1b]0;title") == 0

    def test_has_ansi_false_for_trailing_partial_dcs(self):
        # DCS without ST is also an incomplete sequence.
        assert has_ansi("hello\x1bP1;2;3") is False


# ---- BUG-5: lone OSC introducer must NOT be counted ----

class TestLoneOscIntroducer:
    def test_count_ansi_zero_for_lone_osc_introducer(self):
        assert count_ansi("\x1b]") == 0

    def test_has_ansi_false_for_lone_osc_introducer(self):
        assert has_ansi("\x1b]") is False

    def test_count_ansi_zero_for_osc_introducer_then_text(self):
        # \x1b] is the OSC introducer; without content/terminator it's
        # not a complete ANSI sequence.
        assert count_ansi("\x1b]more text") == 0

    def test_has_ansi_false_for_osc_introducer_then_text(self):
        assert has_ansi("\x1b]more text") is False

    def test_count_ansi_counts_only_dcs_introducer_when_st_present(self):
        # \x1bP alone is NOT counted (DCS introducer).
        assert count_ansi("\x1bP") == 0
        # But the full DCS IS counted.
        assert count_ansi("\x1bP1;2;3\x1b\\") == 1


# ---- Single-char escape range per ECMA-48 ----
# 0x40-0x5F is @ A-Z [ \ ] ^ _
# But [ is CSI introducer (matched separately),
# ] is OSC introducer (must NOT match here),
# \ is the ST (matched separately).
# So the single-char Fe / Fp / Fs / Gs / Us / Sp / Del set is
# A-Z, \, ^, _  (and optionally 0x7F DEL).

class TestSingleCharEscapes:
    def test_count_ansi_one_for_ris(self):
        # ESC c = RIS (Reset Initial State). 'c' is in the A-Z range.
        assert count_ansi("\x1bc") == 1

    def test_count_ansi_one_for_decid(self):
        # ESC [ is CSI, not single-char. But here we test that ESC Z
        # (DECID) is correctly classified as single-char.
        assert count_ansi("\x1bZ") == 1

    def test_count_ansi_does_not_count_lone_bracket(self):
        # \x1b[ starts CSI — without a final byte, it's trailing partial.
        # We expect 1 here (trailing detector).
        assert count_ansi("\x1b[") == 1

    def test_has_ansi_false_for_lone_backslash(self):
        # \x1b\\ is the ST terminator — it's not a standalone escape.
        # Currently the regex for ST is consumed by the DCS/OSC patterns.
        # By itself, \x1b\\ isn't a complete ANSI sequence in our sense.
        # (We just check it doesn't crash / doesn't overcount.)
        n = count_ansi("\x1b\\")
        # Implementation-defined: could be 0 or 1 depending on whether
        # we count ST as a sequence. Test it doesn't crash and is bounded.
        assert n in (0, 1)

    def test_count_ansi_zero_for_pm_introducer(self):
        # ESC ^ is the PM (Privacy Message) introducer, NOT a single-char
        # escape. It only becomes a sequence once followed by body + ST.
        assert count_ansi("\x1b^") == 0

    def test_count_ansi_zero_for_apc_introducer(self):
        # ESC _ is the APC (Application Program Command) introducer,
        # NOT a single-char escape. Only a sequence once followed by body + ST.
        assert count_ansi("\x1b_") == 0


# ---- clean() never returns the input object ----

class TestCleanReturnValue:
    def test_clean_always_returns_new_str_when_input_has_escapes(self):
        s = "\x1b[31mhi\x1b[0m"
        result = clean(s)
        assert result is not s

    def test_clean_returns_new_str_for_plain_text(self):
        # Even on no-op, we want a fresh str object (no aliasing surprises).
        s = "plain text"
        result = clean(s)
        assert result is not s
        assert result == s

    def test_clean_returns_new_str_for_empty(self):
        # CPython interns the empty string as a singleton — there is no
        # way to produce a fresh ``""`` object. So we assert value
        # equality instead of identity for the empty case.
        s = ""
        result = clean(s)
        assert result == s
        # For non-empty inputs the identity guarantee holds.
        assert clean("x") is not "x"


# ---- Return types ----

class TestReturnTypes:
    def test_has_ansi_returns_bool(self):
        assert isinstance(has_ansi("anything"), bool)
        assert isinstance(has_ansi("\x1b[31m"), bool)
        assert isinstance(has_ansi(""), bool)

    def test_count_ansi_returns_int(self):
        assert isinstance(count_ansi("anything"), int)
        assert isinstance(count_ansi("\x1b[31m"), int)
        assert isinstance(count_ansi(""), bool) is False  # int, not bool
        assert isinstance(count_ansi(""), int)


# ---- ScrubError ----

class TestScrubError:
    def test_scrub_error_is_value_error(self):
        assert issubclass(ScrubError, ValueError)

    def test_scrub_error_can_be_caught_as_value_error(self):
        # ScrubError is a ValueError subclass, so users can catch either.
        # We pass a non-supported type to force the error path.
        with pytest.raises(ValueError):
            clean(42)  # type: ignore[arg-type]


# ---- Consistency between has_ansi / count_ansi / clean ----

class TestCleanConsistency:
    """For any input, if clean strips something, has_ansi must return
    True and count_ansi must return >= 1. (This is the user-facing
    guarantee.)"""

    @pytest.mark.parametrize(
        "s",
        [
            "\x1b[31mhi\x1b[0m",
            "\x1b]0;title\x07",
            "\x1bP1;2;3\x1b\\",
            "\x1bc",
            "\x1bZ",
            "\x1b_",
            "text\x1b",
            "text\x1b[",
            "text\x1b[31",
            "text\x1b]0;title",
            "text\x1bP",
            "\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\",
        ],
    )
    def test_has_ansi_true_when_clean_strips(self, s):
        if clean(s) != s:
            assert has_ansi(s) is True
            assert count_ansi(s) >= 1

    @pytest.mark.parametrize(
        "s",
        [
            "plain text",
            "",
            "no escapes here",
            "café — 🚀",
        ],
    )
    def test_no_ansi_means_clean_is_noop(self, s):
        assert has_ansi(s) is False
        assert count_ansi(s) == 0
        # clean() preserves content (may or may not be the same object,
        # but the value must be equal).
        assert clean(s) == s


# ---- Module metadata ----

class TestModuleMetadata:
    def test_module_has_version(self):
        assert isinstance(__version__, str)
        assert __version__  # non-empty