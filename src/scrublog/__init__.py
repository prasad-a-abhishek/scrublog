"""scrublog — strip ANSI escape codes from logs, byte streams, and CLI output.

Public API:
    clean(s)             -> str   Strip ANSI escapes from str or bytes.
    has_ansi(s)          -> bool  True if any ANSI sequence is present.
    count_ansi(s)        -> int   Count of distinct ANSI sequences.
    stream(*chunks)      -> iter  Generator yielding cleaned string chunks,
                                safe across escape boundaries split mid-stream.

Raises:
    ScrubError           For malformed or non-decodable bytes input.
                        (ScrubError is a subclass of ValueError.)
"""
from __future__ import annotations

import re
from typing import Iterator, Union

__version__ = "0.1.0"


class ScrubError(ValueError):
    """Raised when input cannot be processed (e.g. non-decodable bytes)."""


# ------------------------------------------------------------------
# ANSI pattern fragments (compiled once).
# ------------------------------------------------------------------
# References:
#   ECMA-48 (CSI / OSC / DCS / SOS / PM / APC)
#   https://en.wikipedia.org/wiki/ANSI_escape_code
#
# CSI:        ESC [ ... final      (params/intermediates 0x30-0x3F / 0x20-0x2F,
#                                  final 0x40-0x7E)
# OSC:        ESC ] ... BEL | ST
# DCS/SOS/PM/APC: ESC [PX^_] ... ST
# Single-char Fe (C0) escapes per ECMA-48: ESC followed by
#   @ A-Z \ ^ _ (i.e. 0x40-0x5F except ] for OSC).
#   In real-world terminals, \x1bc (lowercase RIS = Reset) is also used
#   by xterm and others. We accept lowercase 'c' explicitly (NOT via
#   re.IGNORECASE — that would erroneously swallow every lowercase
#   letter after a lone ESC, see BUG-2026-07-23).

# CSI: ESC [ params (0x30-0x3F)* intermediates (0x20-0x2F)* final (0x40-0x7E)
# The final-byte class already includes 0x61-0x7A (a-z) because ECMA-48's
# 0x40-0x7E range covers all ASCII letters, so we don't need IGNORECASE.
_CSI_RE = re.compile(
    r"\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"
)

# OSC: ESC ] body (BEL | ST) — body is anything except BEL or ESC; if ESC,
# it must be ST (\x1b\\).
_OSC_RE = re.compile(
    r"\x1b\](?:[^\x07\x1b]|\x1b\\)*(?:\x07|\x1b\\)"
)

# DCS / SOS / PM / APC: ESC [PX^_] body ST — body is anything except ESC;
# if ESC, it must be ST.
_DCS_RE = re.compile(
    r"\x1b[PX^_](?:[^\x1b]|\x1b\\)*\x1b\\"
)

# Single-char Fe escapes. The following introducers belong to multi-char
# sequences and MUST NOT match here:
#   [ (0x5B)  CSI introducer
#   ] (0x5D)  OSC introducer
#   P (0x50)  DCS introducer
#   X (0x58)  SOS introducer
#   ^ (0x5E)  PM introducer
#   _ (0x5F)  APC introducer
# So the standard single-char set is 0x40-0x5F minus {[, ], P, X, ^, _} =
# @ A-O Q-W Y Z \ 0x7F (DEL).
# Plus lowercase 'c' for RIS (xterm compat) — added explicitly, not via
# IGNORECASE, so we don't match every other lowercase letter.
_SINGLE_RE = re.compile(
    r"\x1b[@A-OQ-WYZ\\\x7f]|\x1bc"
)

# ------------------------------------------------------------------
# Trailing / partial sequence patterns.
# ------------------------------------------------------------------
# Scope (consistency rules):
# - Bare ESC (\x1b alone at end)        -> IS a sequence (incomplete Fe).
# - Partial CSI (no final byte)         -> IS a sequence (incomplete CSI).
# - Partial OSC body (no BEL/ST)        -> NOT a sequence (orphan introducer).
# - Partial DCS body (no ST)            -> NOT a sequence (orphan introducer).
#   ^ the above is for has_ansi/count_ansi/clean on a single string.
#     For stream() we are MORE LENIENT and buffer partial OSC/DCS bodies
#     too, because the next chunk might bring a terminator.

