# scrublog

> Strip ANSI escape codes from logs, byte streams, and CLI output.
> One job. Done well. Zero dependencies.

```
$ echo -e '\033[31mERROR\033[0m: bad' | scrublog
ERROR: bad
```

## Why

Every developer hits this. You spawn a subprocess, capture its stdout, and
now your log file is full of `\x1b[31m`, `\x1b[1;32m`, `\x1b]8;;url\x1b\\` —
ANSI escape codes that are meaningful in a terminal but garbage in:

- log aggregators (Loki, Datadog, CloudWatch)
- structured JSON pipelines
- bug reports pasted into GitHub issues
- emails
- the file you're about to grep for `ERROR`

Existing solutions either:

1. Use fragile regex that misses OSC hyperlinks, 256-color, truecolor,
   DCS, or trailing incomplete sequences at end-of-stream, **or**
2. Bundle massive dependencies (`colorama`, `pyte`, etc.) for a 100-line job.

`scrublog` does it right, does it small, and does it without dependencies.

## Features

- ✅ Strips **all** ANSI escape classes: SGR (colors), CSI cursor / clear,
  OSC (terminal titles, hyperlinks), DCS, and single-char escapes
- ✅ Handles 16-color, **256-color**, and **truecolor (24-bit RGB)**
- ✅ Safely handles **incomplete / split escape sequences** at end of input
  and across stream chunks
- ✅ Works on `str` and `bytes` (auto-decodes UTF-8, falls back to latin-1)
- ✅ Preserves Unicode (emoji, combining marks, RTL)
- ✅ Streaming API for cleaning logs in chunks
- ✅ Ships as both a **library** (`from scrublog import clean`) and a
  **CLI** (`scrublog file.log` or `scrublog --stdin`)
- ✅ **Zero dependencies**, pure stdlib

## Install

```bash
pip install scrublog
```

Or from source:

```bash
git clone https://github.com/prasad-a-abhishek/scrublog
cd scrublog
pip install -e .
```

## Library usage

```python
from scrublog import clean, has_ansi, count_ansi, stream

# Strip ANSI from anything
clean("\x1b[31mhello\x1b[0m")        # => "hello"
clean(b"\x1b[38;5;208morange\x1b[0m") # => "orange"

# Truecolor
clean("\x1b[38;2;255;100;0mhi\x1b[0m") # => "hi"

# OSC hyperlinks (the modern terminal clickable link)
clean("\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\")  # => "link"

# Detect before cleaning
if has_ansi(line):
    line = clean(line)

# Count sequences (useful for telemetry / quality gates)
count_ansi(line_with_many_codes)  # => int

# Stream — safe even if escape sequences split across chunks
for clean_chunk in stream(raw_chunk_1, raw_chunk_2, raw_chunk_3):
    sink.write(clean_chunk)
```

## CLI usage

```
scrublog <file>          Strip ANSI from <file>, print to stdout.
scrublog <file> -i       Strip in place (overwrite the file).
scrublog --stdin         Read from stdin, write to stdout.
scrublog -               Shorthand for --stdin.
```

### Examples

Pipe through it:

```bash
$ ls --color=always /tmp | scrublog
file1
file2
...

$ docker logs mycontainer 2>&1 | scrublog > clean.log

$ npm test -- --color=always | scrublog > test-output.txt
```

Clean a file in place:

```bash
$ scrublog -i server.log
```

Inspect a log without ANSI noise:

```bash
$ grep -E "ERROR|FATAL" /var/log/app.log | scrublog
```

## Why another strip-ANSI library?

I wrote this because I needed a clean, dependency-free, well-tested
implementation that handles the messy cases:

- **Trailing `\x1b` at end of input** — caused by truncated logs or partial
  reads. Most regex-based strippers either keep it (so your log file ends
  with garbage) or crash. scrublog drops it.
- **OSC hyperlinks (`\x1b]8;;url\x1b\\…\x1b]8;;\x1b\\`)** — increasingly
  common in modern CLI tools. Naive regex misses them entirely.
- **Sequences split across stream chunks** — when reading from a subprocess
  pipe, you can get part of an escape sequence in one read and the rest in
  the next. `scrublog.stream()` buffers just enough to keep things sane.
- **Bytes vs str** — logs come in both. scrublog handles either, with
  latin-1 fallback for the rare non-UTF-8 garbage that shows up in the wild.

## Supported escape classes

| Class | Example | Stripped? |
|-------|---------|-----------|
| SGR (color) | `\x1b[31m` / `\x1b[1;31m` | ✅ |
| 256-color | `\x1b[38;5;208m` | ✅ |
| Truecolor | `\x1b[38;2;255;100;0m` | ✅ |
| Cursor movement | `\x1b[2J` / `\x1b[H` | ✅ |
| OSC title | `\x1b]0;title\x07` | ✅ |
| OSC hyperlink | `\x1b]8;;url\x1b\\…\x1b]8;;\x1b\\` | ✅ |
| DCS / SOS / PM / APC | `\x1bP…\x1b\\` | ✅ |
| Single-char (e.g. RIS) | `\x1b7` | ✅ |
| Incomplete / trailing | `text\x1b` or `text\x1b[31` | ✅ dropped cleanly |

## API reference

### `clean(s: str | bytes) -> str`

Return *s* with all ANSI escape sequences removed.

### `has_ansi(s: str | bytes) -> bool`

True if *s* contains at least one ANSI escape sequence.

### `count_ansi(s: str | bytes) -> int`

Number of distinct ANSI escape sequences in *s*.

### `stream(*chunks: str | bytes) -> Iterator[str]`

Generator that yields cleaned string chunks. Buffers incomplete escape
sequences across chunk boundaries so they never leak into output.

## Development

```bash
git clone https://github.com/prasad-a-abhishek/scrublog
cd scrublog
pip install -e ".[test]"
pytest                   # 25 tests, all green
```

Tested on Python 3.8 – 3.12.

## License

MIT © prasad-a-abhishek
