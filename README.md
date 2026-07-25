# scrublog

[![PyPI version](https://img.shields.io/pypi/v/scrublog.svg)](https://pypi.org/project/scrublog/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

> Lossless ANSI escape sequence & color stripper for terminal logs, build pipelines, and log aggregators.

## Quick Start

```bash
pip install scrublog
cat build.log | scrublog > clean.log
```

```python
from scrublog import clean

clean_text = clean("[32m2026-07-25 10:00:00[0m [1mINFO[0m [server.py] Request OK")
```

## ⚡ Performance & Benchmarks

`scrublog` uses C-string fast-paths to outperform standard regex ANSI stripping by over **2.5x**.

| Workload Profile | `scrublog.clean()` | Standard Regex | Speed Advantage | Peak RAM |
| :--- | :---: | :---: | :---: | :---: |
| **ANSI Log (1,000 lines)** | ⚡ **5.07 ms** | 12.76 ms | **2.5x Faster** | **0.57 MB** |
| **ANSI Log (10,000 lines)** | ⚡ **49.94 ms** | 126.90 ms | **2.5x Faster** | **5.64 MB** |
| **ESC Boundary Streaming** | 💡 **Native (`stream()`)** | 🛑 **Corrupts split bytes** | **Lossless** | N/A |

> **Replicate these results:** Run `python3 benchmarks/run_benchmark.py` directly inside this repository. See full matrix in [benchmarks/BENCHMARK.md](benchmarks/BENCHMARK.md).

## Why `scrublog`?

Most developers use simple `re.sub()` regex patterns to remove color codes from logs. However:
1. **Stream Chunk Corruption:** When logs stream over network sockets or stdout, ANSI sequences can be split right across chunk boundaries (e.g. `[` in chunk 1, `31m` in chunk 2). Regex corrupts these split sequences into garbage characters.
2. **Hyperlinks & Complex Sequences:** Regex fails or corrupts multi-byte ST/BEL terminators in OSC 8 hyperlinks.

`scrublog` provides a robust, state-machine driven parser that handles chunk boundaries safely without memory overhead.

## Key Features

- **Zero Runtime Dependencies:** Pure Python standard library implementation.
- **Stream Boundary Safety:** `scrublog.stream()` buffers partial ANSI sequences across iterator chunks.
- **Comprehensive Terminal Support:** Cleans SGR 256-color, TrueColor RGB, cursor movement, DEC private modes, and OSC hyperlinks.
- **In-Place File Cleaning:** Clean files directly via CLI with `--in-place`.

## CLI Usage

```bash
# Read stdin and output clean log to stdout
cat server.log | scrublog

# Clean a file in-place
scrublog --in-place build.log

# Stream log file directly
scrublog application.log > clean.log
```

## Python API Reference

```python
from scrublog import clean, stream, has_ansi, count_ansi

# Check if text contains ANSI codes
if has_ansi(log_line):
    print(f"Found {count_ansi(log_line)} ANSI sequences")

# Strip ANSI codes
clean_log = clean(raw_log)

# Stream processing across network/file chunks
for clean_chunk in stream(chunk_generator()):
    sys.stdout.write(clean_chunk)
```

## License

MIT © [Abhishek Prasad](https://github.com/prasad-a-abhishek)