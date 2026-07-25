# scrublog

> Lossless ANSI escape sequence & color stripper for terminal logs.

## Quick Start

```bash
pip install scrublog
cat build.log | scrublog > clean.log
```

```python
from scrublog import clean
clean_text = clean("[32mHello World[0m")
```

## ⚡ Performance & Benchmarks

`scrublog` uses C-string fast-paths to outperform standard regex ANSI stripping by over **2.5x**.

| Workload Profile | `scrublog.clean()` | Standard Regex | Speed Advantage |
| :--- | :---: | :---: | :---: |
| **ANSI Log (1,000 lines)** | ⚡ **5.07 ms** | 12.76 ms | **2.5x Faster** |
| **ANSI Log (10,000 lines)** | ⚡ **49.94 ms** | 126.90 ms | **2.5x Faster** |
| **ESC Boundary Streaming** | 💡 **Native (`stream()`)** | 🛑 **Corrupts split bytes** | **Lossless** |

> **Replicate these results:** Run `python3 benchmarks/run_benchmark.py` directly inside this repository. See full matrix in [benchmarks/BENCHMARK.md](benchmarks/BENCHMARK.md).

## Features

- **Stream Chunking:** Handles ANSI sequences split across chunk boundaries without byte corruption.
- **OSC & Hyperlink Support:** Cleanly strips OSC terminal hyperlinks and title sequences.

## License

MIT