# Strict trailing detector (used by clean/has_ansi/count_ansi). Matches:
#   - bare ESC
#   - partial CSI (no final byte yet)
# Does NOT match partial OSC/DCS bodies — the rule is "no terminator = not
# a sequence". The TestLoneOscIntroducer / TestSingleCharEscapes tests
# pin this: count_ansi("\x1b]") == 0, count_ansi("\x1b]more text") == 0,
# count_ansi("\x1b_") == 0, count_ansi("\x1bP1;2;3") == 0.
_TRAILING_RE = re.compile(
    r"\x1b\[(?:[\x30-\x3f]*[\x20-\x2f]*)?\Z"
    r"|\x1b\Z"
)

# Stream-tail detector: ALSO catches bare OSC/DCS introducers AND partial
# OSC/DCS bodies, because the next chunk could bring a terminator. Used
# only inside stream() to decide what to buffer (not to strip or count).
_STREAM_TAIL_RE = re.compile(
    r"\x1b\[(?:[\x30-\x3f]*[\x20-\x2f]*)?\Z"
    r"|\x1b](?:[^\x07\x1b])*\Z"
    r"|\x1b[PX^_](?:[^\x1b])*\Z"
    r"|\x1b\Z"
)

# Used by clean(): match every kind of escape (complete or trailing partial).
_FULL_PATTERN = re.compile(
    "(" + _CSI_RE.pattern + ")"
    "|(" + _OSC_RE.pattern + ")"
    "|(" + _DCS_RE.pattern + ")"
    "|(" + _SINGLE_RE.pattern + ")"
    "|(" + _TRAILING_RE.pattern + ")"
)

# Used by has_ansi / count_ansi — same pattern, so the trio agrees.
_DETECT_PATTERN = _FULL_PATTERN

# Pattern used inside stream() for the head (everything except trailing tail).
# Note: this INCLUDES single-char Fe escapes, so a lone ESC followed by
# 'more' will see \x1b+M match _SINGLE_RE only if the char is in the set.
# The tail is held back separately to avoid leaking.
_HEAD_PATTERN = re.compile(
    "(" + _CSI_RE.pattern + ")"
    "|(" + _OSC_RE.pattern + ")"
    "|(" + _DCS_RE.pattern + ")"
    "|(" + _SINGLE_RE.pattern + ")"
)

# Single-char Fe introducers that can follow a lone ESC. Used by stream()
# to decide whether a held ESC should be dropped as a stray or kept as
# the start of a real sequence. Must be EXPLICIT — `.isalpha()` would
# also match 'm', 'o', 'r', 'e', etc. which are NOT escape introducers.
_SINGLE_FE_INTRODUCERS = frozenset(
    "@ABCDEFGHIJKLMNOQRSTUVWYZ\\"
    + "\x7f"  # DEL
    + "c"    # lowercase RIS (xterm compat)
)


def _as_text(s: Union[str, bytes, bytearray]) -> str:
    if isinstance(s, str):
        return s
    if isinstance(s, (bytes, bytearray)):
        try:
            return s.decode("utf-8")
        except UnicodeDecodeError:
            # Try latin-1 as a last resort — never loses data, never crashes.
            return s.decode("latin-1")
    raise ScrubError(f"expected str or bytes, got {type(s).__name__}")


def clean(s: Union[str, bytes, bytearray]) -> str:
    """Return *s* with all ANSI escape sequences removed.

    Always returns a fresh ``str`` object — even when the input contained
    no escapes. ``re.sub`` may return the same object on a no-op match;
    we explicitly copy via ``str.translate({})`` so callers can rely on
    ``clean(s) is not s`` (for non-empty inputs).

    Note: CPython interns the empty string ``""`` as a singleton, so
    ``clean("") is ""`` is True. This is a language-level guarantee, not
    a library contract violation.
    """
    text = _as_text(s)
    result = _FULL_PATTERN.sub("", text)
    if result is text:
        # Guarantee a fresh str object. ``str.translate({})`` always
        # returns a new object (it's defined to do so), unlike
        # ``str(s)``, ``"".join([s])`` etc. which return the same
        # interned singleton for literals.
        return result.translate({})
    return result


def has_ansi(s: Union[str, bytes, bytearray]) -> bool:
    """True if *s* contains at least one ANSI escape sequence.

    Counts:
      - complete sequences (CSI, OSC, DCS, single-char Fe)
      - trailing bare ESC (``"hello\\x1b"``)
      - trailing partial CSI (``"hello\\x1b[31"``)

    Does NOT count:
      - bare OSC introducer (``"\\x1b]"``) — orphan, not a sequence
      - bare DCS introducer (``"\\x1bP"``) — orphan, not a sequence
      - partial OSC body without BEL/ST (``"hello\\x1b]0;title"``)
      - partial DCS body without ST (``"hello\\x1bP1;2;3"``)
    """
    text = _as_text(s)
    return bool(_DETECT_PATTERN.search(text))


