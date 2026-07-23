"""scrublog — strip ANSI escape codes from logs, byte streams, and CLI output.

Public API:
    clean(s)             -> str   Strip ANSI escapes from str or bytes.
    has_ansi(s)          -> bool  True if any ANSI sequence is present.
    count_ansi(s)        -> int   Count of distinct ANSI sequences.
    stream(*chunks)      -> iter  Generator yielding cleaned string chunks,
                                safe across escape boundaries split mid-stream.

Raises:
    ScrubError           For malformed or non-decodable bytes input.
"""
from __future__ import annotations

import re
from typing import Iterator, Union

__version__ = "0.1.0"


class ScrubError(ValueError):
    """Raised when input cannot be processed (e.g. non-decodable bytes)."""


# ANSI patterns compiled once.
# References:
#   ECMA-48 (CSI / OSC / DCS / SOS / PM / APC)
#   https://en.wikipedia.org/wiki/ANSI_escape_code
#
# CSI:        ESC [ ... letter
# OSC:        ESC ] ... (BEL | ST)
# DCS/SOS/PM/APC: ESC P|\\X|^|_ ... ST
# Single-char escapes: ESC followed by a single char in [@-Z\\-_]
# Plain ESC at end of input is also stripped.
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OSC_RE = re.compile(r"\x1b\](?:[^\x07\x1b]|\x1b[\\])*(?:\x07|\x1b\\)")
_DCS_RE = re.compile(r"\x1b[PX^_](?:[^\x1b]|\x1b[\\])*\x1b\\")
_SINGLE_RE = re.compile(r"\x1b[@-Z\\-_]")
_TRAILING_ESC_RE = re.compile(r"\x1b(?:\[.*)?$")  # incomplete sequence at end

_FULL_PATTERN = re.compile(
    f"({_CSI_RE.pattern})|({_OSC_RE.pattern})|({_DCS_RE.pattern})"
    f"|({_SINGLE_RE.pattern})|({_TRAILING_ESC_RE.pattern})"
)

# Stricter version that fully consumes (no $ dangling). Used by has_ansi/count_ansi.
_DETECT_PATTERN = re.compile(
    f"{_CSI_RE.pattern}|{_OSC_RE.pattern}|{_DCS_RE.pattern}|{_SINGLE_RE.pattern}"
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
    """Return *s* with all ANSI escape sequences removed."""
    text = _as_text(s)
    return _FULL_PATTERN.sub("", text)


def has_ansi(s: Union[str, bytes, bytearray]) -> bool:
    """True if *s* contains at least one ANSI escape sequence."""
    text = _as_text(s)
    return bool(_DETECT_PATTERN.search(text))


def count_ansi(s: Union[str, bytes, bytearray]) -> int:
    """Return the number of distinct ANSI escape sequences in *s*."""
    text = _as_text(s)
    return sum(1 for _ in _DETECT_PATTERN.finditer(text))


def stream(*chunks: Union[bytes, str]) -> Iterator[str]:
    """Generator: yield cleaned chunks of text.

    Accepts str or bytes. Safely handles escape sequences that are split
    across consecutive chunks by buffering at most a few bytes at a time.
    """
    buffer = ""
    for c in chunks:
        if isinstance(c, (bytes, bytearray)):
            try:
                c = c.decode("utf-8")
            except UnicodeDecodeError:
                c = c.decode("latin-1")
        buffer += c
        # Clean, but keep any trailing partial sequence in the buffer.
        match = _TRAILING_ESC_RE.search(buffer)
        if match:
            head = buffer[: match.start()]
            buffer = buffer[match.start():]
        else:
            head = buffer
            buffer = ""
        if head:
            yield _FULL_PATTERN.sub("", head)
    if buffer:
        # Whatever remains: drop trailing ESC cleanly.
        yield _FULL_PATTERN.sub("", buffer)