def count_ansi(s: Union[str, bytes, bytearray]) -> int:
    """Return the number of distinct ANSI escape sequences in *s*.

    Includes trailing partial sequences so the trio (has_ansi,
    count_ansi, clean) agrees on what counts.
    """
    text = _as_text(s)
    return sum(1 for _ in _DETECT_PATTERN.finditer(text))


# Buffer cap for partial escape sequences. Per ECMA-48, the longest
# introducer is 2 bytes; OSC/DCS bodies are unbounded. A real producer
# should never have an incomplete sequence longer than this; if it does
# (malicious input, corrupt stream), we flush instead of buffering forever.
_MAX_BUFFER_BYTES = 1024 * 1024  # 1 MiB


def stream(*chunks: Union[bytes, str]) -> Iterator[str]:
    """Generator: yield cleaned chunks of text.

    Accepts ``str`` or ``bytes``. Safely handles escape sequences that
    are split across consecutive chunks by buffering the partial tail
    until either a terminator arrives or the next chunk shows it's
    not actually an escape sequence after all.

    Bare OSC/DCS introducers (``\\x1b]``, ``\\x1bP``, ``\\x1bX``, ``\\x1b^``,
    ``\\x1b_``) are buffered across chunks because the next chunk may
    complete them. A bare ESC at the boundary is also held back so the
    next chunk can decide whether it was a one-char escape or the start
    of a multi-byte one.
    """
    buffer = ""
    for raw in chunks:
        if isinstance(raw, (bytes, bytearray)):
            try:
                c = raw.decode("utf-8")
            except UnicodeDecodeError:
                c = raw.decode("latin-1")
        else:
            c = raw
        buffer += c

        # If we have a held lone ESC in the buffer (the LAST \x1b), and
        # the byte after it is NOT an escape introducer, then the held
        # ESC was a single-char Fe that has been "completed" by a
        # non-escape byte → drop the held ESC and continue with the
        # rest of the buffer.
        last_esc = buffer.rfind("\x1b")
        if last_esc != -1 and last_esc < len(buffer) - 1:
            held = buffer[last_esc + 1]
            is_escape_introducer = (
                held in ("[", "]", "P", "X", "^", "_")
                or held in _SINGLE_FE_INTRODUCERS
            )
            if not is_escape_introducer:
                # The held ESC was a no-op; drop it from the buffer.
                buffer = buffer[:last_esc] + buffer[last_esc + 1:]

        # Find any partial escape at the tail and buffer it. The streaming
        # tail detector is more lenient than the one used by clean() —
        # it also catches bare OSC/DCS introducers and partial OSC/DCS
        # bodies, because the next chunk could bring a terminator.
        match = _STREAM_TAIL_RE.search(buffer)
        if match:
            head = buffer[: match.start()]
            tail = buffer[match.start():]
        else:
            head = buffer
            tail = ""

        # Safety: don't buffer unbounded partial sequences.
        if len(tail) > _MAX_BUFFER_BYTES:
            head = buffer
            tail = ""

        if head:
            cleaned = _HEAD_PATTERN.sub("", head)
            if cleaned:
                yield cleaned

        buffer = tail

    if buffer:
        # End-of-input: strip whatever is still in the buffer. The
        # buffer may contain a partial OSC/DCS body (no terminator yet)
        # or a bare ESC. Use the same lenient detector stream() uses
        # to decide what to strip — anything that _STREAM_TAIL_RE
        # would have held back gets dropped here.
        head, _tail = _split_at_tail(buffer)
        if head:
            cleaned = _HEAD_PATTERN.sub("", head)
            if cleaned:
                yield cleaned


def _split_at_tail(s: str) -> tuple[str, str]:
    """Return (head, tail) where tail is the partial-escape suffix.

    Used at end-of-input to identify and drop any held-but-incomplete
    escape sequence. The lenient stream-tail regex includes partial
    OSC/DCS bodies (no terminator) so they get dropped here.
    """
    m = _STREAM_TAIL_RE.search(s)
    if m:
        return s[: m.start()], s[m.start():]
    return s, ""
